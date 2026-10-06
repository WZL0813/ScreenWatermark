# -*- coding: utf-8 -*-
"""Drive the settings panel by control id, then measure whether the watermark changed.

Why by id and not by mouse: clicking depends on DPI, focus and Z-order. The panel
is a plain Win32 window, so SendMessage/SetWindowText on GetDlgItem is exact.

Notifies the panel the same way a user would:
  * edits    -> SetWindowTextW + a synthetic EN_CHANGE in WM_COMMAND
  * checkbox -> BM_CLICK (fires BN_CLICKED for the panel to see)
  * trackbar -> TBM_SETPOS + WM_HSCROLL to its parent
  * combo    -> CB_SETCURSEL + CBN_SELCHANGE in WM_COMMAND

ASCII only (PowerShell/cmd read non-BOM scripts with the OEM code page).
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
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

SRCCOPY = 0x00CC0020
WM_COMMAND = 0x0111
WM_HSCROLL = 0x0114
EN_CHANGE = 0x0300
BN_CLICKED = 0x0000
CBN_SELCHANGE = 0x0001
BM_CLICK = 0x00F5
BM_SETCHECK = 0x00F1
TBM_SETPOS = 0x0405
TBM_GETPOS = 0x0400
CB_SETCURSEL = 0x014E
CB_GETCOUNT = 0x0146
CB_GETLBTEXT = 0x0148
CB_FINDSTRINGEXACT = 0x0158
SB_SETTEXT = 0x0401

# control ids straight out of settings.cpp
ID_TEXT = 1001
ID_FONTSIZE = 1002
ID_FONTFAMILY = 1003
ID_BOLD = 1004
ID_ITALIC = 1005
ID_OPACITY = 1006
ID_ANGLE = 1008
ID_GAPX = 1010
ID_GAPY = 1011
ID_COLOR = 1012
ID_TEMPLATE = 1014
ID_TIMEFMT = 1015
ID_ALLMON = 1017
ID_PHASE = 1018
ID_CLICKTHROUGH = 1019
ID_APPLY = 1020
ID_HIDE = 1021
ID_SAVE = 1022
ID_RESET = 1023
ID_LINESPACING = 1026

WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def make_aware() -> None:
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        pass


def kill_stale(timeout: float = 8.0) -> None:
    """Wait until every previous ScreenWatermark.exe is really gone.

    The app is single-instance (deliberately: the second launch exits silently),
    so a leftover process makes the next launch a no-op and the test then drives
    a panel that belongs to the old process. That produced a whole round of
    bogus numbers, hence this hard gate.
    """
    subprocess.run(
        ["taskkill", "/f", "/im", "ScreenWatermark.exe"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    end = time.time() + timeout
    while time.time() < end:
        out = subprocess.run(
            ["tasklist", "/fi", "IMAGENAME eq ScreenWatermark.exe"],
            capture_output=True,
            text=True,
        ).stdout
        if "ScreenWatermark.exe" not in out:
            return
        time.sleep(0.3)
    raise RuntimeError("ScreenWatermark.exe still running; refusing to test")


def wait_for_startup(log_path: str, marker: str, timeout: float = 10.0) -> bool:
    """Poll debug.log until the app logged the config it actually loaded."""
    end = time.time() + timeout
    while time.time() < end:
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                if marker in f.read():
                    return True
        time.sleep(0.2)
    return False


def find_window(cls: str, timeout: float = 5.0):
    end = time.time() + timeout
    while time.time() < end:
        found = []

        def cb(hwnd, _lp):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, buf, 256)
            if buf.value == cls:
                found.append(hwnd)
            return True

        user32.EnumWindows(WNDENUMPROC(cb), 0)
        if found:
            return found[0]
        time.sleep(0.15)
    return None


def dlg_item(parent, cid: int):
    """Find a control by id among the panel's *direct* children.

    Do not use GetDlgItem here. A ComboBox owns an internal Edit child, and its
    GWLP_ID can collide with a real control (measured on this panel: the font
    ComboBox's internal Edit is also id 1001, same as the watermark text box).
    GetDlgItem walks children in z-order and happily returns that internal Edit,
    so writes land in the wrong window and the control looks broken.
    """
    GWL_ID = -12
    user32.GetWindowLongPtrW.restype = ctypes.c_void_p
    h = user32.GetWindow(parent, 5)  # GW_CHILD
    while h:
        if (user32.GetWindowLongPtrW(h, GWL_ID) or 0) == cid:
            return h
        h = user32.GetWindow(h, 2)  # GW_HWNDNEXT
    return None


def child_text(parent, cid: int) -> str:
    h = dlg_item(parent, cid)
    if not h:
        return "<no control>"
    n = user32.GetWindowTextLengthW(h)
    buf = ctypes.create_unicode_buffer(n + 2)
    user32.GetWindowTextW(h, buf, n + 2)
    return buf.value


def set_text(parent, cid: int, text: str) -> None:
    h = dlg_item(parent, cid)
    user32.SetWindowTextW(h, text)
    # SetWindowText does not notify; the panel needs the EN_CHANGE to react
    user32.SendMessageW(parent, WM_COMMAND, (EN_CHANGE << 16) | (cid & 0xFFFF), h)


def click(parent, cid: int) -> None:
    """Press a button and make sure the panel sees BN_CLICKED.

    BM_CLICK is unreliable here: it fakes a mouse press, and a window that is not
    foreground gets WM_CANCELMODE in between, so the button never completes and
    no WM_COMMAND is sent. Sending BN_CLICKED ourselves is deterministic.
    """
    h = dlg_item(parent, cid)
    user32.SendMessageW(h, BM_CLICK, 0, 0)
    user32.SendMessageW(parent, WM_COMMAND, (BN_CLICKED << 16) | (cid & 0xFFFF), h)


def check_state(parent, cid: int) -> int:
    return user32.SendMessageW(dlg_item(parent, cid), 0x00F0, 0, 0)  # BM_GETCHECK


def set_check(parent, cid: int, on: bool) -> None:
    """Set a checkbox state and make sure the panel gets a notification.

    BS_AUTOCHECKBOX flips whatever state it is in, so BM_CLICK alone would toggle
    it the wrong way when it already matched the target. Force the state, then
    send BN_CLICKED explicitly.
    """
    h = dlg_item(parent, cid)
    user32.SendMessageW(h, BM_SETCHECK, 1 if on else 0, 0)
    user32.SendMessageW(parent, WM_COMMAND, (BN_CLICKED << 16) | (cid & 0xFFFF), h)


def check_state_now(parent, cid: int) -> int:
    return user32.SendMessageW(dlg_item(parent, cid), 0x00F0, 0, 0)  # BM_GETCHECK


def set_trackbar(parent, cid: int, pos: int) -> None:
    h = dlg_item(parent, cid)
    user32.SendMessageW(h, TBM_SETPOS, 1, pos)
    user32.SendMessageW(parent, WM_HSCROLL, 0, h)


def set_combo(parent, cid: int, text: str) -> None:
    h = dlg_item(parent, cid)
    idx = user32.SendMessageW(h, CB_FINDSTRINGEXACT, -1, text)
    if idx < 0:
        # not in the list: type it as if the user had
        user32.SetWindowTextW(h, text)
        user32.SendMessageW(parent, WM_COMMAND, (CBN_SELCHANGE << 16) | (cid & 0xFFFF), h)
        return
    user32.SendMessageW(h, CB_SETCURSEL, idx, 0)
    user32.SendMessageW(parent, WM_COMMAND, (CBN_SELCHANGE << 16) | (cid & 0xFFFF), h)


def grab():
    w = user32.GetSystemMetrics(0)
    h = user32.GetSystemMetrics(1)
    screen = user32.GetDC(None)
    mem = gdi32.CreateCompatibleDC(screen)
    bmp = gdi32.CreateCompatibleBitmap(screen, w, h)
    old = gdi32.SelectObject(mem, bmp)
    gdi32.BitBlt(mem, 0, 0, w, h, screen, 0, 0, SRCCOPY)

    class BIH(ctypes.Structure):
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

    bi = BIH()
    bi.biSize = ctypes.sizeof(BIH)
    bi.biWidth = w
    bi.biHeight = -h
    bi.biPlanes = 1
    bi.biBitCount = 32
    bi.biCompression = 0
    buf = (ctypes.c_char * (w * h * 4))()
    gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0)
    gdi32.SelectObject(mem, old)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(None, screen)
    return w, h, bytearray(buf.raw)


def diff_ratio(base, cur, w: int, h: int) -> float:
    """Share of sampled pixels whose grey value moved by more than a hair."""
    changed = 0
    total = 0
    for i in range(0, w * h * 4, 4 * 3):  # sample every 3rd pixel
        b0, g0, r0 = base[i], base[i + 1], base[i + 2]
        b1, g1, r1 = cur[i], cur[i + 1], cur[i + 2]
        total += 1
        if abs(r0 - r1) > 3 or abs(g0 - g1) > 3 or abs(b0 - b1) > 3:
            changed += 1
    return changed / max(total, 1)


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hdc", wt.HDC),
        ("fErase", wt.BOOL),
        ("rcPaint", wt.RECT),
        ("fRestore", wt.BOOL),
        ("fIncUpdate", wt.BOOL),
        ("rgbReserved", ctypes.c_byte * 32),
    ]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wt.UINT),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wt.HINSTANCE),
        ("hIcon", wt.HICON),
        ("hCursor", wt.HANDLE),
        ("hbrBackground", wt.HBRUSH),
        ("lpszMenuName", wt.LPCWSTR),
        ("lpszClassName", wt.LPCWSTR),
    ]


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.GetModuleHandleW.restype = wt.HMODULE
_kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]

_WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

# Without these the module handle comes back truncated to 32 bits and
# CreateWindowExW raises OverflowError.
user32.CreateWindowExW.restype = wt.HWND
user32.CreateWindowExW.argtypes = [
    wt.DWORD,
    wt.LPCWSTR,
    wt.LPCWSTR,
    wt.DWORD,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wt.HWND,
    wt.HMENU,
    wt.HINSTANCE,
    ctypes.c_void_p,
]
user32.RegisterClassW.restype = wt.ATOM
user32.RegisterClassW.argtypes = [ctypes.c_void_p]
# LPARAM can be a full 64-bit pointer here; without argtypes ctypes rejects it
user32.DefWindowProcW.restype = ctypes.c_longlong
user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, ctypes.c_ulonglong, ctypes.c_longlong]
user32.SetWindowPos.restype = wt.BOOL
user32.SetWindowPos.argtypes = [
    wt.HWND,
    wt.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wt.UINT,
]


class Backdrop:
    """A plain white full-screen window used as a clean canvas.

    Measuring on the live desktop is hopeless here: other agents keep repainting
    their windows, so the noise floor swamps the watermark. Painting white behind
    the (topmost) watermark removes every other source: what changes is only the
    grey text, and the numbers become comparable between runs.
    """

    CLS = "SwTestBackdrop"

    def __init__(self):
        self.hwnd = None
        self._proc = None
        self._brush = gdi32.CreateSolidBrush(0x00FFFFFF)  # white
        self._make_class()

    def _make_class(self):
        def wndproc(hwnd, msg, wp, lp):
            if msg == 0x000F:  # WM_PAINT
                ps = PAINTSTRUCT()
                hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
                rect = wt.RECT()
                user32.GetClientRect(hwnd, ctypes.byref(rect))
                user32.FillRect(hdc, ctypes.byref(rect), self._brush)
                user32.EndPaint(hwnd, ctypes.byref(ps))
                return 0
            if msg == 0x0014:  # WM_ERASEBKGND
                return 1
            return user32.DefWindowProcW(hwnd, msg, ctypes.c_ulonglong(wp), ctypes.c_longlong(lp))

        self._proc = _WNDPROC(wndproc)
        wc = WNDCLASSW()
        wc.lpfnWndProc = ctypes.cast(self._proc, ctypes.c_void_p)
        wc.hInstance = _kernel32.GetModuleHandleW(None)
        wc.lpszClassName = self.CLS
        wc.hbrBackground = self._brush
        user32.RegisterClassW(ctypes.byref(wc))

    def show(self):
        w = user32.GetSystemMetrics(0)
        h = user32.GetSystemMetrics(1)
        self.hwnd = user32.CreateWindowExW(
            0x00000008,  # WS_EX_TOPMOST
            self.CLS,
            "backdrop",
            0x80000000,  # WS_POPUP
            0,
            0,
            w,
            h,
            None,
            None,
            _kernel32.GetModuleHandleW(None),
            None,
        )
        user32.ShowWindow(self.hwnd, 5)  # SW_SHOW
        user32.UpdateWindow(self.hwnd)
        time.sleep(0.5)

    def hide(self):
        if self.hwnd:
            user32.DestroyWindow(self.hwnd)
            self.hwnd = None
            time.sleep(0.4)


def raise_overlay_above_backdrop() -> int:
    """Re-assert the watermark as the newest topmost window.

    Two topmost windows: the one activated last ends up on top. Creating the
    backdrop after the watermark would bury the watermark, so we push the overlay
    back up with SetWindowPos(HWND_TOPMOST) after every backdrop (re)show.
    """
    raised = 0

    def cb(hwnd, _lp):
        nonlocal raised
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        if buf.value == "ScreenWatermarkOverlayWnd":
            user32.SetWindowPos(hwnd, wt.HWND(-1), 0, 0, 0, 0, 0x0013)  # NOMOVE|NOSIZE|NOACTIVATE
            raised += 1
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    time.sleep(0.4)
    return raised


def region_grey_count(buf, w: int, h: int, bw: int = 900, bh: int = 900) -> int:
    """Count watermark-grey pixels in the top-left region.

    A whole-screen diff percentage is too diluted: the watermark only covers a
    fraction of the pixels, so every change looks like 0.1%. Counting grey pixels
    in one region is direct and easy to sanity-check by eye.
    """
    n = 0
    for y in range(0, min(bh, h)):
        row = y * w * 4
        for x in range(0, min(bw, w)):
            i = row + x * 4
            b, g, r = buf[i], buf[i + 1], buf[i + 2]
            if max(r, g, b) - min(r, g, b) <= 12 and 30 <= (r + g + b) // 3 <= 240:
                n += 1
    return n


def region_diff_ratio(a, b, w: int, h: int, bw: int = 900, bh: int = 900) -> float:
    """Share of pixels in the top-left region that differ between two shots."""
    changed = 0
    total = 0
    for y in range(0, min(bh, h)):
        row = y * w * 4
        for x in range(0, min(bw, w)):
            i = row + x * 4
            total += 1
            if (
                abs(a[i] - b[i]) > 4
                or abs(a[i + 1] - b[i + 1]) > 4
                or abs(a[i + 2] - b[i + 2]) > 4
            ):
                changed += 1
    return changed / max(total, 1)


def save_png(buf, w: int, h: int, path: str) -> None:
    from PIL import Image  # noqa: PLC0415

    img = Image.frombuffer("RGBA", (w, h), bytes(buf), "raw", "BGRA", 0, 1).convert("RGB")
    img.save(path)


def grab_stats(buf, w: int, h: int):
    """Quick histogram so we can tell 'all white' from 'watermark present'."""
    white = 0
    grey = 0
    total = 0
    for i in range(0, w * h * 4, 4 * 97):  # sparse sample
        b, g, r = buf[i], buf[i + 1], buf[i + 2]
        total += 1
        if r > 245 and g > 245 and b > 245:
            white += 1
        elif max(r, g, b) - min(r, g, b) <= 12 and 40 <= (r + g + b) // 3 <= 235:
            grey += 1
    return white / max(total, 1), grey / max(total, 1)


def overlay_state() -> str:
    """visible flag + z-order hint for the watermark windows."""
    out = []

    def cb(hwnd, _lp):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        if buf.value == "ScreenWatermarkOverlayWnd":
            out.append("visible" if user32.IsWindowVisible(hwnd) else "HIDDEN")
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return ",".join(out) if out else "missing"


def main() -> int:
    make_aware()
    here = os.path.dirname(os.path.abspath(__file__))
    cfgdir = os.path.join(here, "out", "percontrol.dir")
    os.makedirs(cfgdir, exist_ok=True)
    cfg = {
        "text": "PERCONTROL-BASE",
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
    # make sure the copy on disk is really what we just wrote before the app reads it
    with open(cfgpath, "r", encoding="utf-8") as f:
        assert json.load(f)["text"] == "PERCONTROL-BASE"

    exe = os.path.abspath(os.path.join(here, "..", "build", "ScreenWatermark.exe"))
    logpath = os.path.abspath(os.path.join(here, "..", "build", "debug.log"))
    if os.path.exists(logpath):
        os.remove(logpath)
    env = dict(os.environ)
    env["SW_DEBUG"] = "1"  # the app logs the config it loaded; startup check reads it
    proc = subprocess.Popen(
        [exe, "--config", cfgpath],
        stderr=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        env=env,
    )
    if not wait_for_startup(logpath, 'text="PERCONTROL-BASE"'):
        print("FAIL: app never logged the expected config; not testing")
        proc.kill()
        return 1
    print("app up, config confirmed in log")
    time.sleep(1.0)

    def panel():
        # re-query every time: the panel window can be recreated, and a stale
        # HWND silently swallows every message we send
        h = find_window("ScreenWatermarkSettingsWnd", 3.0)
        if not h:
            raise RuntimeError("settings panel window lost")
        return h

    if not user32.IsWindowVisible(panel()):
        user32.ShowWindow(panel(), 5)  # SW_SHOW
        time.sleep(1.0)

    # White backdrop under the topmost watermark: kills every noise source.
    backdrop = Backdrop()
    backdrop.show()
    print("raised %d overlay window(s) above the backdrop" % raise_overlay_above_backdrop())

    results = []
    w, h, base = grab()
    wf, gf = grab_stats(base, w, h)
    print("screen %dx%d  white=%.3f grey=%.4f" % (w, h, wf, gf))
    # Save a PNG right here: if the watermark is not in this shot, no number below
    # means anything (that is exactly how one earlier round got misread).
    save_png(base, w, h, os.path.join(here, "out", "percontrol-baseline.png"))
    if gf < 0.0005:
        print("FAIL: watermark not visible on the white backdrop; aborting before measuring")
        backdrop.hide()
        proc.kill()
        kill_stale()
        return 1

    def snap():
        """Screenshot that can only see the watermark.

        Z-order between two topmost windows was not stable (the backdrop kept
        winning after repaints), so instead of fighting it: hide the backdrop,
        grab, show it again. Then the overlay is the only topmost window around.
        """
        backdrop.hide()
        raise_overlay_above_backdrop()
        _, _, buf = grab()
        backdrop.show()
        raise_overlay_above_backdrop()
        return buf

    print("-- per-control apply test (live preview OFF, so only Apply can change it) --")
    set_check(panel(), 1016, False)  # IDC_LIVEPREVIEW = 1016
    time.sleep(0.8)
    if check_state_now(panel(), 1016) != 0:
        print("FAIL: live preview refuses to turn off; the test would be meaningless")
        proc.kill()
        return 1
    print("live preview confirmed OFF (checkbox=%d)" % check_state_now(panel(), 1016))

    # Noise floor: two grabs with nothing changed. Anything at or below this is
    # just repaint jitter, not the watermark reacting.
    shot_a = snap()
    time.sleep(0.8)
    shot_b = snap()
    noise = region_diff_ratio(shot_a, shot_b, w, h)
    print("noise floor (same state, two grabs) = %.2f%%" % (noise * 100.0))
    threshold = max(noise * 3.0, 0.005)
    print("threshold for 'changed' = %.2f%%" % (threshold * 100.0))
    base_grey = region_grey_count(base, w, h)
    print("baseline grey-pixel count = %d" % base_grey)

    def rebase():
        """Put every control back to the baseline values and re-shoot."""
        nonlocal base, base_grey
        p = panel()
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
        time.sleep(1.2)
        base = snap()
        base_grey = region_grey_count(base, w, h)

    def measure(name, action, note=""):
        """Rebase -> shoot A -> change one control -> Apply -> shoot B -> compare A,B.

        Comparing against a long-lived baseline was fragile (the overlay kept
        losing the topmost race to the backdrop). A and B are taken back-to-back
        in the same state except for the one control under test, so the comparison
        is self-contained and cannot be poisoned by anything that happened earlier.
        """
        rebase()
        a = snap()
        action(panel())
        time.sleep(0.6)
        click(panel(), ID_APPLY)
        time.sleep(1.2)
        b = snap()
        ratio = region_diff_ratio(a, b, w, h)
        ga = region_grey_count(a, w, h)
        gb = region_grey_count(b, w, h)
        results.append((name, ratio, "grey %d -> %d" % (ga, gb)))
        print(
            "  %-26s changed=%6.3f%%  grey %7d -> %7d  %s"
            % (name, ratio * 100.0, ga, gb, note)
        )
        return b

    measure("text", lambda p: set_text(p, ID_TEXT, "PERCONTROL-CHANGED-TEXT"))
    rebase()
    measure("font_size 30->64", lambda p: set_text(p, ID_FONTSIZE, "64"))
    rebase()
    measure("font_family YaHei->SimSun", lambda p: set_combo(p, ID_FONTFAMILY, "SimSun"))
    rebase()
    measure("opacity 35->90", lambda p: set_trackbar(p, ID_OPACITY, 90))
    rebase()
    measure("angle -30->25", lambda p: set_trackbar(p, ID_ANGLE, 25))
    rebase()
    measure("gap_x 150->500", lambda p: set_text(p, ID_GAPX, "500"))
    rebase()
    measure("gap_y 120->400", lambda p: set_text(p, ID_GAPY, "400"))
    rebase()
    measure("line_spacing 1.2->2.6", lambda p: set_text(p, ID_LINESPACING, "2.60"))
    rebase()
    measure("bold off->on", lambda p: set_check(p, ID_BOLD, True))
    rebase()
    measure("italic off->on", lambda p: set_check(p, ID_ITALIC, True))
    rebase()
    measure("phase_offset on->off", lambda p: set_check(p, ID_PHASE, False))

    print()
    print("=== summary (threshold %.2f%%) ===" % (threshold * 100.0))
    bad = []
    for name, ratio, note in results:
        flag = "OK  " if ratio > threshold else "FAIL"
        if ratio <= threshold:
            bad.append(name)
        print("%s %-26s %6.2f%%   (%s)" % (flag, name, ratio * 100.0, note))
    print()
    print("=== last applies the app logged (raw) ===")
    if os.path.exists(logpath):
        with open(logpath, "r", encoding="utf-8", errors="replace") as f:
            applies = [ln.strip() for ln in f if "Apply:" in ln]
        for ln in applies[-14:]:
            print("  " + ln)

    print()
    print("controls with no visible change: %s" % (", ".join(bad) if bad else "(none)"))

    backdrop.hide()
    proc.kill()
    kill_stale()
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
