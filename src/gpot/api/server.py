"""HTTP API 服务 —— 把内核暴露成本地 REST 接口。

前端（WebView2 里的纯静态页面）只对这里发请求；本模块是 UI ↔ 内核的
唯一耦合点。换 UI 技术栈（WebView2 / 真 WinUI3 壳 / tkinter）都不用动内核。
"""
from __future__ import annotations

import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from gpot.core import (store as _store, detection, providers,
                       extract, translate, sink, pipeline)

# 应用级唯一状态实例
_STATE = _store.Store()

# 资源目录：src/gpot/ui/assets
_ASSETS = Path(__file__).resolve().parents[1] / "ui" / "assets"


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def _kit_tools(engine: dict | None, deployed: bool = False) -> list:
    if not engine or engine.get("key") != "unity":
        # 原型只给出 Unity 三件套；其它引擎在 M2 由 kit_catalog 提供
        return []
    status = "已就位" if deployed else "待部署"
    return [
        {"name": "BepInEx 5", "version": "5.4.23.5", "size": "2.7 MB",
         "verified": True, "status": status},
        {"name": "XUnity.AutoTranslator", "version": "5.6.2", "size": "1.8 MB",
         "verified": True, "status": status},
        {"name": "ResourceRedirector", "version": "2.1.0", "size": "0.4 MB",
         "verified": True, "status": status},
    ]


def _name_from_path(p: str) -> str:
    p = (p or "").rstrip("/\\")
    return p.split("/")[-1].split("\\")[-1] or "未命名游戏"


# ---------------------------------------------------------------------------
# 请求处理器
# ---------------------------------------------------------------------------
class _Handler(BaseHTTPRequestHandler):
    server_version = "G-POT-API/0.1"

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
            return self._send(200, _STATE.to_dict())
        if path == "/api/providers":  # FR-38: 列出翻译后端（第 0 步配置）
            return self._send(200, {"providers": providers.list_providers()})
        if path.startswith("/api/sink"):
            q = parse_qs(p.query)
            ek = (q.get("engine", [None])[0]
                  or (_STATE.engine or {}).get("key")
                  or "unity")
            return self._send(200, sink.sink_view(ek))
        if path.startswith("/api/verify"):  # FR-45: 启动验证（第 6 步·应用结果闭环）
            return self._send(200, sink.verify(_STATE))
        if path.startswith("/api/jobs/"):
            jid = path.rsplit("/", 1)[-1]
            j = translate.get_job(_STATE, jid)
            return self._send(200 if j else 404, j or {"error": "no such job"})
        # 兜底：其余 GET 路径尝试作为 assets 静态文件伺服（兼容相对路径引用，
        # 使 index.html 在 file:// 下双击也能完整加载 CSS/JS）。找不到仍 404。
        return self._static(path.lstrip("/"), self._ctype(path))

    # -------------------- POST --------------------
    def do_POST(self):
        p = urlparse(self.path)
        path = p.path
        b = self._json_body()

        if path == "/api/config":  # FR-38: 配置翻译服务 + 连通测试（第 0 步）
            for k in ("provider", "model", "address"):
                if k in b:
                    _STATE.config[k] = b[k]
            r = providers.test_connection(_STATE.config)
            _STATE.config["connected"] = r["connected"]
            if r["connected"]:
                pipeline.complete_step(_STATE, 0)
            return self._send(200, {"config": _STATE.config, **r})

        if path == "/api/game":  # FR-39: 选择游戏目录（第 1 步）
            gp = b.get("path", "")
            _STATE.game = {"path": gp, "name": b.get("name") or _name_from_path(gp),
                          "existing": 14679}
            pipeline.complete_step(_STATE, 1)
            return self._send(200, _STATE.game)

        if path == "/api/detect":  # FR-40: 识别引擎（第 2 步）
            eng = detection.detect_engine(_STATE.game.get("path", ""))
            _STATE.engine = eng
            _STATE.kit = {"deployed": False, "tools": _kit_tools(eng)}
            pipeline.complete_step(_STATE, 2)
            return self._send(200, eng)

        if path == "/api/deploy":  # FR-41: 部署注入工具（第 2 步·前移）
            _STATE.kit = {"deployed": True, "tools": _kit_tools(_STATE.engine, deployed=True)}
            return self._send(200, _STATE.kit)

        if path == "/api/extract":  # FR-42: 提取待翻译文本与护栏（第 3 步）
            return self._send(200, extract.extract(_STATE, b))

        if path == "/api/translate/start":  # FR-43: 启动翻译任务（第 4 步）
            jid = translate.start_translate(_STATE, bool(b.get("retry")))
            return self._send(200, {"job_id": jid})

        if path.startswith("/api/jobs/") and path.endswith("/cancel"):
            jid = path.rsplit("/", 2)[-2]
            return self._send(200, {"ok": translate.cancel_job(_STATE, jid)})

        if path == "/api/sink/apply":  # FR-44（按引擎变脸·落盘）& FR-48（引擎锁死校验）
            ek = b.get("engine") or (_STATE.engine or {}).get("key") or "unity"
            detected = (_STATE.engine or {}).get("key") or "unity"
            if ek != detected:
                return self._send(400, {"error": "engine_mismatch",
                                        "message": f"当前游戏管线为 {detected}，不能按 {ek} 管线写入"})
            return self._send(200, sink.apply(_STATE, ek))

        if path == "/api/nav":  # FR-36: 导航锁（只落已解锁区间）
            ok = _STATE.nav(int(b.get("step", 0)))
            return self._send(200 if ok else 400, _STATE.to_dict())

        if path == "/api/reset":
            _STATE.reset()
            return self._send(200, _STATE.to_dict())

        return self._send(404, {"error": "not found"})


def build_server(port: int = 8731) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), _Handler)


if __name__ == "__main__":
    srv = build_server()
    srv.serve_forever()
