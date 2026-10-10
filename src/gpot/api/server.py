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
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from gpot.core import (store as _store, detection, providers,
                       extract, translate, sink, pipeline,
                       kernel, kit_catalog, kit_installer)

# 应用级唯一状态实例
_STATE = _store.Store()

# 应用版本（FR-51: 版本唯一真源，随 /api/state 暴露、状态栏常显、双开复用前比对——
# 旧版本实例不复用，避免「双击 bat 还是老版本」；老板 2026-10-10 指定 V0.4* 起编号）
APP_VERSION = "0.4.6"

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


def _persist_flow() -> None:
    """FR-37: 步骤状态持久化 —— current_step / max_step 写 config.ini（flow.* 键）。"""
    _CFG["flow.current_step"] = str(_STATE.current_step)
    _CFG["flow.max_step"] = str(_STATE.max_step)
    try:
        kernel.save_config(_CFG)
    except Exception:
        pass


def _restore_flow() -> None:
    """FR-37: 启动时回到上次所在步骤（无记录 / 首次启动 → 第 0 步）。"""
    try:
        cur = int(str(_CFG.get("flow.current_step", "") or ""), 10)
        mx = int(str(_CFG.get("flow.max_step", "") or ""), 10)
    except ValueError:
        return                      # 从未走过流程 → 保持第 0 步
    _STATE.max_step = max(0, min(mx, len(_store.STEPS) - 1))
    _STATE.current_step = max(0, min(cur, _STATE.max_step))


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


def _recent_list() -> list:  # FR-39: 最近使用列表（HTTP 薄委托；实现唯一真源 core/store.recent_games）
    return _store.recent_games(_CFG.get("recent_dirs") or [])


def _name_from_path(p: str) -> str:
    return _store.name_from_path(p)


def _sync_translate_metrics() -> None:
    """第 4 步指标 = tstore 真实统计。

    任何改表操作（行编辑/替换/去重/导入）之后都必须同步——2026-10-10
    codegraph 评估 P1：replace/dedup 后指标曾停留旧值。
    """
    st = _STATE.tstore.stats()
    _STATE.translate.update({"total": st["total"], "done": st["translated"],
                             "failed": st["untranslated"]})


_CLSID_FILE_OPEN_DIALOG = "DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7"
_IID_I_FILE_OPEN_DIALOG = "D57C7288-D4AD-4768-BE02-9D969532D960"


def _pick_folder() -> dict:  # FR-52: 第 1 步「浏览」——现代版目录选择器（老式 SHBrowse 仅兜底）
    """Windows「浏览文件夹」对话框（在 HTTP worker 线程内打开）。

    首选现代版 IFileOpenDialog（Vista 通用项对话框，老板 2026-10-10 指定），
    失败时兜底旧式 SHBrowseForFolderW。用户取消返回 {"canceled": True}。
    """
    if os.name != "nt":
        return {"path": None, "canceled": True,
                "message": "当前系统无原生对话框 · 请直接粘贴路径"}
    try:
        return _pick_folder_modern()
    except Exception:
        pass
    return _pick_folder_legacy()


