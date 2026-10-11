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


def _native_hwnd(win) -> int:
    """从 pywebview Window 摸出原生 HWND（pywebview 各版本暴露方式不一）。

    实测（本机 pywebview 6.2.1 + edgechromium）：`win.native` 是 winforms 的
    `BrowserForm`，**没有** `GetHandle()`（那是 edgechromium 老版本的写法），
    HWND 在 `.Handle` 属性上。旧库 v3.28 与其它后端又可能是别的形态，
    所以这里逐个试，拿不到就返回 0（调用方负责静默降级 + 写日志）。
    """
    native = getattr(win, "native", None)
    if native is None:
        return 0
    for attr in ("Handle", "handle"):
        v = getattr(native, attr, None)
        if v is not None:
            got = _as_hwnd(v)
            if got:
                return got
    for meth in ("GetHandle", "get_handle"):
        fn = getattr(native, meth, None)
        if callable(fn):
            try:
                got = _as_hwnd(fn())
                if got:
                    return got
            except Exception:
                pass
    return 0


def _as_hwnd(v) -> int:
    """把各种 HWND 形态转成 int。

    实测坑：pywebview 6.2.1 + winforms 后端下 `Form.Handle` 是
    **`System.IntPtr` 包装对象**（不是整数、也不是 `ctypes.c_void_p`），
    直接 `int(v)` 抛异常 → 于是早期版本恒返回 0、边缘缩放静默装不上。
    这里依次试 `.ToInt64()` / `.value` / `int()`。
    """
    if isinstance(v, int):
        return v
    for meth in ("ToInt64", "to_int64"):
        fn = getattr(v, meth, None)
        if callable(fn):
            try:
                return int(fn())
            except Exception:
                pass
    inner = getattr(v, "value", None)
    if isinstance(inner, int):
        return inner
    try:
        return int(v)
    except Exception:
        return 0


