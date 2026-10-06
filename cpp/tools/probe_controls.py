# -*- coding: utf-8 -*-
"""One-off probe: are the control ids the test harness uses actually the right HWNDs?

This exists because a whole round of "control X does not work" numbers turned out
to be the harness writing into the wrong window.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
import subprocess
import sys
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetDlgItem.restype = wt.HWND
WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

ID_TEXT = 1001
ID_FONTSIZE = 1002
ID_FONTFAMILY = 1003
ID_BOLD = 1004
ID_LINESPACING = 1026
ID_APPLY = 1020


def find(cls):
    res = []

    def cb(h, _):
        b = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(h, b, 256)
        if b.value == cls:
            res.append(h)
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return res[0] if res else None


def cls_of(h):
    b = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(h, b, 256)
    return b.value


def txt(h):
    if not h:
        return "<null>"
    n = user32.GetWindowTextLengthW(h)
    b = ctypes.create_unicode_buffer(n + 2)
    user32.GetWindowTextW(h, b, n + 2)
    return b.value


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    cfgdir = os.path.join(here, "..", "tests", "out", "probe.dir")
    cfgdir = os.path.abspath(cfgdir)
    os.makedirs(cfgdir, exist_ok=True)
    cfg = {
        "text": "PROBE-TEXT",
        "font_size": 30,
        "hotkeys": {"toggle": "Ctrl+Alt+F9", "settings": "Ctrl+Alt+S", "quit": "Ctrl+Alt+Q"},
    }
    with open(os.path.join(cfgdir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

    exe = os.path.abspath(os.path.join(here, "..", "build", "ScreenWatermark.exe"))
    subprocess.run(["taskkill", "/f", "/im", "ScreenWatermark.exe"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.0)
    p = subprocess.Popen(
        [exe, "--config", os.path.join(cfgdir, "config.json")],
        stderr=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
    )
    time.sleep(3.0)
    panel = find("ScreenWatermarkSettingsWnd")
    if not panel:
        print("panel not found")
        p.kill()
        return 1
    user32.ShowWindow(panel, 5)
    time.sleep(1.2)
    print("panel hwnd = 0x%X" % panel)

    for cid in (ID_TEXT, ID_FONTSIZE, ID_FONTFAMILY, ID_BOLD, ID_LINESPACING, ID_APPLY):
        h = user32.GetDlgItem(panel, cid)
        print("  ID %-5d -> hwnd=0x%-8X class=%-14s text=%r" % (cid, h or 0, cls_of(h), txt(h)))

    print("-- write then read back --")
    for cid, val in ((ID_TEXT, "WRITTEN-TEXT"), (ID_FONTSIZE, "64"), (ID_LINESPACING, "2.60")):
        h = user32.GetDlgItem(panel, cid)
        user32.SetWindowTextW(h, val)
        print("  set ID %-5d to %-14r -> readback=%r" % (cid, val, txt(h)))

    print("-- all children of the panel (id, class, text) --")
    GWL_ID = -12
    user32.GetWindowLongPtrW.restype = ctypes.c_void_p

    def cb_child(h, _):
        cid = user32.GetWindowLongPtrW(h, GWL_ID) or 0
        print("     id=%-6d class=%-16s text=%r" % (cid, cls_of(h), txt(h)))
        return True

    user32.EnumChildWindows(panel, WNDENUMPROC(cb_child), 0)

    p.kill()
    subprocess.run(["taskkill", "/f", "/im", "ScreenWatermark.exe"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
