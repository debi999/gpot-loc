"""HTTP API 服务 —— 把内核暴露成本地 REST 接口。

前端（WebView2 里的纯静态页面）只对这里发请求；本模块是 UI ↔ 内核的
唯一耦合点。换 UI 技术栈（WebView2 / 真 WinUI3 壳 / tkinter）都不用动内核。

M2（2026-10-10）：全部端点接入真实内核（kernel.py = 旧库 v3.29 业务段），
并复用旧库 config.ini 持久化（kernel.load_config / save_config）。
"""
from __future__ import annotations

import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from gpot.core import (store as _store, detection, providers,
                       extract, translate, sink, pipeline,
                       kernel, kit_catalog, kit_installer)

# 应用级唯一状态实例
_STATE = _store.Store()

# 应用版本（老板 2026-10-10 指定：修改版从 V0.4* 起编号；/api/state 暴露，
# main.py 双开复用前比对——旧版本实例不复用，避免「双击 bat 还是老版本」）
APP_VERSION = "0.4.0"

# 旧库格式 config.ini（随 kernel 落在 core/ 目录）—— 提供方/游戏目录记忆
_CFG = kernel.load_config()

# 资源目录：src/gpot/ui/assets
_ASSETS = Path(__file__).resolve().parents[1] / "ui" / "assets"


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def _persist_config() -> None:
    """把 UI 配置写回旧库格式 config.ini（复用 kernel 的唯一实现）。"""
    kcfg = providers.to_kernel_cfg(_STATE.config)
    _CFG["provider"] = kcfg["provider"]
    _CFG["base"] = kcfg["base"]
    _CFG["model"] = kcfg["model"]
    _CFG["key"] = kcfg["key"]
    _CFG["appid"] = kcfg["appid"]
    _CFG["secret"] = kcfg["secret"]
    _CFG["src"] = kcfg["src"]
    _CFG["dst"] = kcfg["dst"]
    _CFG["prompt"] = kcfg["prompt"]
    try:
        kernel.save_config(_CFG)
    except Exception:
        pass


def _restore_config() -> None:
    """启动时把 config.ini 记忆值灌回 STATE（不自动解锁步骤）。"""
    if not _CFG:
        return
    c = _STATE.config
    c["provider"] = providers._NAME2KEY.get(_CFG.get("provider", ""), c["provider"])
    for k in ("base", "key", "model", "appid", "secret", "src", "dst", "prompt"):
        if _CFG.get(k):
            c[{"base": "address"}.get(k, k)] = _CFG[k]
    if _CFG.get("provider") == "本地Ollama/Qwen" and _CFG.get("model"):
        c["model"] = _CFG["model"]


def _kit_tools(engine: dict | None, deployed: bool = False) -> list:
    """注入工具清单（真实数据：kit_catalog.required_tools）。"""
    eng = (engine or {}).get("engine")
    if not eng:
        return []
    status = "已就位" if deployed else "待部署"
    out = []
    for p in (kit_catalog.required_tools(eng) or []):
        size = p.get("size")
        out.append({
            "name": p.get("title") or p.get("id", ""),
            "version": p.get("version", "—"),
            "size": (f"{size / 1e6:.1f} MB" if isinstance(size, (int, float)) else "—"),
            "verified": bool(p.get("verified")),
            "status": status,
        })
    return out


def _name_from_path(p: str) -> str:
    p = (p or "").rstrip("/\\")
    return p.split("/")[-1].split("\\")[-1] or "未命名游戏"


