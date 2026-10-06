# -*- coding: utf-8 -*-
"""Press a full combo such as Ctrl+Alt+F9 (keybd_event, so RegisterHotKey sees it).

ASCII only. Extends the simpler press_hotkey.py helper the other agents use by
accepting the whole combo string instead of a single hardcoded key.

    python press_combo.py "Ctrl+Alt+F9"
"""
from __future__ import annotations

import ctypes
import sys
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_EXTENDEDKEY = 0x0001

MOD_VK = {"ctrl": 0x11, "control": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B}


def vk_for(name: str) -> int:
    low = name.strip().lower()
    if low in MOD_VK:
        return MOD_VK[low]
    if len(name) == 1 and name.upper().isalnum():
        return ord(name.upper())
    if low.startswith("f") and low[1:].isdigit() and 1 <= int(low[1:]) <= 24:
        return 0x70 + int(low[1:]) - 1
    raise ValueError("unsupported key: " + name)


def press(combo: str) -> None:
    parts = [p for p in (x.strip() for x in combo.split("+")) if p]
    if not parts:
        raise ValueError("empty combo")
    mods = [vk_for(p) for p in parts[:-1]]
    main = vk_for(parts[-1])
    for vk in mods:
        user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.04)
    user32.keybd_event(main, 0, 0, 0)
    time.sleep(0.08)
    user32.keybd_event(main, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.04)
    for vk in reversed(mods):
        user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: press_combo.py <combo>", file=sys.stderr)
        return 2
    combo = sys.argv[1]
    try:
        press(combo)
    except ValueError as exc:
        print("press failed: %s" % exc, file=sys.stderr)
        return 2
    print("sent %s" % combo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
