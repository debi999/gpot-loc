"""WebView2 宿主 —— 用 pywebview 开一个指向本地 API 的 Edge WebView2 窗口。

解耦要点：本模块只认「窗口」这一个概念，永远不 import core 或 api 的逻辑，
窗口里加载的就是本地 API 的首页 URL。pywebview 懒加载，因此 --no-gui
模式下本文件即使被 import 也不会触发任何 GUI 依赖。
"""
from __future__ import annotations

import os


def _icon_path() -> str | None:
    """定位随包分发的窗口图标 assets/icon.ico。

    注意 PYZ 打包环境下 ``__file__`` 可能不存在（旧库 v3.28 的教训），
    因此全程 try/except：取不到就返回 None，让 pywebview 走默认图标，
    绝不能让「找图标」把窗口启动搞挂。
    """
    try:
        here = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        return None
    cand = os.path.join(here, "assets", "icon.ico")
    return cand if os.path.isfile(cand) else None


def open_window(url: str, title: str = "G-POT 翻译器") -> None:
    import webview  # 懒加载：仅真正开窗口时才需要
    icon = _icon_path()
    webview.create_window(title, url, width=1180, height=760,
                          min_size=(900, 600))
    # 优先显式 Edge/WebView2 后端；若该后端初始化失败，退一步用默认后端再试一次，
    # 仍失败则抛出异常，由 main() 改用系统浏览器兜底。
    # 窗口图标：winforms 后端读取 start(icon=...)（winforms.py 里 self.Icon = Icon(icon)）；
    # 旧版 pywebview 不认识 icon 参数会抛 TypeError，此时退回「无图标但仍是 edgechromium」。
    try:
        try:
            webview.start(gui="edgechromium", icon=icon)
        except TypeError:
            webview.start(gui="edgechromium")
    except Exception:
        webview.start()
