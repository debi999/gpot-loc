"""G-POT Loc —— C 路线入口（Python 内核 + WebView2 Fluent UI）。

用法：
  python main.py              # 启动 API 服务 + 打开 WebView2 窗口
  python main.py --no-gui     # 只跑 API 服务（无界面 / 测试用）
  python main.py --open-browser  # 用系统浏览器代替 WebView2（调试）
  python main.py --port N     # 指定端口（默认 8731）

无黑窗模式：v0.4.1 起不依赖 pythonw——本机 hermes venv 的 pythonw.exe 实为
控制台子系统 shim（PE subsystem=3，会派生 python.exe 子进程），bat 走 pythonw
分支仍会带出黑窗；且 Windows Terminal 作为默认终端时 FreeConsole 关不掉已
显示的控制台。故 GUI 模式检测到自带控制台时，立即用 CREATE_NO_WINDOW 重启
自身（子进程完全没有控制台），父进程退出，黑窗随之关闭。输出落
%TEMP%\\gpot-run.log。
"""
from __future__ import annotations

import os
import sys
import time

# --- pythonw 防护（必须先于任何 print）：无控制台时输出落日志文件 ---
if sys.stdout is None or sys.stderr is None:
    try:
        _log = open(os.path.join(os.environ.get("TEMP", os.getcwd()),
                                 "gpot-run.log"), "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or _log
        sys.stderr = sys.stderr or _log
    except Exception:
        pass

# --- 黑窗根治（v0.4.1）：GUI 模式若自带控制台，导入重模块前先无窗重启自己 ---
# --no-gui / --open-browser（调试形态）保留控制台，绝不重启。
if os.environ.get("GPOT_NOWIN") != "1" and sys.argv and \
        not any(a in sys.argv for a in ("--no-gui", "--open-browser", "-h", "--help")):
    try:
        import ctypes
        _k32 = ctypes.windll.kernel32
        _hwnd = _k32.GetConsoleWindow()
        if _hwnd:
            import subprocess
            _script = os.path.abspath(sys.argv[0] or __file__)
            _logf = open(os.path.join(os.environ.get("TEMP", os.getcwd()),
                                      "gpot-run.log"), "a", encoding="utf-8")
            _logf.write("[%s] === G-POT run (re-exec no-console) ===\n"
                        % time.strftime("%Y-%m-%d %H:%M:%S"))
            _logf.flush()
            _env = dict(os.environ)
            _env["GPOT_NOWIN"] = "1"
            # 子进程 stdout 是文件句柄时，Python 按区域编码重包 → 必须钉死 UTF-8
            _env["PYTHONIOENCODING"] = "utf-8:replace"
            _env["PYTHONUTF8"] = "1"
            try:
                ctypes.windll.user32.ShowWindow(_hwnd, 0)  # SW_HIDE，尽早压住黑窗
            except Exception:
                pass
            subprocess.Popen(
                [sys.executable, _script] + sys.argv[1:],
                creationflags=0x08000000,  # CREATE_NO_WINDOW：子进程完全没有控制台
                env=_env, cwd=os.path.dirname(_script) or None,
                stdin=subprocess.DEVNULL, stdout=_logf, stderr=_logf)
            sys.exit(0)
    except SystemExit:
        raise
    except Exception:
        pass  # 重启失败则按老流程继续跑（最坏情况=多一个黑窗，功能不受影响）

import argparse
import threading
import urllib.request

from gpot.api.server import build_server, APP_VERSION


def _gpot_alive(port: int) -> str | None:
    """该端口上是否已有一个 G-POT 实例在跑；返回其版本号（防双开：复用而不是崩掉）。

    返回 None = 端口活着但不是 G-POT（被别的程序占用）；返回版本字符串 = 是 G-POT。
    """
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/state", timeout=2) as r:
            if r.status != 200:
                return None
            import json
            return json.loads(r.read().decode("utf-8", "replace")).get("app_version")
    except Exception:
        return None


def _detach_console() -> None:
    """GUI 模式下隐藏后端黑窗（v0.4 老板实测反馈；v0.4.1 兜底保留）。

    正常路径下无窗重启（模块顶部 CREATE_NO_WINDOW）已经生效，这里只剩
    兜底作用：万一某台机器真的用带控制台的解释器跑到了这一步，先把输出
    重定向到日志、再隐藏+释放控制台。注意 Windows Terminal 作为默认终端时
    FreeConsole 不保证立刻关掉已显示的窗口，所以先 ShowWindow(SW_HIDE)。
    --no-gui（调试模式）绝不调用，保留控制台看日志。
    """
    try:
        log = open(os.path.join(os.environ.get("TEMP", os.getcwd()),
                                "gpot-run.log"), "a", encoding="utf-8", buffering=1)
        log.write("[%s] === G-POT run ===\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
        sys.stdout = sys.stderr = log
    except Exception:
        pass
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        u32 = ctypes.windll.user32
        hwnd = k32.GetConsoleWindow()
        if hwnd:
            u32.ShowWindow(hwnd, 0)  # SW_HIDE
        k32.FreeConsole()
    except Exception:
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description="G-POT Loc (C-route prototype)")
    ap.add_argument("--no-gui", action="store_true", help="只启动 API 服务")
    ap.add_argument("--open-browser", action="store_true",
                    help="用系统浏览器代替 WebView2（调试）")
    ap.add_argument("--port", type=int, default=8731)
    args = ap.parse_args()

    # 端口占用三态：自己绑上 / 已有「同版本」G-POT 实例（复用）/ 换端口。
    # 版本校验：旧版本实例不复用——否则改完代码双击 bat 打开的还是旧界面。
    httpd = None
    port = args.port
    reuse = False
    for _ in range(10):
        try:
            httpd = build_server(port)
            break
        except OSError:
            ver = _gpot_alive(port)
            if ver == APP_VERSION:
                reuse = True
                break
            if ver is not None:  # 是 G-POT 但版本不同 → 旧实例，另起端口
                print(f"[G-POT] 端口 {port} 上是旧版本实例（{ver} ≠ {APP_VERSION}），"
                      f"换用端口 {port + 1} 启动新版本。旧实例可关闭以释放端口。")
                port += 1
                continue
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

    # GUI / 浏览器模式都属「无控制台交付形态」：隐藏黑窗（--no-gui 调试除外）
    if not args.no_gui:
        _detach_console()

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