def _pick_folder_modern() -> dict:
    """现代版文件夹选择（IFileDialog COM 直调，ctypes 无第三方依赖）。"""
    import ctypes
    from ctypes import wintypes

    PVOID = ctypes.c_void_p

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    def _guid(s: str) -> GUID:
        g = GUID()
        hr = ctypes.windll.ole32.CLSIDFromString(
            ctypes.c_wchar_p("{%s}" % s.strip("{}")), ctypes.byref(g))
        if hr != 0:
            raise OSError("CLSIDFromString 0x%08X" % (hr & 0xFFFFFFFF))
        return g

    def _m(obj: int, idx: int, restype, *argtypes):
        """取 COM 对象虚表第 idx 个方法（0 起算，含 IUnknown 三件套）。"""
        vtbl = ctypes.cast(PVOID(obj), ctypes.POINTER(PVOID)).contents.value
        fp = ctypes.cast(PVOID(vtbl + idx * ctypes.sizeof(PVOID)),
                         ctypes.POINTER(PVOID)).contents.value
        return ctypes.WINFUNCTYPE(restype, PVOID, *argtypes)(fp)

    ole32 = ctypes.windll.ole32
    ole32.CoInitialize(None)
    dlg = PVOID()
    hr = ole32.CoCreateInstance(ctypes.byref(_guid(_CLSID_FILE_OPEN_DIALOG)),
                                None, 1,   # CLSCTX_INPROC_SERVER
                                ctypes.byref(_guid(_IID_I_FILE_OPEN_DIALOG)),
                                ctypes.byref(dlg))
    if hr != 0 or not dlg.value:
        raise OSError("CoCreateInstance 0x%08X" % (hr & 0xFFFFFFFF))
    try:
        # SetOptions：FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST
        _m(dlg.value, 9, HRESULT, wintypes.DWORD)(dlg, 0x20 | 0x40 | 0x800)
        _m(dlg.value, 17, HRESULT, wintypes.LPCWSTR)(
            dlg, "选择游戏根目录（含 BepInEx 或 *_Data 的目录）")
        hr = _m(dlg.value, 3, HRESULT, wintypes.HWND)(dlg, None)   # Show
        if hr != 0:   # 0x800704C7 = 取消；其余失败同样按未选择处理
            return {"path": None, "canceled": True}
        psi = PVOID()
        hr = _m(dlg.value, 20, HRESULT, PVOID)(dlg, ctypes.byref(psi))  # GetResult
        if hr != 0 or not psi.value:
            return {"path": None, "canceled": True}
        try:
            ppsz = PVOID()
            hr = _m(psi.value, 5, HRESULT, wintypes.DWORD, PVOID)(
                psi, 0x80058000, ctypes.byref(ppsz))   # GetDisplayName(FILESYSPATH)
            if hr != 0 or not ppsz.value:
                return {"path": None, "canceled": True}
            try:
                path = ctypes.wstring_at(ppsz.value)
            finally:
                ole32.CoTaskMemFree(ppsz)
            return {"path": path, "canceled": False}
        finally:
            _m(psi.value, 2, wintypes.DWORD)(psi)      # Release
    finally:
        _m(dlg.value, 2, wintypes.DWORD)(dlg)          # Release
        ole32.CoUninitialize()


def _pick_file() -> dict:  # FR-52: 文件选择（CSV 导入用）——同族对话框，选文件不选文件夹
    if os.name != "nt":
        return {"path": None, "canceled": True,
                "message": "当前系统无原生对话框 · 请直接输入 CSV 路径"}
    try:
        return _pick_file_modern()
    except Exception:
        return {"path": None, "canceled": True, "message": "无法打开文件选择器"}


