# -*- coding: utf-8 -*-
"""独立进程探测全局热键占用情况（严格版）。

关键点：`use_last_error=True` + 每次调用前 `set_last_error(0)`，
否则读到的可能是更早调用留下的陈旧错误码。

注意 RegisterHotKey 必须传**真实的 vk**：之前 Rust 版 --probe 里写成 vk=0，
等于探测一个不存在的组合，于是永远"成功"，把"Ctrl+Alt+W 已被占用"盖住了。

用法： python tools/probe.py
先杀掉所有 ScreenWatermark 进程再跑，看到的是"本机常驻程序"的净占用；
启动本程序后再跑，看到的是"本程序实际抢到了哪些"。
"""
import ctypes
from ctypes import wintypes

u = ctypes.WinDLL("user32", use_last_error=True)
u.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
u.RegisterHotKey.restype = wintypes.BOOL
u.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
u.UnregisterHotKey.restype = wintypes.BOOL

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x4000

# 先探"首选组合"，再探"降级组合"，最后把 Ctrl+Alt+S 也带上。
CASES = [
    ("Ctrl+Alt+W", MOD_CONTROL | MOD_ALT, 0x57),
    ("Ctrl+Alt+Q", MOD_CONTROL | MOD_ALT, 0x51),
    ("Ctrl+Alt+S", MOD_CONTROL | MOD_ALT, 0x53),
    ("Ctrl+Alt+Shift+W", MOD_CONTROL | MOD_ALT | MOD_SHIFT, 0x57),
    ("Ctrl+Alt+Shift+Q", MOD_CONTROL | MOD_ALT | MOD_SHIFT, 0x51),
    ("Ctrl+Alt+Shift+S", MOD_CONTROL | MOD_ALT | MOD_SHIFT, 0x53),
]


def main():
    print("热键占用探测（FREE=可注册 / TAKEN=已被占用）")
    for i, (name, mods, vk) in enumerate(CASES):
        ctypes.set_last_error(0)
        ok = u.RegisterHotKey(None, 9900 + i, mods | MOD_NOREPEAT, vk)
        err = ctypes.get_last_error()
        if ok:
            print("   %-18s FREE" % name)
            u.UnregisterHotKey(None, 9900 + i)
        else:
            print("   %-18s TAKEN(被占用) err=%d" % (name, err))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
