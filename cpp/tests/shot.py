# -*- coding: utf-8 -*-
"""Full-screen capture + optional white backdrop.

Overlay windows are per-pixel alpha, so a screenshot composites them over
whatever is behind. Other agents repaint the desktop constantly, so an optional
plain white topmost window is used as a neutral canvas; the watermark is pushed
back above it before the shot.

ASCII only (PowerShell/cmd read non-BOM scripts with the OEM code page).

    python shot.py out.png [--backdrop]
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
SRCCOPY = 0x00CC0020

user32.CreateWindowExW.restype = wt.HWND
user32.CreateWindowExW.argtypes = [
    wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wt.HWND, wt.HMENU, wt.HINSTANCE, ctypes.c_void_p,
]
user32.RegisterClassW.argtypes = [ctypes.c_void_p]
user32.DefWindowProcW.restype = ctypes.c_longlong
user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, ctypes.c_ulonglong, ctypes.c_longlong]
user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wt.UINT]
kernel32.GetModuleHandleW.restype = wt.HMODULE


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hdc", wt.HDC), ("fErase", wt.BOOL), ("rcPaint", wt.RECT),
        ("fRestore", wt.BOOL), ("fIncUpdate", wt.BOOL), ("rgbReserved", ctypes.c_byte * 32),
    ]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wt.UINT), ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
        ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON), ("hCursor", wt.HANDLE),
        ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
        ("lpszClassName", wt.LPCWSTR),
    ]


WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def make_aware():
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        pass


def make_backdrop():
    brush = gdi32.CreateSolidBrush(0x00FFFFFF)

    def wndproc(hwnd, msg, wp, lp):
        if msg == 0x000F:  # WM_PAINT
            ps = PAINTSTRUCT()
            hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
            r = wt.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(r))
            user32.FillRect(hdc, ctypes.byref(r), brush)
            user32.EndPaint(hwnd, ctypes.byref(ps))
            return 0
        if msg == 0x0014:  # WM_ERASEBKGND
            return 1
        return user32.DefWindowProcW(hwnd, msg, ctypes.c_ulonglong(wp), ctypes.c_longlong(lp))

    proc = WNDPROC(wndproc)
    wc = WNDCLASSW()
    wc.lpfnWndProc = ctypes.cast(proc, ctypes.c_void_p)
    wc.hInstance = kernel32.GetModuleHandleW(None)
    wc.lpszClassName = "SwShotBackdrop"
    wc.hbrBackground = brush
    user32.RegisterClassW(ctypes.byref(wc))
    w = user32.GetSystemMetrics(0)
    h = user32.GetSystemMetrics(1)
    hwnd = user32.CreateWindowExW(0x00000008, "SwShotBackdrop", "backdrop", 0x80000000,
                                 0, 0, w, h, None, None,
                                 kernel32.GetModuleHandleW(None), None)
    user32.ShowWindow(hwnd, 5)
    user32.UpdateWindow(hwnd)
    time.sleep(0.5)
    return hwnd, proc


def raise_overlays():
    n = 0

    def cb(hwnd, _lp):
        nonlocal n
        b = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, b, 256)
        if b.value == "ScreenWatermarkOverlayWnd":
            user32.SetWindowPos(hwnd, wt.HWND(-1), 0, 0, 0, 0, 0x0013)
            n += 1
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    time.sleep(0.4)
    return n


def grab(path):
    w = user32.GetSystemMetrics(0)
    h = user32.GetSystemMetrics(1)
    screen = user32.GetDC(None)
    mem = gdi32.CreateCompatibleDC(screen)
    bmp = gdi32.CreateCompatibleBitmap(screen, w, h)
    old = gdi32.SelectObject(mem, bmp)
    gdi32.BitBlt(mem, 0, 0, w, h, screen, 0, 0, SRCCOPY)

    class BIH(ctypes.Structure):
        _fields_ = [
            ("biSize", wt.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
            ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
            ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", ctypes.c_long),
            ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wt.DWORD),
            ("biClrImportant", wt.DWORD),
        ]

    bi = BIH()
    bi.biSize = ctypes.sizeof(BIH)
    bi.biWidth = w
    bi.biHeight = -h
    bi.biPlanes = 1
    bi.biBitCount = 32
    buf = (ctypes.c_char * (w * h * 4))()
    gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0)
    gdi32.SelectObject(mem, old)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(None, screen)

    from PIL import Image
    img = Image.frombuffer("RGBA", (w, h), bytes(buf.raw), "raw", "BGRA", 0, 1).convert("RGB")
    img.save(path)

    px = img.load()
    grey = 0
    total = 0
    for y in range(0, h, 3):
        for x in range(0, w, 3):
            r, g, b = px[x, y]
            total += 1
            if max(r, g, b) - min(r, g, b) <= 12 and 24 <= (r + g + b) // 3 <= 240:
                grey += 1
    print("SHOT %s %dx%d grey=%.4f" % (path, w, h, grey / max(total, 1)))
    return grey / max(total, 1)


def main() -> int:
    make_aware()
    args = sys.argv[1:]
    backdrop = "--backdrop" in args
    args = [a for a in args if a != "--backdrop"]
    path = args[0] if args else "shot.png"
    hwnd = None
    proc = None
    if backdrop:
        hwnd, proc = make_backdrop()
    raise_overlays()
    grab(path)
    if hwnd:
        user32.DestroyWindow(hwnd)
        time.sleep(0.3)
    _ = proc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
