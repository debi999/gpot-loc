"""FR-81 边缘缩放判定单测 —— core.winframe 纯逻辑，不碰 Win32。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gpot.core import winframe as W  # noqa: E402


def test_corner_wins_over_edge():
    """角区同时命中两边时必须先判角（否则角上显示单向光标）。"""
    w, h = 1000, 800
    assert W.hit_test(0, 0, w, h) == W.HTTOPLEFT
    assert W.hit_test(999, 0, w, h) == W.HTTOPRIGHT
    assert W.hit_test(0, 799, w, h) == W.HTBOTTOMLEFT
    assert W.hit_test(999, 799, w, h) == W.HTBOTTOMRIGHT


def test_four_edges():
    w, h = 1000, 800
    assert W.hit_test(500, 0, w, h) == W.HTTOP
    assert W.hit_test(500, 799, w, h) == W.HTBOTTOM
    assert W.hit_test(0, 400, w, h) == W.HTLEFT
    assert W.hit_test(999, 400, w, h) == W.HTRIGHT


def test_center_is_client():
    assert W.hit_test(500, 400, 1000, 800) == W.HTCLIENT


def test_border_width_respected():
    """带宽可配：border=20 时 y=10 才算顶边；border=6 时 y=10 已是客户区。"""
    assert W.hit_test(500, 10, 1000, 800, border=20) == W.HTTOP
    assert W.hit_test(500, 10, 1000, 800, border=6) == W.HTCLIENT
    assert W.hit_test(500, 2, 1000, 800, border=20) == W.HTTOP


def test_caption_band():
    """顶部拖拽带：caption_top 内整体 HTCAPTION，且不与上下边冲突。"""
    # y=5 既在顶边内也在 caption 内 —— 边优先（否则顶边没法缩放）
    assert W.hit_test(500, 5, 1000, 800, border=6, caption_top=30) == W.HTTOP
    # y=15 在 caption 内但不在 border 内
    assert W.hit_test(500, 15, 1000, 800, border=6, caption_top=30) == W.HTCAPTION
    # y=40 超出 caption
    assert W.hit_test(500, 40, 1000, 800, border=6, caption_top=30) == W.HTCLIENT


def test_degenerate_size_is_client():
    """窗口尺寸为 0 时不能判成缩放区（否则会出现「整屏都是边」）。"""
    assert W.hit_test(0, 0, 0, 0) == W.HTCLIENT
    assert W.hit_test(-1, -1, -5, -5) == W.HTCLIENT


def test_cursor_mapping_covers_all_resize_codes():
    for code in (W.HTLEFT, W.HTRIGHT, W.HTTOP, W.HTBOTTOM, W.HTTOPLEFT,
                 W.HTTOPRIGHT, W.HTBOTTOMLEFT, W.HTBOTTOMRIGHT):
        assert W.cursor_for(code) != "default"
    assert W.cursor_for(W.HTCLIENT) == "default"
    assert W.cursor_for(W.HTCAPTION) == "move"


def test_host_imports_edge_resize_hook():
    """ui/host.py 必须真的接线（不然这个模块就是死代码，违反铁律③）。"""
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            'gpot', 'ui', 'host.py'), encoding='utf-8').read()
    assert '_install_edge_resize' in src and 'WM_NCHITTEST' in src


def test_host_native_hwnd_handles_intptr_wrapper():
    """FR-81 实测坑：pywebview 6.2.1 的 Form.Handle 是 System.IntPtr 包装对象，
    直接 int() 抛异常 → 早期版本恒拿不到 HWND、边缘缩放静默装不上。"""
    from gpot.ui import host

    class FakeIntPtr:
        """模拟 .NET System.IntPtr：有 ToInt64()，但 int() 会失败。"""

        def __init__(self, v):
            self._v = v

        def ToInt64(self):
            return self._v

        def __int__(self):
            raise TypeError('not a plain int')

    assert host._as_hwnd(FakeIntPtr(12345)) == 12345
    assert host._as_hwnd(0x7fff) == 0x7fff
    assert host._as_hwnd(None) == 0
    assert host._as_hwnd('nope') == 0


def test_host_native_hwnd_falls_back_across_shapes():
    """不同 pywebview 后端/版本的 native 形态不一，兜底链要都走到。"""
    from gpot.ui import host

    class WithHandle:
        Handle = 999

    class WithGetHandle:
        def GetHandle(self):
            return 777

    class Empty:
        pass

    class W:
        def __init__(self, native):
            self.native = native

    assert host._native_hwnd(W(WithHandle())) == 999
    assert host._native_hwnd(W(WithGetHandle())) == 777
    assert host._native_hwnd(W(Empty())) == 0
    assert host._native_hwnd(object()) == 0


def test_host_declares_win32_signatures():
    """64 位下 ctypes 不声明 argtypes/restype 会写越界崩进程 —— 必须有。"""
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            'gpot', 'ui', 'host.py'), encoding='utf-8').read()
    for needed in ('CallWindowProcW.argtypes', 'SetWindowLongPtrW.argtypes',
                   'GetWindowRect.argtypes', 'restype'):
        assert needed in src, needed