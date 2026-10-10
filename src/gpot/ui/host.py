"""WebView2 宿主 —— 用 pywebview 开一个指向本地 API 的 Edge WebView2 窗口。

解耦要点：本模块只认「窗口」这一个概念，永远不 import core 或 api 的逻辑，
窗口里加载的就是本地 API 的首页 URL。pywebview 懒加载，因此 --no-gui
模式下本文件即使被 import 也不会触发任何 GUI 依赖。

v0.4：无边框窗口（frameless）——原生标题栏移除，最小化/最大化/关闭整合到
页面顶栏（前端经 js_api 调 WinCtl）；窗口拖动由顶栏 .pywebview-drag-region
区域承担（见 index.html / customize.js 的祖先链匹配逻辑）。
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


class WinCtl:
    """窗口控制桥：前端顶栏按钮 → 原生窗口动作（js_api 暴露给页面）。

    js_api 在 create_window 时传入，而 window 对象要 create 之后才有——
    所以先建桥再回填 _w。方法名即前端调用的 API 名（pywebview 公开非下划线方法）。
    """

    def __init__(self) -> None:
        self._w = None  # pywebview Window，create_window 后回填

    def _bind(self, w) -> None:
        self._w = w

    def minimize(self) -> None:
        if self._w is not None:
            self._w.minimize()

    def toggle_max(self) -> None:
        w = self._w
        if w is None:
            return
        # maximized 属性旧版 pywebview 可能没有——取不到就按「未最大化」处理
        if getattr(w, "maximized", False):
            w.restore()
        else:
            w.maximize()

    def close(self) -> None:
        if self._w is not None:
            self._w.destroy()


def open_window(url: str, title: str = "G-POT 翻译器") -> None:
    import webview  # 懒加载：仅真正开窗口时才需要
    icon = _icon_path()
    ctl = WinCtl()
    win = webview.create_window(title, url, width=1180, height=760,
                                min_size=(900, 600),
                                frameless=True,   # v0.4：去原生标题栏
                                easy_drag=False,  # 拖动交给顶栏 drag-region
                                js_api=ctl)
    ctl._bind(win)
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
