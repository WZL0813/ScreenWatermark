# -*- coding: utf-8 -*-
"""把设置面板的子控件逐个列出来：类名、文本、矩形、可见性。

为什么要它：原生控件的气泡提示是"看着像有问题"，只有把每个子窗口的
类名和尺寸打出来，才能确认 TRACKBAR 是不是真的建出来了、尺寸对不对。

用法： python tools/dump_controls.py <pid> [父窗口类名]
"""
import ctypes
import sys
from ctypes import wintypes

u32 = ctypes.WinDLL("user32", use_last_error=True)
EnumWindows = u32.EnumWindows
EnumChildWindows = u32.EnumChildWindows
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
GetClassNameW = u32.GetClassNameW
GetWindowTextW = u32.GetWindowTextW
GetWindowTextLengthW = u32.GetWindowTextLengthW
GetWindowRect = u32.GetWindowRect
IsWindowVisible = u32.IsWindowVisible
GetWindowThreadProcessId = u32.GetWindowThreadProcessId
GetDlgCtrlID = u32.GetDlgCtrlID
GetWindowLongW = u32.GetWindowLongW

GWL_STYLE = -16


def cls(h):
    b = ctypes.create_unicode_buffer(256)
    GetClassNameW(h, b, 256)
    return b.value


def text(h):
    n = GetWindowTextLengthW(h)
    if n <= 0:
        return ""
    b = ctypes.create_unicode_buffer(n + 2)
    GetWindowTextW(h, b, n + 2)
    return b.value


def main():
    if len(sys.argv) < 2:
        print("usage: dump_controls.py <pid> [parent_class]")
        return 2
    pid = int(sys.argv[1])
    want = sys.argv[2] if len(sys.argv) > 2 else "ScreenWatermarkSettingsPanel"

    tops = []

    def cb(hwnd, _):
        wpid = wintypes.DWORD()
        GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value == pid and cls(hwnd) == want:
            tops.append(hwnd)
        return True

    EnumWindows(EnumWindowsProc(cb), 0)
    if not tops:
        print("FAIL 找不到类名 %s 的顶层窗口（pid=%d）" % (want, pid))
        return 1

    for top in tops:
        r = wintypes.RECT()
        GetWindowRect(top, ctypes.byref(r))
        print("TOP hwnd=0x%X class=%s text=%r rect=%dx%d+%d+%d visible=%s"
              % (top, cls(top), text(top), r.right - r.left, r.bottom - r.top,
                 r.left, r.top, bool(IsWindowVisible(top))))
        rows = []

        def cb2(h, _):
            rr = wintypes.RECT()
            GetWindowRect(h, ctypes.byref(rr))
            rows.append((GetDlgCtrlID(h), cls(h), text(h),
                         rr.left - r.left, rr.top - r.top,
                         rr.right - rr.left, rr.bottom - rr.top,
                         bool(IsWindowVisible(h)),
                         GetWindowLongW(h, GWL_STYLE) & 0xFFFFFFFF))
            return True

        EnumChildWindows(top, EnumWindowsProc(cb2), 0)
        print("子控件数量: %d" % len(rows))
        print("%-6s %-22s %-24s %-18s %-9s %s" % ("id", "class", "text", "rect(x,y,w,h)", "visible", "style"))
        for rid, c, t, x, y, w, h, vis, st in sorted(rows, key=lambda z: (z[3], z[4])):
            print("%-6d %-22s %-24s (%4d,%4d,%4d,%4d) %-9s 0x%08X"
                  % (rid, c, (t[:22] + "..") if len(t) > 24 else t, x, y, w, h, vis, st))
    return 0


if __name__ == "__main__":
    sys.exit(main())