def _install_edge_resize(win) -> bool:
    """给无边框窗口装上边缘拖拽缩放（FR-81）。

    pywebview 的 frameless 窗口没有系统边框，也就没法拖边缘改大小。本函数把
    窗口过程子类化，拦 `WM_NCHITTEST`：鼠标落在窗口四边/四角时回
    `HTLEFT/HTRIGHT/...`，Windows 就会自己画出缩放光标并接管拖拽 —— 这是
    原生做法，比在前端模拟 mousemove 稳得多（拖出窗口外也不丢事件）。

    判定「点在哪个区」是纯逻辑，已下沉 `core.winframe.hit_test`（可单测）；
    这里只负责把判定结果翻译成 Win32 消息约定（分层铁律④）。

    任何一步失败（取不到 HWND / API 不存在 / 非 Windows）都返回 False，
    窗口照常能用，只是没有边缘缩放 —— 绝不能让「加个缩放」把窗口搞挂。
    """
    if os.name != "nt":
        return False
    try:
        import ctypes
        import traceback
        from ctypes import wintypes

        from ..core import winframe

        GWLP_WNDPROC = -4
        WM_NCHITTEST = 0x0084

        user32 = ctypes.windll.user32
        # ⚠️ 必须显式声明 argtypes/restype。ctypes 默认把 HWND/WPARAM/LPARAM 当
        # 32 位 int 传，64 位下指针被截断 → CallWindowProcW 写越界 → 进程直接
        # 崩（access violation）。这是 Win32 子类化最常见的坑。
        LONG_PTR = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long
        set_proc_type = ctypes.WINFUNCTYPE(LONG_PTR, wintypes.HWND, wintypes.UINT,
                                           wintypes.WPARAM, wintypes.LPARAM)
        user32.GetWindowRect.argtypes = [wintypes.HWND,
                                         ctypes.POINTER(wintypes.RECT)]
        user32.GetWindowRect.restype = wintypes.BOOL
        user32.CallWindowProcW.argtypes = [LONG_PTR, wintypes.HWND, wintypes.UINT,
                                           wintypes.WPARAM, wintypes.LPARAM]
        user32.CallWindowProcW.restype = LONG_PTR
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int,
                                             set_proc_type]
        user32.SetWindowLongPtrW.restype = LONG_PTR

        hwnd = _native_hwnd(win)
        if not hwnd:
            _log_resize("拿不到 HWND（native 暴露形式不匹配）")
            return False

        set_proc = set_proc_type
        # ⚠️ 用可变单元素列表而不是 dict/闭包变量：子类化一旦生效，Windows 可能在
        # SetWindowLongPtrW 返回**之前**就发一次 WM_NCHITTEST，那时 old 还没写进去
        # → 回调里 KeyError / NameError，整窗消息链断掉。
        old_box = [0]

        def _proc(hwnd_, msg, wparam, lparam):
            if msg == WM_NCHITTEST:
                r = wintypes.RECT()
                user32.GetWindowRect(hwnd_, ctypes.byref(r))
                code = winframe.hit_test(
                    ctypes.c_short(lparam & 0xFFFF).value,
                    ctypes.c_short((lparam >> 16) & 0xFFFF).value,
                    r.right - r.left, r.bottom - r.top)
                if code != winframe.HTCLIENT:
                    return code
            old = old_box[0]
            if not old:
                return user32.DefWindowProcW(hwnd_, msg, wparam, lparam)
            return user32.CallWindowProcW(old, hwnd_, msg, wparam, lparam)

        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                          wintypes.WPARAM, wintypes.LPARAM]
        user32.DefWindowProcW.restype = LONG_PTR

        cb = set_proc(_proc)
        if hasattr(user32, "SetWindowLongPtrW"):
            old = user32.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, cb)
        else:
            old = user32.SetWindowLongW(hwnd, GWLP_WNDPROC, cb)
        old_box[0] = old
        if not old:
            _log_resize("SetWindowLongPtrW 返回 0（子类化失败）")
            return False
        # keepref：委托被 GC 回收后进程直接崩（访问已释放的代码页）
        globals()["_GPOT_WNDPROC_KEEPALIVE"] = (cb, _proc, old_box)
        return True
    except Exception:
        _log_resize("子类化异常：\n" + traceback.format_exc())
        return False


def _schedule_edge_resize(win) -> None:
    """后台线程里等窗口建出来，再装边缘缩放（FR-81）。

    实测（pywebview 6.2.1 + edgechromium）：`win.native` 要等窗口真正创建后
    才回填，早一步取就是 None —— 所以轮询等，不是死等一次。
    任何异常都不外泄：装不上就静默降级（窗口照常能用，只是不能拖边缘）。
    """
    def _late_resize():
        import time
        for _ in range(60):          # 最多等 ~6s
            time.sleep(0.1)
            try:
                if _install_edge_resize(win):
                    return
            except Exception:
                return
    try:
        import threading
        threading.Thread(target=_late_resize, daemon=True).start()
    except Exception as e:
        _log_resize("起线程失败：%s" % e)


def _log_resize(msg: str) -> None:
    """边缘缩放安装诊断 —— 失败是静默降级，必须留痕（诚实性 NFR-9）。"""
    try:
        path = os.path.join(os.environ.get("TEMP", os.getcwd()), "gpot-run.log")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("[edge-resize] %s\n" % msg)
    except Exception:
        pass


def open_window(url: str, title: str = "G-POT 翻译器") -> None:
    import webview  # 懒加载：仅真正开窗口时才需要
    icon = _icon_path()
    ctl = WinCtl()
    win = webview.create_window(title, url, width=1180, height=760,
                                min_size=(900, 600),
                                frameless=True,   # FR-50: 去原生标题栏（min/max/close 整合顶栏 WinCtl）
                                easy_drag=False,  # 拖动交给顶栏 drag-region
                                js_api=ctl)
    ctl._bind(win)
    # FR-81：窗口起来后再装边缘缩放（要 native HWND，只能事后子类化）
    _schedule_edge_resize(win)
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
