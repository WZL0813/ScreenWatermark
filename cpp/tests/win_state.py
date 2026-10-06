# -*- coding: utf-8 -*-
"""Watermark window probe: proves the overlay is really on screen and toggling.

ASCII only. Prints a single-line signature so it can be diffed across a hotkey
press:
    marker  -> "OVERLAY n=N visible=V ... pos=x,y size=WxH"
    shot    -> full-screen PNG + the share of greyish pixels (the watermark)

DPI note: this box runs at 175%, so SetProcessDpiAwarenessContext(-4) is called
before any screen query, otherwise the numbers come back virtualised.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import sys

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

SRCCOPY = 0x00CC0020
GWL_EXSTYLE = -20

WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def make_aware() -> None:
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        pass


def overlay_windows():
    found = []

    def cb(hwnd, _lp):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        if buf.value == "ScreenWatermarkOverlayWnd":
            rect = wt.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            user32.GetWindowLongPtrW.restype = ctypes.c_void_p
            ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) or 0
            found.append(
                {
                    "hwnd": hwnd,
                    "visible": bool(user32.IsWindowVisible(hwnd)),
                    "rect": (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top),
                    "ex": ex,
                }
            )
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return found


def cmd_marker(_args) -> int:
    make_aware()
    wins = overlay_windows()
    if not wins:
        print("MARKER overlay=0 visible=0")
        return 1
    w = wins[0]
    x, y, cw, ch = w["rect"]
    print(
        "MARKER overlay=%d visible=%d pos=%d,%d size=%dx%d EX=0x%08X"
        % (len(wins), 1 if w["visible"] else 0, x, y, cw, ch, w["ex"])
    )
    return 0


def cmd_shot(args) -> int:
    from PIL import Image  # noqa: PLC0415  (only needed for the pixel path)

    make_aware()
    path = args[0] if args else "shot.png"
    w = user32.GetSystemMetrics(0)
    h = user32.GetSystemMetrics(1)
    screen = user32.GetDC(None)
    mem = gdi32.CreateCompatibleDC(screen)
    bmp = gdi32.CreateCompatibleBitmap(screen, w, h)
    old = gdi32.SelectObject(mem, bmp)
    gdi32.BitBlt(mem, 0, 0, w, h, screen, 0, 0, SRCCOPY)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wt.DWORD),
            ("biWidth", ctypes.c_long),
            ("biHeight", ctypes.c_long),
            ("biPlanes", wt.WORD),
            ("biBitCount", wt.WORD),
            ("biCompression", wt.DWORD),
            ("biSizeImage", wt.DWORD),
            ("biXPelsPerMeter", ctypes.c_long),
            ("biYPelsPerMeter", ctypes.c_long),
            ("biClrUsed", wt.DWORD),
            ("biClrImportant", wt.DWORD),
        ]

    bi = BITMAPINFOHEADER()
    bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.biWidth = w
    bi.biHeight = -h
    bi.biPlanes = 1
    bi.biBitCount = 32
    bi.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0)
    gdi32.SelectObject(mem, old)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(None, screen)

    img = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")
    img.save(path)
    px = img.load()
    total = 0
    grey = 0
    for yy in range(0, h, 2):
        for xx in range(0, w, 2):
            r, g, b = px[xx, yy]
            total += 1
            if max(r, g, b) - min(r, g, b) <= 12 and 24 <= (r + g + b) // 3 <= 235:
                grey += 1
    print("SHOT %s %dx%d grey=%.4f" % (path, w, h, grey / max(total, 1)))
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd = sys.argv[1]
    if cmd == "marker":
        return cmd_marker(sys.argv[2:])
    if cmd == "shot":
        return cmd_shot(sys.argv[2:])
    print("unknown command: " + cmd, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
