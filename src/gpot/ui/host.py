"""WebView2 宿主 —— 用 pywebview 开一个指向本地 API 的 Edge WebView2 窗口。

解耦要点：本模块只认「窗口」这一个概念，永远不 import core 或 api 的逻辑，
窗口里加载的就是本地 API 的首页 URL。pywebview 懒加载，因此 --no-gui
模式下本文件即使被 import 也不会触发任何 GUI 依赖。
"""
from __future__ import annotations


def open_window(url: str, title: str = "G-POT 翻译器") -> None:
    import webview  # 懒加载：仅真正开窗口时才需要
    webview.create_window(title, url, width=1180, height=760,
                          min_size=(900, 600))
    # 优先显式 Edge/WebView2 后端；若该后端初始化失败，退一步用默认后端再试一次，
    # 仍失败则抛出异常，由 main() 改用系统浏览器兜底。
    try:
        webview.start(gui="edgechromium")
    except Exception:
        webview.start()
