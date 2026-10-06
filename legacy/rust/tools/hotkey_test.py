# -*- coding: utf-8 -*-
"""验收辅助：用真实按键序列触发全局热键，并枚举目标进程的水印窗口。

为什么要它：Ctrl+Alt+W 这类系统级热键，只有真的敲键盘（或合成按键）才能验证
"注册上了"和"按下去有反应"是两回事。枚举窗口时按"属于目标 pid + 类名"筛，
避免把别的实现的窗口算进来。

组合可以配：本机 Ctrl+Alt+W/Q 常被别的常驻软件占用，程序会降级到
Ctrl+Alt+Shift+W/Q，所以实际要按哪个得先看 `--probe` 的 hint 或日志里
`快捷键：...` 那一行。默认值就是本机降级后的组合。

用法：
    python tools/hotkey_test.py <pid>
    python tools/hotkey_test.py <pid> --toggle "Ctrl+Alt+Shift+W" --panel "Ctrl+Alt+S"
"""
import argparse
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

u32 = ctypes.WinDLL("user32", use_last_error=True)

EnumWindows = u32.EnumWindows
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
GetClassNameW = u32.GetClassNameW
IsWindowVisible = u32.IsWindowVisible
GetWindowRect = u32.GetWindowRect
GetWindowThreadProcessId = u32.GetWindowThreadProcessId
keybd_event = u32.keybd_event
GetWindowLongW = u32.GetWindowLongW

KEYEVENTF_KEYUP = 0x0002
GWL_EXSTYLE = -20

WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOPMOST = 0x00000008

REQUIRED = {
    "WS_EX_LAYERED(0x80000)": WS_EX_LAYERED,
    "WS_EX_TRANSPARENT(0x20)": WS_EX_TRANSPARENT,
    "WS_EX_TOOLWINDOW(0x80)": WS_EX_TOOLWINDOW,
    "WS_EX_NOACTIVATE(0x8000000)": WS_EX_NOACTIVATE,
    "WS_EX_TOPMOST(0x8)": WS_EX_TOPMOST,
}

VK = {"ctrl": 0x11, "alt": 0x12, "shift": 0x10}
LETTERS = {"W": 0x57, "S": 0x53, "Q": 0x51}

# 回调必须留活引用：ctypes 委托一旦被回收，EnumWindows 就什么都找不到。
_KEEP = []


def _find_top(pid, cls):
    out = []

    def cb(hwnd, _):
        wpid = wintypes.DWORD()
        GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value != pid:
            return True
        buf = ctypes.create_unicode_buffer(256)
        GetClassNameW(hwnd, buf, 256)
        if buf.value == cls:
            out.append(hwnd)
        return True

    ref = EnumWindowsProc(cb)
    _KEEP.append(ref)
    EnumWindows(ref, 0)
    return out


def overlays(pid):
    found = []
    for hwnd in _find_top(pid, "ScreenWatermarkOverlay"):
        r = wintypes.RECT()
        GetWindowRect(hwnd, ctypes.byref(r))
        found.append({
            "hwnd": hwnd,
            "visible": bool(IsWindowVisible(hwnd)),
            "rect": (r.left, r.top, r.right - r.left, r.bottom - r.top),
            "exstyle": GetWindowLongW(hwnd, GWL_EXSTYLE) & 0xFFFFFFFF,
        })
    return found


def parse_combo(text):
    """'Ctrl+Alt+Shift+W' -> [VK_CONTROL, VK_MENU, VK_SHIFT, 0x57]"""
    vks = []
    for part in text.split("+"):
        p = part.strip().lower()
        if p in VK:
            vks.append(VK[p])
        elif part.strip().upper() in LETTERS:
            vks.append(LETTERS[part.strip().upper()])
        else:
            raise ValueError("认不出的按键：%s" % part)
    if not vks:
        raise ValueError("空组合")
    return vks