def _pick_folder() -> dict:
    """Windows 原生「选择文件夹」对话框（在 HTTP worker 线程内打开）。

    用 ctypes 调 SHBrowseForFolderW 而非 tkinter：tkinter 的对话框要求主线程，
    而本服务是 ThreadingHTTPServer 每请求一线程；SHBrowseForFolder 只要线程
    先 CoInitialize 即可。用户取消返回 {"canceled": True}。
    """
    if os.name != "nt":
        return {"path": None, "canceled": True,
                "message": "当前系统无原生对话框 · 请直接粘贴路径"}
    try:
        import ctypes
        from ctypes import wintypes

        class BROWSEINFOW(ctypes.Structure):
            _fields_ = [("hwndOwner", wintypes.HWND),
                        ("pidlRoot", ctypes.c_void_p),
                        ("pszDisplayName", wintypes.LPWSTR),
                        ("lpszTitle", wintypes.LPCWSTR),
                        ("ulFlags", wintypes.UINT),
                        ("lpfn", ctypes.c_void_p),
                        ("lParam", ctypes.c_void_p),
                        ("iImage", ctypes.c_int)]

        ole32 = ctypes.windll.ole32
        shell32 = ctypes.windll.shell32
        ole32.CoInitialize(None)
        try:
            BIF_RETURNONLYFSDIRS = 0x0001
            BIF_NEWDIALOGSTYLE = 0x0040    # 可新建文件夹的现代化样式
            buf = ctypes.create_unicode_buffer(260)
            bi = BROWSEINFOW()
            bi.pszDisplayName = buf
            bi.lpszTitle = "选择游戏根目录（含 BepInEx 或 *_Data 的目录）"
            bi.ulFlags = BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE
            pidl = shell32.SHBrowseForFolderW(ctypes.byref(bi))
            if not pidl:
                return {"path": None, "canceled": True}
            out = ctypes.create_unicode_buffer(260)
            ok = shell32.SHGetPathFromIDListW(pidl, out)
            ole32.CoTaskMemFree(pidl)
            return {"path": out.value if ok else None,
                    "canceled": not ok}
        finally:
            ole32.CoUninitialize()
    except Exception as e:   # 对话框打不开也不能把服务搞挂
        return {"path": None, "message": "对话框打开失败（%s）· 请直接粘贴路径"
                % str(e)[:120]}


