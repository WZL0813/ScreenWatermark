import ctypes
from ctypes import wintypes

u = ctypes.WinDLL("user32", use_last_error=True)
u.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
u.RegisterHotKey.restype = wintypes.BOOL
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x4000
for i, (n, m, k) in enumerate([("Ctrl+Alt+Shift+W", MOD_CONTROL | MOD_ALT | MOD_SHIFT, 0x57),
                               ("Ctrl+Alt+Shift+Q", MOD_CONTROL | MOD_ALT | MOD_SHIFT, 0x51),
                               ("Ctrl+Alt+S", MOD_CONTROL | MOD_ALT, 0x53)]):
    ctypes.set_last_error(0)
    ok = u.RegisterHotKey(None, 9900 + i, m | MOD_NOREPEAT, k)
    print("   %-18s %s" % (n, "FREE" if ok else "TAKEN(busy)"))
    if ok:
        u.UnregisterHotKey(None, 9900 + i)