def press(vks):
    """按下修饰键 -> 敲主键 -> 反序松开。留间隔，避免系统当成"长按重复"。"""
    for v in vks[:-1]:
        keybd_event(v, 0, 0, 0)
        time.sleep(0.02)
    keybd_event(vks[-1], 0, 0, 0)
    time.sleep(0.04)
    keybd_event(vks[-1], 0, KEYEVENTF_KEYUP, 0)
    for v in reversed(vks[:-1]):
        keybd_event(v, 0, KEYEVENTF_KEYUP, 0)
        time.sleep(0.02)
    time.sleep(0.5)


def show(tag, lst):
    if not lst:
        print("%-16s (没有 overlay 窗口)" % tag)
        return
    for w in lst:
        print("%-16s hwnd=0x%X visible=%-5s rect=%dx%d+%d+%d exstyle=0x%X"
              % (tag, w["hwnd"], w["visible"], w["rect"][2], w["rect"][3],
                 w["rect"][0], w["rect"][1], w["exstyle"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pid", type=int, nargs="?", default=0,
                    help="目标进程 pid；用 --start 自动拉起时可省略")
    ap.add_argument("--start", default="",
                    help="自己拉起这个 exe 再测（缩短被对端清场打断的时间窗）")
    ap.add_argument("--toggle", default="Ctrl+Alt+Shift+W",
                    help="实际生效的显示/隐藏组合（看 --probe 的 hint 行）")
    ap.add_argument("--panel", default="Ctrl+Alt+S")
    ap.add_argument("--quit", dest="quit_combo", default="",
                    help="留空则不做退出测试")
    args = ap.parse_args()

    proc = None
    if args.start:
        proc = subprocess.Popen([args.start, "--log"])
        pid = proc.pid
        time.sleep(2.5)
        if proc.poll() is not None:
            print("FAIL 启动后立刻退出，exit=%s" % proc.returncode)
            return 1
    else:
        pid = args.pid
        if not pid:
            print("usage: hotkey_test.py <pid> | --start <exe>")
            return 2

    print("实际生效组合：toggle=%s panel=%s" % (args.toggle, args.panel))
    print()
    lst = overlays(pid)
    show("BEFORE", lst)
    if not lst:
        print("FAIL 目标进程没有 overlay 窗口")
        return 1

    ex = lst[0]["exstyle"]
    print("exstyle=0x%X" % ex)
    ok = True
    for name, bit in REQUIRED.items():
        hit = (ex & bit) == bit
        ok = ok and hit
        print("  %-28s %s" % (name, "OK" if hit else "MISSING"))
    print()

    if args.toggle:
        print("-- 发送 %s --" % args.toggle)
        press(parse_combo(args.toggle))
        lst2 = overlays(pid)
        show("AFTER toggle", lst2)
        if lst2:
            print("  可见性 %s -> %s" % (lst[0]["visible"], lst2[0]["visible"]))
            print("  再按一次恢复显示")
            press(parse_combo(args.toggle))
            show("AFTER again", overlays(pid))
    print()

    if args.panel:
        print("-- 发送 %s 开关面板 --" % args.panel)
        before = _find_top(pid, "ScreenWatermarkSettingsPanel")
        press(parse_combo(args.panel))
        after = _find_top(pid, "ScreenWatermarkSettingsPanel")
        print("  面板窗口：发送前 %d 个，发送后 %d 个，visible=%s"
              % (len(before), len(after), [bool(IsWindowVisible(h)) for h in after]))
    print()

    if args.quit_combo:
        print("-- 发送 %s 退出 --" % args.quit_combo)
        press(parse_combo(args.quit_combo))
        time.sleep(1.0)
        still = overlays(pid)
        print("  退出后 overlay 窗口：%d 个（0 = 进程已退）" % len(still))

    if proc is not None:
        print()
        print("进程存活（本轮结束前）: %s" % (proc.poll() is None))
        proc.kill()
        proc.wait()
        print("测试进程已清理")

    print("verdict=%s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
