# -*- coding: utf-8 -*-
"""Per-control check driven by the app's own rendered bitmap.

Screenshots were useless here: other agents repaint the desktop, and two topmost
windows (watermark + a white test backdrop) kept fighting over z-order, so the
numbers were noise. The app can now dump the exact bitmap it renders
(--dump-bitmap), which is the end of the render chain and therefore the right
thing to compare.

For every control: rebase -> dump A -> change one control -> Apply -> dump B ->
compare A and B. A and B differ only by that control, so nothing earlier can
pollute the result.

ASCII only (PowerShell/cmd read non-BOM scripts with the OEM code page).
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
import shutil
import subprocess
import sys
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)
WM_COMMAND = 0x0111
WM_HSCROLL = 0x0114
WM_APP = 0x8000
MSG_DUMP_FRAME = WM_APP + 16
EN_CHANGE = 0x0300
BN_CLICKED = 0x0000
CBN_SELCHANGE = 0x0001
BM_CLICK = 0x00F5
BM_SETCHECK = 0x00F1
BM_GETCHECK = 0x00F0
TBM_SETPOS = 0x0405
CB_SETCURSEL = 0x014E
CB_FINDSTRINGEXACT = 0x0158

ID_TEXT = 1001
ID_FONTSIZE = 1002
ID_FONTFAMILY = 1003
ID_BOLD = 1004
ID_ITALIC = 1005
ID_OPACITY = 1006
ID_ANGLE = 1008
ID_GAPX = 1010
ID_GAPY = 1011
ID_LINESPACING = 1026
ID_LIVEPREVIEW = 1016
ID_PHASE = 1018
ID_APPLY = 1020

WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
user32.GetWindowLongPtrW.restype = ctypes.c_void_p


def dlg_item(parent, cid: int):
    """Direct children only: a ComboBox's internal Edit can share an id with a
    real control (measured: both 1001), and GetDlgItem would return that one."""
    h = user32.GetWindow(parent, 5)  # GW_CHILD
    while h:
        if (user32.GetWindowLongPtrW(h, -12) or 0) == cid:  # GWL_ID
            return h
        h = user32.GetWindow(h, 2)  # GW_HWNDNEXT
    return None


def find_window(cls: str, timeout: float = 8.0):
    end = time.time() + timeout
    while time.time() < end:
        found = []

        def cb(hwnd, _lp):
            b = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, b, 256)
            if b.value == cls:
                found.append(hwnd)
            return True

        user32.EnumWindows(WNDENUMPROC(cb), 0)
        if found:
            return found[0]
        time.sleep(0.15)
    return None


def set_text(parent, cid, text):
    h = dlg_item(parent, cid)
    user32.SetWindowTextW(h, text)
    user32.SendMessageW(parent, WM_COMMAND, (EN_CHANGE << 16) | (cid & 0xFFFF), h)


def click(parent, cid):
    h = dlg_item(parent, cid)
    user32.SendMessageW(h, BM_CLICK, 0, 0)
    user32.SendMessageW(parent, WM_COMMAND, (BN_CLICKED << 16) | (cid & 0xFFFF), h)


def set_check(parent, cid, on):
    h = dlg_item(parent, cid)
    user32.SendMessageW(h, BM_SETCHECK, 1 if on else 0, 0)
    user32.SendMessageW(parent, WM_COMMAND, (BN_CLICKED << 16) | (cid & 0xFFFF), h)


def check_now(parent, cid):
    return user32.SendMessageW(dlg_item(parent, cid), BM_GETCHECK, 0, 0)


def set_trackbar(parent, cid, pos):
    h = dlg_item(parent, cid)
    user32.SendMessageW(h, TBM_SETPOS, 1, pos)
    user32.SendMessageW(parent, WM_HSCROLL, 0, h)


def set_combo(parent, cid, text):
    h = dlg_item(parent, cid)
    idx = user32.SendMessageW(h, CB_FINDSTRINGEXACT, -1, text)
    if idx >= 0:
        user32.SendMessageW(h, CB_SETCURSEL, idx, 0)
    else:
        user32.SetWindowTextW(h, text)
    user32.SendMessageW(parent, WM_COMMAND, (CBN_SELCHANGE << 16) | (cid & 0xFFFF), h)


def kill_stale(timeout: float = 10.0):
    subprocess.run(["taskkill", "/f", "/im", "ScreenWatermark.exe"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    end = time.time() + timeout
    while time.time() < end:
        out = subprocess.run(["tasklist", "/fi", "IMAGENAME eq ScreenWatermark.exe"],
                             capture_output=True, text=True).stdout
        if "ScreenWatermark.exe" not in out:
            return
        time.sleep(0.3)
    raise RuntimeError("ScreenWatermark.exe still running")


def canvas_stats(path):
    """(grey pixel count, mean alpha-ish coverage) of a dumped frame."""
    from PIL import Image  # noqa: PLC0415

    img = Image.open(path).convert("RGBA")
    px = img.load()
    w, h = img.size
    grey = 0
    total = 0
    for y in range(0, h, 3):
        for x in range(0, w, 3):
            r, g, b, a = px[x, y]
            total += 1
            if a > 8:
                grey += 1
    return grey, total


def canvas_diff(p1, p2):
    """Share of sampled pixels whose alpha coverage differs."""
    from PIL import Image, ImageChops  # noqa: PLC0415

    a = Image.open(p1).convert("RGBA")
    b = Image.open(p2).convert("RGBA")
    if a.size != b.size:
        return 1.0
    pa = a.split()[3].load()
    pb = b.split()[3].load()
    w, h = a.size
    diff = 0
    total = 0
    for y in range(0, h, 3):
        for x in range(0, w, 3):
            total += 1
            if abs(pa[x, y] - pb[x, y]) > 3:
                diff += 1
    return diff / max(total, 1)


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    outdir = os.path.join(here, "out")
    os.makedirs(outdir, exist_ok=True)
    cfgdir = os.path.join(outdir, "bitmap.dir")
    os.makedirs(cfgdir, exist_ok=True)
    frame = os.path.join(outdir, "frame.png")
    frame_a = os.path.join(outdir, "frame-a.png")
    frame_b = os.path.join(outdir, "frame-b.png")

    cfg = {
        "text": "PERCONTROL",
        "font_family": "Microsoft YaHei",
        "font_size": 30,
        "bold": False,
        "italic": False,
        "color": "#808080",
        "opacity": 0.35,
        "angle": -30,
        "gap_x": 150,
        "gap_y": 120,
        "line_spacing": 1.2,
        "enabled": True,
        "click_through": True,
        "template": False,
        "time_format": "%Y-%m-%d %H:%M",
        "refresh_seconds": 30,
        "all_monitors": True,
        "phase_offset": True,
        "autostart": False,
        "hotkeys": {"toggle": "Ctrl+Alt+F9", "settings": "Ctrl+Alt+S", "quit": "Ctrl+Alt+Q"},
    }
    kill_stale()
    cfgpath = os.path.join(cfgdir, "config.json")
    with open(cfgpath, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

    exe = os.path.abspath(os.path.join(here, "..", "build", "ScreenWatermark.exe"))
    for p in (frame, frame_a, frame_b):
        if os.path.exists(p):
            os.remove(p)
    proc = subprocess.Popen([exe, "--config", cfgpath, "--dump-bitmap", frame],
                            stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    time.sleep(3.5)
    if proc.poll() is not None:
        print("FAIL: app exited early (%s)" % proc.returncode)
        return 1
    msgwnd = find_window("ScreenWatermarkMsgWnd", 5.0)
    if not msgwnd:
        print("FAIL: message window not found")
        proc.kill()
        return 1
    panel = find_window("ScreenWatermarkSettingsWnd", 5.0)
    if not panel:
        print("FAIL: panel window not found")
        proc.kill()
        return 1
    user32.ShowWindow(panel, 5)
    time.sleep(1.2)

    def next_frame(timeout: float = 8.0, before: float = 0.0):
        """Wait for the app to write frame-<n>.png with n greater than `before`."""
        end = time.time() + timeout
        while time.time() < end:
            best = None
            for fn in os.listdir(outdir):
                if fn.startswith("frame-") and fn.endswith(".png"):
                    try:
                        n = int(fn[6:-4])
                    except ValueError:
                        continue
                    if n > before and (best is None or n > best[0]):
                        best = (n, os.path.join(outdir, fn))
            if best:
                time.sleep(0.2)  # let the write finish
                return best[0], best[1]
            time.sleep(0.1)
        return None, None

    # live preview OFF: only Apply may change the watermark
    set_check(panel, ID_LIVEPREVIEW, False)
    time.sleep(0.8)
    print("live preview checkbox = %d (0 = off)" % check_now(panel, ID_LIVEPREVIEW))

    def rebase():
        p = find_window("ScreenWatermarkSettingsWnd", 3.0)
        set_text(p, ID_TEXT, cfg["text"])
        set_text(p, ID_FONTSIZE, "30")
        set_combo(p, ID_FONTFAMILY, "Microsoft YaHei")
        set_trackbar(p, ID_OPACITY, 35)
        set_trackbar(p, ID_ANGLE, -30)
        set_text(p, ID_GAPX, "150")
        set_text(p, ID_GAPY, "120")
        set_text(p, ID_LINESPACING, "1.20")
        set_check(p, ID_BOLD, False)
        set_check(p, ID_ITALIC, False)
        set_check(p, ID_PHASE, True)
        click(p, ID_APPLY)
        time.sleep(1.0)

    results = []
    seq = 0
    for name, action in [
        ("text", lambda p: set_text(p, ID_TEXT, "PERCONTROL-CHANGED-TEXT")),
        ("font_size 30->64", lambda p: set_text(p, ID_FONTSIZE, "64")),
        ("font_family YaHei->SimSun", lambda p: set_combo(p, ID_FONTFAMILY, "SimSun")),
        ("opacity 35->90", lambda p: set_trackbar(p, ID_OPACITY, 90)),
        ("angle -30->25", lambda p: set_trackbar(p, ID_ANGLE, 25)),
        ("gap_x 150->500", lambda p: set_text(p, ID_GAPX, "500")),
        ("gap_y 120->400", lambda p: set_text(p, ID_GAPY, "400")),
        ("line_spacing 1.2->2.6", lambda p: set_text(p, ID_LINESPACING, "2.60")),
        ("bold off->on", lambda p: set_check(p, ID_BOLD, True)),
        ("italic off->on", lambda p: set_check(p, ID_ITALIC, True)),
        ("phase_offset on->off", lambda p: set_check(p, ID_PHASE, False)),
    ]:
        rebase()
        # rebase 自己会落一帧，拿它当 A
        seq, fa = next_frame(before=seq)
        if not fa:
            print("FAIL: no baseline frame for %s" % name)
            break
        action(find_window("ScreenWatermarkSettingsWnd", 3.0))
        time.sleep(0.4)
        click(find_window("ScreenWatermarkSettingsWnd", 3.0), ID_APPLY)
        time.sleep(0.8)
        seq, fb = next_frame(before=seq)
        if not fb:
            print("FAIL: no changed frame for %s" % name)
            break
        ratio = canvas_diff(fa, fb)
        ga, _ = canvas_stats(fa)
        gb, _ = canvas_stats(fb)
        results.append((name, ratio, ga, gb))
        print("  %-26s bitmap changed=%7.3f%%   covered px %7d -> %7d"
              % (name, ratio * 100.0, ga, gb))

    print()
    threshold = 0.002
    print("=== summary (threshold %.2f%% of sampled pixels) ===" % (threshold * 100.0))
    bad = []
    for name, ratio, ga, gb in results:
        flag = "OK  " if ratio > threshold else "FAIL"
        if ratio <= threshold:
            bad.append(name)
        print("%s %-26s %7.3f%%   (%d -> %d)" % (flag, name, ratio * 100.0, ga, gb))
    print()
    print("controls with no visible change: %s" % (", ".join(bad) if bad else "(none)"))

    proc.kill()
    kill_stale()
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