def _pick_file_modern() -> dict:
    """现代版文件选择（IFileDialog，FOS_FILEMUSTEXIST，CSV 过滤）。"""
    import ctypes
    from ctypes import wintypes

    PVOID = ctypes.c_void_p

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    class FILTERSPEC(ctypes.Structure):
        _fields_ = [("name", wintypes.LPCWSTR), ("spec", wintypes.LPCWSTR)]

    def _guid(s: str) -> GUID:
        g = GUID()
        hr = ctypes.windll.ole32.CLSIDFromString(
            ctypes.c_wchar_p("{%s}" % s.strip("{}")), ctypes.byref(g))
        if hr != 0:
            raise OSError("CLSIDFromString 0x%08X" % (hr & 0xFFFFFFFF))
        return g

    def _m(obj: int, idx: int, restype, *argtypes):
        vtbl = ctypes.cast(PVOID(obj), ctypes.POINTER(PVOID)).contents.value
        fp = ctypes.cast(PVOID(vtbl + idx * ctypes.sizeof(PVOID)),
                         ctypes.POINTER(PVOID)).contents.value
        return ctypes.WINFUNCTYPE(restype, PVOID, *argtypes)(fp)

    ole32 = ctypes.windll.ole32
    ole32.CoInitialize(None)
    dlg = PVOID()
    hr = ole32.CoCreateInstance(ctypes.byref(_guid(_CLSID_FILE_OPEN_DIALOG)),
                                None, 1, ctypes.byref(_guid(_IID_I_FILE_OPEN_DIALOG)),
                                ctypes.byref(dlg))
    if hr != 0 or not dlg.value:
        raise OSError("CoCreateInstance 0x%08X" % (hr & 0xFFFFFFFF))
    try:
        # SetFileTypes（vtable=4）：CSV / 全部文件
        filters = (FILTERSPEC * 2)(
            FILTERSPEC(name="CSV 译文表", spec="*.csv"),
            FILTERSPEC(name="全部文件", spec="*.*"))
        _m(dlg.value, 4, HRESULT, wintypes.UINT, PVOID)(dlg, 2, filters)
        # SetOptions：FOS_FILEMUSTEXIST | FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST
        _m(dlg.value, 9, HRESULT, wintypes.DWORD)(dlg, 0x4 | 0x40 | 0x800)
        _m(dlg.value, 17, HRESULT, wintypes.LPCWSTR)(dlg, "选择要导入的 CSV 译文表")
        hr = _m(dlg.value, 3, HRESULT, wintypes.HWND)(dlg, None)   # Show
        if hr != 0:
            return {"path": None, "canceled": True}
        psi = PVOID()
        hr = _m(dlg.value, 20, HRESULT, PVOID)(dlg, ctypes.byref(psi))  # GetResult
        if hr != 0 or not psi.value:
            return {"path": None, "canceled": True}
        try:
            ppsz = PVOID()
            hr = _m(psi.value, 5, HRESULT, wintypes.DWORD, PVOID)(
                psi, 0x80058000, ctypes.byref(ppsz))
            if hr != 0 or not ppsz.value:
                return {"path": None, "canceled": True}
            try:
                path = ctypes.wstring_at(ppsz.value)
            finally:
                ole32.CoTaskMemFree(ppsz)
            return {"path": path, "canceled": False}
        finally:
            _m(psi.value, 2, wintypes.DWORD)(psi)
    finally:
        _m(dlg.value, 2, wintypes.DWORD)(dlg)
        ole32.CoUninitialize()


