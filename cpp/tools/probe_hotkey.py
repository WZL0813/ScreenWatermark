# -*- coding: utf-8 -*-
"""Hotkey probes for ScreenWatermark verification.

ASCII only on purpose: PowerShell 5.1 and cmd read non-BOM scripts with the
OEM/ANSI code page, and a stray byte sequence can swallow a quote.

Commands:
    python probe_hotkey.py parse "Ctrl+Alt+F9"     # print normalized combo
    python probe_hotkey.py state "Ctrl+Alt+F9"     # FREE / TAKEN
    python probe_hotkey.py state-many "Ctrl+Alt+W" "Ctrl+Alt+F9"
    python probe_hotkey.py windows                 # list ScreenWatermark windows + exstyle
    python probe_hotkey.py wmhotkey <hwnd> <id>    # note: not used, kept for reference
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys

user32 = ctypes.WinDLL("user32", use_last_error=True)

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
ERROR_HOTKEY_ALREADY_REGISTERED = 1409

VK_NAMES = {0x11: "Ctrl", 0x12: "Alt", 0x10: "Shift", 0x5B: "Win", 0x5C: "Win"}


def parse_combo(text: str):
    """Return (mods, vk) or raise ValueError. Mirrors the C++ parser."""
    text = text.strip()
    if not text:
        return 0, 0
    mods = 0
    vk = 0
    seen_main = False
    for raw in text.split("+"):
        part = raw.strip()
        if not part:
            continue
        low = part.lower()
        if low in ("ctrl", "control"):
            mods |= MOD_CONTROL
            continue
        if low == "alt":
            mods |= MOD_ALT
            continue
        if low == "shift":
            mods |= MOD_SHIFT
            continue
        if low in ("win", "windows"):
            mods |= MOD_WIN
            continue
        if seen_main:
            raise ValueError("more than one main key: " + part)
        if len(part) == 1 and part.upper().isalnum():
            vk = ord(part.upper())
        elif low.startswith("f") and low[1:].isdigit() and 1 <= int(low[1:]) <= 24:
            vk = 0x70 + int(low[1:]) - 1
        else:
            raise ValueError("unknown key: " + part)
        seen_main = True
    if not seen_main:
        raise ValueError("no main key")
    return mods, vk


def combo_text(mods: int, vk: int) -> str:
    out = []
    if mods & MOD_CONTROL:
        out.append("Ctrl")
    if mods & MOD_ALT:
        out.append("Alt")
    if mods & MOD_SHIFT:
        out.append("Shift")
    if mods & MOD_WIN:
        out.append("Win")
    if 0x70 <= vk <= 0x87:
        out.append("F%d" % (vk - 0x70 + 1))
    else:
        out.append(chr(vk))
    return "+".join(out)


def hotkey_state(text: str) -> str:
    """Register then immediately unregister; FREE means nobody owns it."""
    mods, vk = parse_combo(text)
    if vk == 0:
        return "EMPTY"
    ctypes.set_last_error(0)
    ok = user32.RegisterHotKey(None, 0xB000, mods | MOD_NOREPEAT, vk)
    err = ctypes.get_last_error()
    if ok:
        user32.UnregisterHotKey(None, 0xB000)
        return "FREE"
    if err == ERROR_HOTKEY_ALREADY_REGISTERED:
        return "TAKEN"
    return "ERR%d" % err


def cmd_state(args) -> int:
    for a in args:
        try:
            mods, vk = parse_combo(a)
            print("%-22s -> %s   (mods=0x%X vk=0x%02X)" % (a, hotkey_state(a), mods, vk))
        except ValueError as exc:
            print("%-22s -> PARSE-FAIL (%s)" % (a, exc))
    return 0


def cmd_parse(args) -> int:
    for a in args:
        try:
            mods, vk = parse_combo(a)
            print("%-22s -> %s" % (a, combo_text(mods, vk) if vk else "(none)"))
        except ValueError as exc:
            print("%-22s -> PARSE-FAIL (%s)" % (a, exc))
    return 0


WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def cmd_windows(_args) -> int:
    GWL_EXSTYLE = -20

    def cb(hwnd, _lp):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        cls = buf.value
        if "ScreenWatermark" not in cls:
            return True
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        rect = wt.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        user32.GetWindowLongPtrW.restype = ctypes.c_void_p
        ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) or 0
        print(
            "%-28s hwnd=0x%X pid=%-6d visible=%-5s %dx%d EX=0x%08X "
            "[LAYERED=%s TRANSPARENT=%s TOOLWINDOW=%s NOACTIVATE=%s]"
            % (
                cls,
                hwnd,
                pid.value,
                bool(user32.IsWindowVisible(hwnd)),
                rect.right - rect.left,
                rect.bottom - rect.top,
                ex,
                bool(ex & 0x80000),
                bool(ex & 0x20),
                bool(ex & 0x80),
                bool(ex & 0x8000000),
            )
        )
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd = sys.argv[1]
    args = sys.argv[2:]
    if cmd == "state":
        return cmd_state(args)
    if cmd == "state-many":
        return cmd_state(args)
    if cmd == "parse":
        return cmd_parse(args)
    if cmd == "windows":
        # DPI aware so the rect comes back in physical pixels (this box is at 175%)
        try:
            user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except Exception:
            pass
        return cmd_windows(args)
    print("unknown command: " + cmd, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
