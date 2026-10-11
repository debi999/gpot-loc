"""无边框窗口的边缘命中判定（FR-81）——**纯逻辑，零 Win32 依赖**。

为什么要下沉到 core：Win32 子类化那部分只能在 Windows 宿主里跑、无法单测；
但「鼠标在窗口哪个位置该显示哪种缩放光标」是纯函数，判定逻辑放这里，
`ui/host.py` 只负责把结果翻译成 `WM_NCHITTEST` 返回码（api/ui 层不做业务判定，
符合 AGENTS.md 第 4 条分层铁律）。

坐标系一律是**客户区**坐标（0..width-1 / 0..height-1），与 Win32
`GET_X_LPARAM/GET_Y_LPARAM` 一致。
"""
from __future__ import annotations

# Win32 WM_NCHITTEST 返回码（只列本项目会用到的）
HTCLIENT = 1
HTCAPTION = 2
HTLEFT = 10
HTRIGHT = 11
HTTOP = 12
HTTOPLEFT = 13
HTTOPRIGHT = 14
HTBOTTOM = 15
HTBOTTOMLEFT = 16
HTBOTTOMRIGHT = 17

DEFAULT_BORDER = 6      # 边缘命中带宽（px），与 Win32 SM_CXFRAME 量级一致
DEFAULT_CAPTION_TOP = 0 # 标题栏拖拽带高度（0 = 不启用顶部拖拽区）


def hit_test(x: int, y: int, width: int, height: int,
             border: int = DEFAULT_BORDER,
             caption_top: int = DEFAULT_CAPTION_TOP) -> int:
    """返回该点应回的 `WM_NCHITTEST` 码。

    - 四边 + 四角共 8 个缩放区，边角优先于单边（角区同时命中两边时先判角）。
    - `caption_top > 0` 时顶部若干像素整体当拖拽区（无边框窗口没有系统标题栏，
      想拖窗口必须自己给一条命中带，否则用户无处拖动）。
    - 其余一律 `HTCLIENT`。
    """
    if width <= 0 or height <= 0:
        return HTCLIENT
    b = max(1, int(border))
    left, right = x < b, x >= width - b
    top, bottom = y < b, y >= height - b

    if top and left:
        return HTTOPLEFT
    if top and right:
        return HTTOPRIGHT
    if bottom and left:
        return HTBOTTOMLEFT
    if bottom and right:
        return HTBOTTOMRIGHT
    if top:
        return HTTOP
    if bottom:
        return HTBOTTOM
    if left:
        return HTLEFT
    if right:
        return HTRIGHT
    if caption_top > 0 and y < caption_top:
        return HTCAPTION
    return HTCLIENT


def cursor_for(code: int) -> str:
    """命中码 → 光标形态（给前端设置 `body.style.cursor` 用；浏览器模式降级）。"""
    return {
        HTLEFT: "w-resize", HTRIGHT: "e-resize",
        HTTOP: "n-resize", HTBOTTOM: "s-resize",
        HTTOPLEFT: "nw-resize", HTTOPRIGHT: "ne-resize",
        HTBOTTOMLEFT: "sw-resize", HTBOTTOMRIGHT: "se-resize",
        HTCAPTION: "move",
    }.get(code, "default")