def _pick_folder_legacy() -> dict:
    """旧式 SHBrowseForFolder 兜底（ctypes 调用，线程内先 CoInitialize）。"""
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
            # 结构体指针字段不能直接赋 c_wchar 数组（ctypes 报 incompatible
            # types）——必须 cast 成 LPWSTR；pszDisplayName 只回显选中名，可空
            bi.pszDisplayName = ctypes.cast(buf, wintypes.LPWSTR)
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
        if path == "/api/recent":  # FR-39: 最近使用列表
            return self._send(200, {"recent": _recent_list()})
        if path == "/api/pick-folder":  # FR-52: 第 1 步「浏览」——原生文件夹选择对话框
            return self._send(200, _pick_folder())
        if path == "/api/rows":   # 第 4 步表格：真实条目（分页/筛选/搜索）
            return self._send(200, self._rows(parse_qs(p.query)))
        # 兜底：其余 GET 路径尝试作为 assets 静态文件伺服（兼容相对路径引用，
        # 使 index.html 在 file:// 下双击也能完整加载 CSS/JS）。找不到仍 404。
        return self._static(path.lstrip("/"), self._ctype(path))

    @staticmethod
    def _rows(q: dict) -> dict:
        t = _STATE.tstore
        limit = min(5000, max(1, int(q.get("limit", ["5000"])[0])))
        offset = max(0, int(q.get("offset", ["0"])[0]))
        # FR-43: 筛选（SMAP 映射/搜索/状态）唯一实现在 core/translate.filter_entries
        # —— 不在此复制第二份（2026-10-10 评估 P1：双份映射表是「筛不中」bug 的温床）
        matched = [{"i": i, "o": e["original"], "t": e["translation"],
                    "s": translate.SMAP.get(e["status"], e["status"])}
                   for i, e in translate.filter_entries(t, {
                       "q": q.get("q", [""])[0],
                       "status": q.get("status", ["all"])[0]})]
        page = matched[offset:offset + limit]
        return {"total": len(t.entries), "matched": len(matched),
                "shown": len(page), "rows": page}

    def _row_edit(self, b: dict) -> tuple:
        """双击行内编辑译文（HTTP 映射；逻辑在 core/store.edit_row，i = 条目序号）。"""
        try:
            i = int(b.get("i", -1))
        except (TypeError, ValueError):
            return 400, {"error": "bad_index", "message": "条目序号无效"}
        e = _store.edit_row(_STATE.tstore, i, str(b.get("translation", "")))
        if e is None:
            return 400, {"error": "bad_index", "message": "条目序号无效"}
        try:
            _STATE.tstore.save(_STATE.tstore.path)
        except Exception as ex:
            return 500, {"error": "save_failed", "message": "写盘失败：%s" % str(ex)[:180]}
        _sync_translate_metrics()
        return 200, {"ok": True, "status": e["status"], "stats": _STATE.tstore.stats()}

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
            _persist_flow()   # FR-37
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
            _persist_flow()   # FR-37
            return self._send(200, _STATE.game)

        if path == "/api/detect":  # FR-40: 识别引擎（第 2 步，真实启发式）· FR-41: 工具清单随回
            eng = detection.detect_engine(_STATE.game.get("path", ""))
            _STATE.engine = eng
            _STATE.kit = {"deployed": False, "tools": _kit_tools(eng), "skipped": False}
            pipeline.complete_step(_STATE, 2)
            _persist_flow()   # FR-37
            return self._send(200, {**eng, "kit": _STATE.kit})

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
                out = extract.extract(_STATE, b)
                _persist_flow()   # FR-37
                return self._send(200, out)
            except Exception as e:
                return self._send(500, {"error": "extract_failed",
                                        "message": str(e)[:300]})

        if path == "/api/translate/start":  # FR-43: 启动翻译任务（第 4 步，真实后端；scope=todo/filtered/all/retry）
            scope = b.get("scope") or ("retry" if b.get("retry") else "todo")
            flt = {"q": b.get("q", ""), "status": b.get("status", "all")}
            jid = translate.start_translate(_STATE, bool(b.get("retry")),
                                            scope=scope, flt=flt)
            _persist_flow()   # FR-37
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
                out = sink.apply(_STATE, ek)
                _persist_flow()   # FR-37
                return self._send(200, out)
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

        if path == "/api/launch":  # FR-45: 第 6 步「启动游戏验证」——真启动游戏
            gdir = _STATE.game.get("path", "")
            if not gdir or not os.path.isdir(gdir):
                return self._send(400, {"error": "no_game",
                                        "message": "先在第 1 步选择游戏目录"})
            exe = detection.find_game_exe(gdir)
            if not exe:
                return self._send(400, {"error": "no_exe",
                                        "message": "游戏目录里没找到可执行的游戏 .exe"})
            try:
                os.startfile(exe)   # 独立进程启动，生命周期与翻译器无关
                return self._send(200, {"ok": True, "exe": exe})
            except Exception as e:
                return self._send(500, {"error": "launch_failed",
                                        "message": "启动失败：%s" % str(e)[:200]})

        if path == "/api/open-dir":  # 第 6 步「打开译文目录」
            gdir = _STATE.game.get("path", "")
            tp = kernel.translation_file_path(gdir) if gdir else ""
            d = os.path.dirname(tp) if tp else ""
            if not d or not os.path.isdir(d):
                return self._send(400, {"error": "no_dir",
                                        "message": "译文目录还不存在（先走完第 5 步保存）"})
            try:
                os.startfile(d)
                return self._send(200, {"ok": True, "dir": d})
            except Exception as e:
                return self._send(500, {"error": "open_failed",
                                        "message": "打开失败：%s" % str(e)[:200]})

        if path == "/api/row/edit":  # 第 4 步双击行内编辑译文（立即落盘）
            code, payload = self._row_edit(b)
            return self._send(code, payload)

        if path == "/api/export-csv":  # FR-43: 导出 CSV（UTF-8-sig，人工回填/备份用）
            t = _STATE.tstore
            if not t.entries:
                return self._send(400, {"error": "empty",
                                        "message": "还没有条目可导出（先在第 3 步提取）"})
            out_dir = os.path.dirname(t.path) if t.path else os.getcwd()
            os.makedirs(out_dir, exist_ok=True)
            out = os.path.join(out_dir,
                               "gpot-export-%s.csv" % time.strftime("%Y%m%d-%H%M%S"))
            try:
                kernel.export_csv(t, out)
            except Exception as e:
                return self._send(500, {"error": "export_failed",
                                        "message": str(e)[:200]})
            return self._send(200, {"ok": True, "path": out, "rows": len(t.entries)})

        if path == "/api/import-csv":  # FR-43: 导入 CSV（merge：按原文合并，无路径时先弹文件对话框）
            ip = b.get("path")
            if not ip:
                ip = (_pick_file() or {}).get("path")
                if not ip:
                    return self._send(200, {"canceled": True})
            if not os.path.isfile(ip):
                return self._send(400, {"error": "bad_file",
                                        "message": "文件不存在：%s" % ip})
            try:
                n = kernel.import_csv(_STATE.tstore, ip, mode="merge")
            except Exception as e:
                return self._send(500, {"error": "import_failed",
                                        "message": str(e)[:200]})
            if n:
                _STATE.tstore.save(_STATE.tstore.path)   # 立即落盘
            _sync_translate_metrics()
            st = _STATE.tstore.stats()
            return self._send(200, {"ok": True, "updated": n, "path": ip,
                                    "total": st["total"], "translated": st["translated"]})

        if path == "/api/replace":  # FR-43: 查找替换（core 实现，立即落盘 + 指标同步）
            n = _store.replace_rows(_STATE.tstore, b.get("find", ""),
                                    b.get("replace", ""), b.get("field", "translation"),
                                    case_sensitive=bool(b.get("case_sensitive", True)))
            if n:
                try:
                    _STATE.tstore.save(_STATE.tstore.path)
                except Exception as ex:
                    return self._send(500, {"error": "save_failed",
                                            "message": "写盘失败：%s" % str(ex)[:180]})
            _sync_translate_metrics()
            st = _STATE.tstore.stats()
            return self._send(200, {"ok": True, "replaced": n,
                                    "stats": {"total": st["total"],
                                              "translated": st["translated"],
                                              "untranslated": st["untranslated"]}})

        if path == "/api/dedup":  # FR-43: 清理重复（归一化键，有译文优先；立即落盘 + 指标同步）
            removed = _store.dedup_rows(_STATE.tstore)
            if removed:
                try:
                    _STATE.tstore.save(_STATE.tstore.path)
                except Exception as ex:
                    return self._send(500, {"error": "save_failed",
                                            "message": "写盘失败：%s" % str(ex)[:180]})
            _sync_translate_metrics()
            st = _STATE.tstore.stats()
            return self._send(200, {"ok": True, "removed": removed,
                                    "total": len(_STATE.tstore.entries),
                                    "stats": {"total": st["total"],
                                              "translated": st["translated"],
                                              "untranslated": st["untranslated"]}})

        if path == "/api/nav":  # FR-36: 导航锁（只落已解锁区间）· FR-37: 位置持久化
            ok = _STATE.nav(int(b.get("step", 0)))
            if ok:
                _persist_flow()
            return self._send(200 if ok else 400, _STATE.to_dict())

        if path == "/api/reset":
            _STATE.reset()
            _persist_flow()   # FR-37: 重置后从第 0 步重新开始
            return self._send(200, _STATE.to_dict())

        return self._send(404, {"error": "not found"})


class _Srv(ThreadingHTTPServer):
    # Windows 上 SO_REUSEADDR 允许第二个实例静默同绑同一端口（请求流向不可控，
    # 表现为"时灵时不灵"的诡异 bug）——必须关掉，让双开走到 main.py 的复用/换端口逻辑。
    allow_reuse_address = False
    daemon_threads = True


def build_server(port: int = 8731) -> ThreadingHTTPServer:
    _restore_config()
    _restore_flow()   # FR-37: 下次打开回到上次所在步骤（首次启动落第 0 步）
    return _Srv(("127.0.0.1", port), _Handler)


if __name__ == "__main__":
    srv = build_server()
    srv.serve_forever()
