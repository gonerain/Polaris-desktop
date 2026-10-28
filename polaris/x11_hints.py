"""让 X11 悬浮窗口跳过任务栏、分页器和 Alt+Tab 切换器。"""

from __future__ import annotations

import ctypes
import ctypes.util
from functools import lru_cache

from PySide6.QtGui import QGuiApplication

_CLIENT_MESSAGE = 33
_SUBSTRUCTURE_NOTIFY = 1 << 19
_SUBSTRUCTURE_REDIRECT = 1 << 20
_NET_WM_STATE_ADD = 1
_EVENT_MASK = _SUBSTRUCTURE_NOTIFY | _SUBSTRUCTURE_REDIRECT


class _ClientMessageData(ctypes.Union):
    _fields_ = [
        ("b", ctypes.c_char * 20),
        ("s", ctypes.c_short * 10),
        ("l", ctypes.c_long * 5),
    ]


class _ClientMessageEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("serial", ctypes.c_ulong),
        ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("window", ctypes.c_ulong),
        ("message_type", ctypes.c_ulong),
        ("format", ctypes.c_int),
        ("data", _ClientMessageData),
    ]


class _XEvent(ctypes.Union):
    _fields_ = [
        ("type", ctypes.c_int),
        ("xclient", _ClientMessageEvent),
        ("pad", ctypes.c_long * 24),
    ]


@lru_cache(maxsize=1)
def _load_x11():
    library = ctypes.util.find_library("X11")
    if not library:
        return None
    x11 = ctypes.CDLL(library)
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    x11.XInternAtom.restype = ctypes.c_ulong
    x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    x11.XDefaultRootWindow.restype = ctypes.c_ulong
    x11.XSendEvent.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_int,
        ctypes.c_long,
        ctypes.POINTER(_XEvent),
    ]
    x11.XSendEvent.restype = ctypes.c_int
    x11.XFlush.argtypes = [ctypes.c_void_p]
    return x11


def apply_skip_taskbar(window) -> bool:
    """给窗口添加 SKIP_TASKBAR / SKIP_PAGER；非 X11 或失败时返回 False。"""
    app = QGuiApplication.instance()
    if app is None or app.platformName() != "xcb":
        return False
    try:
        x11 = _load_x11()
    except (OSError, AttributeError):
        # Optional desktop hints must never prevent startup on a minimal Linux.
        return False
    if x11 is None:
        return False
    try:
        window_id = int(window.winId())
    except (AttributeError, RuntimeError, TypeError):
        return False
    if not window_id:
        return False

    display = x11.XOpenDisplay(None)
    if not display:
        return False
    try:
        state_atom = x11.XInternAtom(display, b"_NET_WM_STATE", 0)
        skip_taskbar = x11.XInternAtom(display, b"_NET_WM_STATE_SKIP_TASKBAR", 0)
        skip_pager = x11.XInternAtom(display, b"_NET_WM_STATE_SKIP_PAGER", 0)
        root = x11.XDefaultRootWindow(display)
        if not state_atom or not skip_taskbar or not skip_pager or not root:
            return False

        event = _XEvent()
        event.xclient.type = _CLIENT_MESSAGE
        event.xclient.send_event = 1
        event.xclient.display = display
        event.xclient.window = window_id
        event.xclient.message_type = state_atom
        event.xclient.format = 32
        event.xclient.data.l[0] = _NET_WM_STATE_ADD
        event.xclient.data.l[1] = skip_taskbar
        event.xclient.data.l[2] = skip_pager
        event.xclient.data.l[3] = 1  # 来源：普通应用
        sent = x11.XSendEvent(display, root, 0, _EVENT_MASK, ctypes.byref(event))
        x11.XFlush(display)
        return bool(sent)
    finally:
        x11.XCloseDisplay(display)
