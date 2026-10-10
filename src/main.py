"""G-POT Loc —— C 路线入口（Python 内核 + WebView2 Fluent UI）。

用法：
  python main.py              # 启动 API 服务 + 打开 WebView2 窗口
  python main.py --no-gui     # 只跑 API 服务（无界面 / 测试用）
  python main.py --open-browser  # 用系统浏览器代替 WebView2（调试）
  python main.py --port N     # 指定端口（默认 8731）

无黑窗模式：bat 用 pythonw.exe 启动本文件，此时 sys.stdout/stderr 为 None，
所有 print 重定向到 %TEMP%\\gpot-run.log（stdout 防护必须放在最前面）。
"""
from __future__ import annotations

import os
import sys

# --- pythonw 防护（必须先于任何 print）：无控制台时输出落日志文件 ---
if sys.stdout is None or sys.stderr is None:
    try:
        _log = open(os.path.join(os.environ.get("TEMP", os.getcwd()),
                                 "gpot-run.log"), "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or _log
        sys.stderr = sys.stderr or _log
    except Exception:
        pass

import argparse
import threading
import time
import urllib.request

from gpot.api.server import build_server


def _gpot_alive(port: int) -> bool:
    """该端口上是否已有一个 G-POT 实例在跑（防双开：复用而不是崩掉）。"""
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/state", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def main() -> None:
    ap = argparse.ArgumentParser(description="G-POT Loc (C-route prototype)")
    ap.add_argument("--no-gui", action="store_true", help="只启动 API 服务")
    ap.add_argument("--open-browser", action="store_true",
                    help="用系统浏览器代替 WebView2（调试）")
    ap.add_argument("--port", type=int, default=8731)
    args = ap.parse_args()

    # 端口占用三态：自己绑上 / 已有 G-POT 实例（复用，不重复起服务）/ 换端口
    httpd = None
    port = args.port
    reuse = False
    for _ in range(10):
        try:
            httpd = build_server(port)
            break
        except OSError:
            if _gpot_alive(port):
                reuse = True
                break
            port += 1
    if httpd is None and not reuse:
        print(f"[G-POT] 端口 {args.port}~{port} 都被非 G-POT 程序占用，无法启动。")
        time.sleep(4)
        return

    url = f"http://127.0.0.1:{port}/"
    if reuse:
        print(f"[G-POT] 检测到已有实例在 {url}，直接复用它打开窗口。")
    else:
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        print(f"[G-POT] API 监听于 {url}")

    if args.no_gui or args.open_browser:
        if args.open_browser:
            import webbrowser
            webbrowser.open(url)
        print("[G-POT] 无窗口模式：Ctrl+C 退出")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            if httpd:
                httpd.shutdown()
        return

    from gpot.ui.host import open_window
    try:
        open_window(url)
    except Exception as exc:  # WebView2 运行时缺失 / pywebview 未装等
        import webbrowser
        print(f"[G-POT] WebView2 窗口启动失败：{exc}")
        print("[G-POT] 已自动改用系统浏览器打开界面（功能完全一致）。")
        webbrowser.open(url)
        print("[G-POT] 无窗口模式：关闭浏览器后按 Ctrl+C 停止服务。")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            if httpd:
                httpd.shutdown()


if __name__ == "__main__":
    main()