# ---------------------------------------------------------------------------
# 请求处理器
# ---------------------------------------------------------------------------
class _Handler(BaseHTTPRequestHandler):
    server_version = "G-POT-API/0.2"

    def _send(self, code: int, payload=None, ctype="application/json; charset=utf-8"):
        body = b""
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _send_raw(self, code: int, data: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        if data:
            self.wfile.write(data)

    def _json_body(self) -> dict:
        try:
            ln = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(ln) if ln else b"{}"
            return json.loads(raw or b"{}")
        except Exception:
            return {}

    def _static(self, rel: str, ctype: str):
        fp = _ASSETS / rel
        if not fp.is_file() or not str(fp.resolve()).startswith(str(_ASSETS.resolve())):
            return self._send(404, {"error": "not found"})
        try:
            data = fp.read_bytes()
        except OSError:
            return self._send(404, {"error": "not found"})
        self._send_raw(200, data, ctype)

    def _ctype(self, path: str) -> str:
        mt, _ = mimetypes.guess_type(path)
        if mt in ("text/css", "application/javascript", "text/html"):
            return f"{mt}; charset=utf-8"
        return mt or "application/octet-stream"

    def log_message(self, *a):  # 静默默认日志
        pass

    # -------------------- GET --------------------
    def do_GET(self):
        p = urlparse(self.path)
        path = p.path
        if path in ("/", "/index.html"):
            return self._static("index.html", "text/html; charset=utf-8")
        if path.startswith("/assets/"):
            return self._static(path[len("/assets/"):], self._ctype(path))
        if path == "/api/state":
            d = _STATE.to_dict()
            d["app_version"] = APP_VERSION
            return self._send(200, d)
        if path == "/api/providers":  # FR-38: 列出翻译后端（第 0 步配置）
            return self._send(200, {"providers": providers.list_providers()})
        if path.startswith("/api/sink"):
            q = parse_qs(p.query)
            ek = (q.get("engine", [None])[0]
                  or (_STATE.engine or {}).get("key")
                  or "unity")
            return self._send(200, sink.sink_view(ek, _STATE))
        if path.startswith("/api/verify"):  # FR-45: 启动验证（第 6 步·应用结果闭环）
            return self._send(200, sink.verify(_STATE))
        if path.startswith("/api/jobs/"):
            jid = path.rsplit("/", 1)[-1]
            j = translate.get_job(_STATE, jid)
            return self._send(200 if j else 404, j or {"error": "no such job"})
        if path == "/api/pick-folder":  # 第 1 步「浏览」：原生文件夹选择对话框
            return self._send(200, _pick_folder())
        if path.startswith("/api/rows"):  # 第 4 步表格：真实条目（分页/筛选）
            return self._send(200, self._rows(parse_qs(p.query)))
        # 兜底：其余 GET 路径尝试作为 assets 静态文件伺服（兼容相对路径引用，
        # 使 index.html 在 file:// 下双击也能完整加载 CSS/JS）。找不到仍 404。
        return self._static(path.lstrip("/"), self._ctype(path))

    @staticmethod
    def _rows(q: dict) -> dict:
        t = _STATE.tstore
        status = (q.get("status", ["all"])[0])
        kw = (q.get("q", [""])[0] or "").strip().lower()
        limit = min(5000, max(1, int(q.get("limit", ["5000"])[0])))
        _SMAP = {"translated": "ok", "english": "warn", "untranslated": "todo"}
        rows = []
        for i, e in enumerate(t.entries):
            s = _SMAP.get(e["status"], e["status"])
            if status != "all" and s != status:
                continue
            if kw and kw not in e["original"].lower() \
                    and kw not in e["translation"].lower():
                continue
            rows.append({"i": i, "o": e["original"], "t": e["translation"], "s": s})
        return {"total": len(t.entries), "shown": len(rows[:limit]),
                "rows": rows[:limit]}

    # -------------------- POST --------------------
    def do_POST(self):
        p = urlparse(self.path)
        path = p.path
        b = self._json_body()

        if path == "/api/config":  # FR-38: 配置翻译服务 + 连通测试（第 0 步）
            for k in ("provider", "model", "address", "key", "appid",
                      "secret", "src", "dst", "prompt"):
                if k in b:
                    _STATE.config[k] = b[k]
            r = providers.test_connection(_STATE.config)
            _STATE.config["connected"] = r["connected"]
            if r["connected"]:
                pipeline.complete_step(_STATE, 0)
            _persist_config()
            return self._send(200, {"config": _STATE.config, **r})

        if path == "/api/game":  # FR-39: 选择游戏目录（第 1 步，真实载入已有译文）
            gp = (b.get("path") or "").strip()
            if not gp or not os.path.isdir(gp):
                return self._send(400, {"error": "bad_path",
                                        "message": "目录不存在：%s" % gp})
            # 选到上层目录时自动下钻定位游戏根（否则已有译文词典找不到 → 看起来"无文本"）
            relocated = None
            gp2, relocated = detection.resolve_game_root(gp)
            gp = gp2
            _STATE.game = {"path": gp, "name": b.get("name") or _name_from_path(gp),
                           "existing": 0, "relocated": relocated}
            tpath = kernel.translation_file_path(gp)
            t = _STATE.tstore
            t.entries = []
            if os.path.isfile(tpath):
                try:
                    t.load(tpath)
                except Exception:
                    t.entries = []
            t.path = tpath
            st = t.stats()
            _STATE.game["existing"] = st["total"]
            _STATE.translate.update({"total": st["total"], "done": st["translated"],
                                     "failed": st["untranslated"]})
            # 游戏目录记忆（旧库 v3.18 语义：优先记忆值 + 最近 5 个）
            gp_norm = os.path.abspath(gp)
            _CFG["game_dir"] = gp_norm
            recent = [d for d in (_CFG.get("recent_dirs") or []) if d != gp_norm]
            _CFG["recent_dirs"] = ([gp_norm] + recent)[:5]
            _persist_config()
            pipeline.complete_step(_STATE, 1)
            return self._send(200, _STATE.game)

        if path == "/api/detect":  # FR-40: 识别引擎（第 2 步，真实启发式）
            eng = detection.detect_engine(_STATE.game.get("path", ""))
            _STATE.engine = eng
            _STATE.kit = {"deployed": False, "tools": _kit_tools(eng)}
            pipeline.complete_step(_STATE, 2)
            return self._send(200, eng)

        if path == "/api/deploy":  # FR-41: 部署注入工具（第 2 步·真实下载部署）
            eng = (_STATE.engine or {}).get("engine")
            gdir = _STATE.game.get("path", "")
            if not eng or not gdir:
                return self._send(400, {"error": "no_engine",
                                        "message": "该引擎没有可部署的工具包"})
            logs: list[str] = []

            def log(s) -> None:
                logs.append(str(s))

            try:
                kit_installer.install_kit(eng, gdir, log=log)
            except Exception as e:
                return self._send(500, {"error": "deploy_failed",
                                        "message": str(e)[:300], "log": logs[-20:]})
            _STATE.kit = {"deployed": True, "tools": _kit_tools(_STATE.engine, True),
                          "log": logs[-20:]}
            return self._send(200, _STATE.kit)

        if path == "/api/extract":  # FR-42: 提取待翻译文本与护栏（第 3 步，真实提取）
            try:
                return self._send(200, extract.extract(_STATE, b))
            except Exception as e:
                return self._send(500, {"error": "extract_failed",
                                        "message": str(e)[:300]})

        if path == "/api/translate/start":  # FR-43: 启动翻译任务（第 4 步，真实后端）
            jid = translate.start_translate(_STATE, bool(b.get("retry")))
            if jid is None:
                return self._send(409, {"error": "running",
                                        "message": "已有翻译任务在进行"})
            return self._send(200, {"job_id": jid if jid != "done" else None,
                                    "done_all": jid == "done"})

        if path.startswith("/api/jobs/") and path.endswith("/cancel"):
            jid = path.rsplit("/", 2)[-2]
            return self._send(200, {"ok": translate.cancel_job(_STATE, jid)})

        if path == "/api/sink/apply":  # FR-44（真实落盘）& FR-48（引擎锁死校验）
            ek = b.get("engine") or (_STATE.engine or {}).get("key") or "unity"
            detected = (_STATE.engine or {}).get("key") or "unity"
            if ek != detected:
                return self._send(400, {"error": "engine_mismatch",
                                        "message": f"当前游戏管线为 {detected}，不能按 {ek} 管线写入"})
            try:
                return self._send(200, sink.apply(_STATE, ek))
            except Exception as e:
                return self._send(500, {"error": "apply_failed",
                                        "message": str(e)[:300]})

        if path == "/api/restore":  # FR-44: 还原原文（rewrite 管线）
            bk = (_STATE.sink or {}).get("backup")
            if not bk or not os.path.isdir(bk):
                return self._send(400, {"error": "no_backup",
                                        "message": "没有可用的原文备份"})
            gdir = _STATE.game.get("path", "")
            try:
                _ok, data_dir, _e = kernel.rpgmaker_engine.detect(gdir)
                if not _ok:
                    raise RuntimeError("不是 RPG Maker MV/MZ 工程")
                kernel.rpgmaker_engine.restore(bk, data_dir)
                _STATE.sink["backup"] = None
                return self._send(200, {"ok": True, "restored_from": bk})
            except Exception as e:
                return self._send(500, {"error": "restore_failed",
                                        "message": str(e)[:300]})

        if path == "/api/nav":  # FR-36: 导航锁（只落已解锁区间）
            ok = _STATE.nav(int(b.get("step", 0)))
            return self._send(200 if ok else 400, _STATE.to_dict())

        if path == "/api/reset":
            _STATE.reset()
            return self._send(200, _STATE.to_dict())

        return self._send(404, {"error": "not found"})


class _Srv(ThreadingHTTPServer):
    # Windows 上 SO_REUSEADDR 允许第二个实例静默同绑同一端口（请求流向不可控，
    # 表现为"时灵时不灵"的诡异 bug）——必须关掉，让双开走到 main.py 的复用/换端口逻辑。
    allow_reuse_address = False
    daemon_threads = True


def build_server(port: int = 8731) -> ThreadingHTTPServer:
    _restore_config()
    return _Srv(("127.0.0.1", port), _Handler)


if __name__ == "__main__":
    srv = build_server()
    srv.serve_forever()
