"""所有 ctypes / Win32 调用都收在这里，别的地方不许直接碰 windll。

为什么要单独一层：Win32 的类型声明一旦漏了 argtypes，64 位下句柄会被截成 32 位，
表现为"窗口样式设不上""托盘图标冒出来又消失"这类很难查的怪毛病。
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"

user32 = ctypes.WinDLL("user32", use_last_error=True) if IS_WINDOWS else None
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True) if IS_WINDOWS else None
shell32 = ctypes.WinDLL("shell32", use_last_error=True) if IS_WINDOWS else None
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True) if IS_WINDOWS else None
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True) if IS_WINDOWS else None

# 窗口扩展样式
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
WS_EX_NOACTIVATE = 0x08000000

GWL_EXSTYLE = -20
GWL_STYLE = -16
GWLP_WNDPROC = -4

# 点击穿透必需的四位：分层 + 鼠标穿透 + 不进 Alt+Tab + 不抢焦点
CLICK_THROUGH_EXSTYLE = WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE

# SetWindowPos
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_SHOWWINDOW = 0x0040

# 分层窗口属性
LWA_COLORKEY = 0x00000001
LWA_ALPHA = 0x00000002

# DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2，句柄值就是 -4
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4

# 显示器枚举
MONITORINFOF_PRIMARY = 0x00000001

# 托盘
NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
NIF_SHOWTIP = 0x00000080
IDI_APPLICATION = 32512
IMAGE_ICON = 1
LR_DEFAULTSIZE = 0x00000040
LR_SHARED = 0x00008000

# 菜单
MF_STRING = 0x00000000
MF_SEPARATOR = 0x00000800
MF_CHECKED = 0x00000008
MF_UNCHECKED = 0x00000000
TPM_RIGHTBUTTON = 0x0002
TPM_RETURNCMD = 0x0100
TPM_NONOTIFY = 0x0080

# 消息
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_COMMAND = 0x0111
WM_CONTEXTMENU = 0x007B
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_APP = 0x8000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

# 快捷键修饰键
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

# window class 用的
CS_HREDRAW = 0x0002
CS_VREDRAW = 0x0001

WM_TRAYICON = WM_APP + 1  # 托盘回调消息号，与 §7 一致

# 注册表自启
HKEY_CURRENT_USER = 0x80000001
KEY_SET_VALUE = 0x0002
KEY_QUERY_VALUE = 0x0001
REG_SZ = 1
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "ScreenWatermark"


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    """字段顺序照 shellapi.h；szTip 是 128 wchar，整个结构体大小必须精确。"""

    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", wintypes.HICON),
    ]


# WNDCLASSW / WNDPROC 的类型别名，注册窗口类时用
WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)
MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL,
    wintypes.HMONITOR,
    wintypes.HDC,
    ctypes.POINTER(RECT),
    wintypes.LPARAM,
)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


if IS_WINDOWS:
    _LONG_PTR = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long
    # 64 位必须走 Ptr 版本；32 位系统上这些符号不存在，退回复合宏展开的旧名
    _get_long = getattr(user32, "GetWindowLongPtrW", None) or user32.GetWindowLongW
    _set_long = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW

    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = _LONG_PTR
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, _LONG_PTR]
    user32.SetWindowLongPtrW.restype = _LONG_PTR
    user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.COLORREF, ctypes.c_ubyte, wintypes.DWORD]
    user32.SetLayeredWindowAttributes.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.SetProcessDpiAwarenessContext.argtypes = [wintypes.HANDLE]
    user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ReleaseDC.restype = ctypes.c_int
    gdi32.GetDeviceCaps.argtypes = [wintypes.HDC, ctypes.c_int]
    gdi32.GetDeviceCaps.restype = ctypes.c_int
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
    shell32.Shell_NotifyIconW.restype = wintypes.BOOL

    advapi32.RegCreateKeyExW.argtypes = [
        wintypes.HKEY,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.HKEY),
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.RegCreateKeyExW.restype = wintypes.LONG
    advapi32.RegSetValueExW.argtypes = [
        wintypes.HKEY,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_char_p,
        wintypes.DWORD,
    ]
    advapi32.RegSetValueExW.restype = wintypes.LONG
    advapi32.RegDeleteValueW.argtypes = [wintypes.HKEY, wintypes.LPCWSTR]
    advapi32.RegDeleteValueW.restype = wintypes.LONG
    advapi32.RegOpenKeyExW.argtypes = [
        wintypes.HKEY,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HKEY),
    ]
    advapi32.RegOpenKeyExW.restype = wintypes.LONG
    advapi32.RegQueryValueExW.argtypes = [
        wintypes.HKEY,
        wintypes.LPCWSTR,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_char_p,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.RegQueryValueExW.restype = wintypes.LONG
    advapi32.RegCloseKey.argtypes = [wintypes.HKEY]
    advapi32.RegCloseKey.restype = wintypes.LONG


@dataclass(frozen=True)
class Monitor:
    """一块屏幕的物理像素矩形。"""

    left: int
    top: int
    right: int
    bottom: int
    primary: bool

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


def set_dpi_awareness() -> bool:
    """必须在任何 UI（包括 tkinter）创建之前调用，否则 Tk 拿到的是被系统缩放后的假坐标。"""
    if not IS_WINDOWS:
        return False
    try:
        # 先试 PMv2；老系统没有这个 API 就退到 shcore 的 PerMonitor，再不行就 system aware
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)):
            return True
    except (AttributeError, OSError):
        pass
    try:
        shcore = ctypes.WinDLL("shcore", use_last_error=True)
        # 2 = PROCESS_PER_MONITOR_DPI_AWARE
        if shcore.SetProcessDpiAwareness(2) == 0:
            return True
    except (AttributeError, OSError):
        pass
    try:
        return bool(user32.SetProcessDPIAware())
    except (AttributeError, OSError):
        return False


def enum_monitors() -> list[Monitor]:
    """EnumDisplayMonitors 给的是物理像素矩形，和 tkinter 在 PMv2 下的坐标系一致。"""
    if not IS_WINDOWS:
        return []
    found: list[Monitor] = []

    def _cb(hmon, hdc, lprect, lparam):  # noqa: ANN001 - ctypes 回调签名
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            rect = info.rcMonitor
        else:
            rect = lprect.contents
        found.append(
            Monitor(
                left=rect.left,
                top=rect.top,
                right=rect.right,
                bottom=rect.bottom,
                primary=bool(info.dwFlags & MONITORINFOF_PRIMARY),
            )
        )
        return True

    proc = MONITORENUMPROC(_cb)  # 必须留引用，回调对象被 GC 掉会直接崩
    try:
        user32.EnumDisplayMonitors(None, None, proc, 0)
    except OSError:
        pass
    if not found:
        # 兜底：至少给主屏，别让水印整个消失
        w = user32.GetSystemMetrics(0)
        h = user32.GetSystemMetrics(1)
        found.append(Monitor(0, 0, w, h, True))
    found.sort(key=lambda m: (not m.primary, m.left, m.top))
    return found


def get_exstyle(hwnd: int) -> int:
    return int(_get_long(wintypes.HWND(hwnd), GWL_EXSTYLE))


def top_level_hwnd(hwnd: int) -> int:
    """沿着 parent 链爬到顶层窗口。

    Tk 的 winfo_id() 给的是解释器内部窗口，不一定就是那个有 WM_CLASS 的顶层窗口；
    挂 wndproc 或按标题找窗口时必须用顶层句柄，否则消息发不到。
    """
    if not IS_WINDOWS or not hwnd:
        return hwnd
    current = int(hwnd)
    for _ in range(16):  # 防御性上限，正常 2~3 层就到顶
        parent = int(user32.GetParent(wintypes.HWND(current)) or 0)
        if not parent:
            break
        current = parent
    return current


def make_overlay_window(hwnd: int, color_key: int, click_through: bool, topmost: bool = True) -> int:
    """把 tkinter 建出来的普通窗口改造成"看得见、点不到、不抢焦点"的水印层。

    返回改造后的扩展样式，方便调用方（和验收脚本）直接核对位。
    """
    exstyle = get_exstyle(hwnd)
    exstyle |= WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
    if click_through:
        exstyle |= WS_EX_TRANSPARENT
    else:
        exstyle &= ~WS_EX_TRANSPARENT
    if topmost:
        exstyle |= WS_EX_TOPMOST
    _set_long(wintypes.HWND(hwnd), GWL_EXSTYLE, exstyle)
    # 扩展样式改完不刷新框架的话，窗口管理器有时不认，穿透就会时灵时不灵
    user32.SetWindowPos(
        wintypes.HWND(hwnd),
        wintypes.HWND(HWND_TOPMOST if topmost else HWND_NOTOPMOST),
        0,
        0,
        0,
        0,
        SWP_FRAMECHANGED | SWP_NOACTIVATE | SWP_NOMOVE | SWP_NOSIZE,
    )
    # 关键帧色必须用 SetLayeredWindowAttributes 生效：该色算全透明，其余像素不透明。
    # 不用 -alpha：那会把文字一起变淡，而且拖动时闪。
    user32.SetLayeredWindowAttributes(wintypes.HWND(hwnd), wintypes.COLORREF(color_key), 0, LWA_COLORKEY)
    return get_exstyle(hwnd)


def raise_topmost(hwnd: int) -> None:
    """只顶 z 序，不激活、不移动、不重画；4 秒一次，CPU 可以忽略。"""
    user32.SetWindowPos(
        wintypes.HWND(hwnd),
        wintypes.HWND(HWND_TOPMOST),
        0,
        0,
        0,
        0,
        SWP_NOACTIVATE | SWP_NOMOVE | SWP_NOSIZE,
    )


def set_click_through(hwnd: int, enabled: bool) -> int:
    exstyle = get_exstyle(hwnd)
    exstyle |= WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
    if enabled:
        exstyle |= WS_EX_TRANSPARENT
    else:
        exstyle &= ~WS_EX_TRANSPARENT
    _set_long(wintypes.HWND(hwnd), GWL_EXSTYLE, exstyle)
    user32.SetWindowPos(
        wintypes.HWND(hwnd),
        None,  # 不动 z 序
        0,
        0,
        0,
        0,
        SWP_FRAMECHANGED | SWP_NOACTIVATE | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER,
    )
    return get_exstyle(hwnd)


def dpi_for_point(x: int = 0, y: int = 0) -> int:
    """取系统 DPI，用来把字号换算成像素。PMv2 下 Tk 自己会换算，这里只做兜底。"""
    if not IS_WINDOWS:
        return 96
    try:
        dc = user32.GetDC(None)
        # 88 = LOGPIXELSX
        dpi = int(gdi32.GetDeviceCaps(dc, 88))
        user32.ReleaseDC(None, dc)
        if dpi > 0:
            return dpi
    except (AttributeError, OSError):
        pass
    try:
        return int(user32.GetDpiForSystem()) or 96
    except (AttributeError, OSError):
        return 96


def primary_dpi() -> int:
    return dpi_for_point(0, 0)


def to_physical_units(px: int, dpi: int) -> int:
    """Tk 的字体磅值在 PMv2 下已经按 DPI 缩放，这里只做安全兜底换算。"""
    if dpi <= 0:
        return px
    return int(round(px * dpi / 96.0))


def get_cursor_pos() -> tuple[int, int]:
    if not IS_WINDOWS:
        return (0, 0)
    pt = POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return (pt.x, pt.y)


# ---- 托盘 / 菜单 / 消息 ---------------------------------------------------


def _setup_window_proc_types() -> None:
    """窗口过程、消息、菜单相关 API 的参数类型。缺一个就会在 64 位下截断句柄。"""
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long
    user32.CallWindowProcW.argtypes = [
        ctypes.c_void_p,
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.CallWindowProcW.restype = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long
    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    user32.RegisterClassW.restype = wintypes.ATOM
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        wintypes.HMENU,
        wintypes.HINSTANCE,
        ctypes.c_void_p,
    ]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.DestroyWindow.restype = wintypes.BOOL
    user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    user32.GetMessageW.restype = ctypes.c_int
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.restype = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long
    user32.PostQuitMessage.argtypes = [ctypes.c_int]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
    user32.GetCursorPos.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
    user32.LoadIconW.restype = wintypes.HICON
    user32.LoadImageW.argtypes = [
        wintypes.HINSTANCE,
        wintypes.LPCWSTR,
        wintypes.UINT,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user32.LoadImageW.restype = wintypes.HANDLE
    user32.CreatePopupMenu.argtypes = []
    user32.CreatePopupMenu.restype = wintypes.HMENU
    user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
    user32.AppendMenuW.restype = wintypes.BOOL
    user32.DestroyMenu.argtypes = [wintypes.HMENU]
    user32.DestroyMenu.restype = wintypes.BOOL
    user32.TrackPopupMenu.argtypes = [
        wintypes.HMENU,
        wintypes.UINT,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        ctypes.c_void_p,
    ]
    user32.TrackPopupMenu.restype = wintypes.BOOL
    user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    user32.RegisterHotKey.restype = wintypes.BOOL
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.UnregisterHotKey.restype = wintypes.BOOL
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetSystemMetrics.restype = ctypes.c_int
    user32.GetParent.argtypes = [wintypes.HWND]
    user32.GetParent.restype = wintypes.HWND
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.c_void_p, MONITORENUMPROC, wintypes.LPARAM]
    user32.EnumDisplayMonitors.restype = wintypes.BOOL
    user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    user32.SetProcessDPIAware.argtypes = []
    user32.SetProcessDPIAware.restype = wintypes.BOOL


if IS_WINDOWS:
    _setup_window_proc_types()


def set_autostart(enabled: bool) -> bool:
    """写 HKCU\\...\\Run。单个用户级，不需要管理员权限。"""
    if not IS_WINDOWS:
        return False
    command = autostart_command()
    try:
        hkey = wintypes.HKEY()
        result = advapi32.RegCreateKeyExW(
            wintypes.HKEY(HKEY_CURRENT_USER),
            RUN_KEY,
            0,
            None,
            0,
            KEY_SET_VALUE | KEY_QUERY_VALUE,
            None,
            ctypes.byref(hkey),
            None,
        )
        if result != 0:
            print(f"[autostart] 打开注册表失败 code={result}", file=sys.stderr)
            return False
        try:
            if enabled:
                data = (command + "\0").encode("utf-16-le")
                rc = advapi32.RegSetValueExW(
                    hkey, RUN_VALUE_NAME, 0, REG_SZ, data, len(data)
                )
                if rc != 0:
                    print(f"[autostart] 写入失败 code={rc}", file=sys.stderr)
                    return False
                return True
            advapi32.RegDeleteValueW(hkey, RUN_VALUE_NAME)
            return True
        finally:
            advapi32.RegCloseKey(hkey)
    except (AttributeError, OSError) as exc:
        print(f"[autostart] 异常: {exc}", file=sys.stderr)
        return False


def get_autostart() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        hkey = wintypes.HKEY()
        if advapi32.RegOpenKeyExW(wintypes.HKEY(HKEY_CURRENT_USER), RUN_KEY, 0, KEY_QUERY_VALUE, ctypes.byref(hkey)) != 0:
            return False
        try:
            size = wintypes.DWORD(0)
            rc = advapi32.RegQueryValueExW(hkey, RUN_VALUE_NAME, None, None, None, ctypes.byref(size))
            return rc == 0 and size.value > 0
        finally:
            advapi32.RegCloseKey(hkey)
    except (AttributeError, OSError):
        return False


def autostart_command() -> str:
    """脚本模式要用 pythonw.exe，否则开机弹黑框。"""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pyw = Path(sys.executable).with_name("pythonw.exe")
    exe = pyw if pyw.exists() else Path(sys.executable)
    script = Path(__file__).resolve().parent.parent / "main.py"
    return f'"{exe}" "{script}"'


# ---- 验收/自检用的小工具 -------------------------------------------------


def window_exstyle_of_title(title: str) -> tuple[int, int] | None:
    """按标题找一个可见顶层窗口，返回 (hwnd, exstyle)。验收脚本靠它核对样式位。"""
    if not IS_WINDOWS:
        return None
    result: list[tuple[int, int]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, lparam):  # noqa: ANN001
        length = user32.GetWindowTextLengthW(hwnd)
        if length:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if buf.value == title and user32.IsWindowVisible(hwnd):
                result.append((int(hwnd), get_exstyle(hwnd)))
                return False
        return True

    user32.EnumWindows(_cb, 0)
    return result[0] if result else None


def overlay_windows(title_prefix: str = "ScreenWatermark") -> list[tuple[int, str, int]]:
    """列出所有标题以 title_prefix 开头的可见顶层窗口：(hwnd, 标题, 扩展样式)。"""
    if not IS_WINDOWS:
        return []
    result: list[tuple[int, str, int]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, lparam):  # noqa: ANN001
        length = user32.GetWindowTextLengthW(hwnd)
        if length:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if buf.value.startswith(title_prefix) and user32.IsWindowVisible(hwnd):
                result.append((int(hwnd), buf.value, get_exstyle(hwnd)))
        return True

    user32.EnumWindows(_cb, 0)
    return result
