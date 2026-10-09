"""G-POT Loc —— C 路线入口（Python 内核 + WebView2 Fluent UI）。

用法：
  python main.py              # 启动 API 服务 + 打开 WebView2 窗口
  python main.py --no-gui     # 只跑 API 服务（无界面 / 测试用）
  python main.py --open-browser  # 用系统浏览器代替 WebView2（调试）
  python main.py --port N     # 指定端口（默认 8731）
"""
from __future__ import annotations

import argparse
import threading
import time

from gpot.api.server import build_server


def main() -> None:
    ap = argparse.ArgumentParser(description="G-POT Loc (C-route prototype)")
    ap.add_argument("--no-gui", action="store_true", help="只启动 API 服务")
    ap.add_argument("--open-browser", action="store_true",
                    help="用系统浏览器代替 WebView2（调试）")
    ap.add_argument("--port", type=int, default=8731)
    args = ap.parse_args()

    httpd = build_server(args.port)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{args.port}/"
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
            httpd.shutdown()


if __name__ == "__main__":
    main()
