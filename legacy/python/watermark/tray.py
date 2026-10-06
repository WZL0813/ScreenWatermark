"""纯 ctypes 的托盘图标 + 全局快捷键。

为什么单独起线程：Shell_NotifyIcon 的鼠标消息只会投递给创建它的那个窗口，
而那个窗口所在的线程必须自己跑 GetMessageW 循环。tkinter 的 mainloop 不能被抢，
所以这里开一个独立线程，两个循环通过 queue.Queue 交换命令。
规矩：这个线程里绝对不许碰 tkinter 控件。
"""

from __future__ import annotations

import ctypes
import queue
import sys
import threading
from ctypes import wintypes

from . import win32
from .win32 import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_NOREPEAT,
    MOD_SHIFT,
    NIF_ICON,
    NIF_MESSAGE,
    NIF_TIP,
    NIM_ADD,
    NIM_DELETE,
    NIM_MODIFY,
    NOTIFYICONDATAW,
    TPM_RETURNCMD,
    TPM_RIGHTBUTTON,
    WM_DESTROY,
    WM_HOTKEY,
    WM_TRAYICON,
    WNDCLASSW,
    WNDPROC,
)

# 命令名与 DESIGN.md §4 的操作一一对应，主线程按字符串分发
CMD_TOGGLE_WATERMARK = "toggle_watermark"
CMD_TOGGLE_PANEL = "toggle_panel"
CMD_QUIT = "quit"
CMD_RELOAD = "reload_config"
CMD_TOGGLE_AUTOSTART = "toggle_autostart"
CMD_SHOW = "show_watermark"
CMD_HIDE = "hide_watermark"
CMD_SETTINGS = "show_settings"

# 菜单项 id 从 1000 开始，和别的 id 不冲突
_MENU_SHOW = 1001
_MENU_HIDE = 1002
_MENU_IDS = {
    _MENU_SHOW: CMD_SHOW,
    _MENU_HIDE: CMD_HIDE,
    1003: CMD_SETTINGS,
    1004: CMD_RELOAD,
    1005: CMD_TOGGLE_AUTOSTART,
    1006: CMD_QUIT,
}

# 全局快捷键：id 从 2000 开始。
# 每条 = (命令, 首选组合, 降级组合, 首选显示名, 降级显示名)。
# 为什么要降级（DESIGN.md §4）：Ctrl+Alt+W/Q 在很多机器上早被别的常驻软件占了
# （本机实测 RegisterHotKey 返回 1409，把所有本程序进程杀掉后依然如此），
# 不退一级的话"开关水印"和"退出"在这类机器上直接没有。
_HOTKEY_ACTIONS = (
    (
        2001,
        CMD_TOGGLE_WATERMARK,
        MOD_CONTROL | MOD_ALT | MOD_NOREPEAT,
        0x57,  # W
        MOD_CONTROL | MOD_ALT | MOD_SHIFT | MOD_NOREPEAT,
        "Ctrl+Alt+W",
        "Ctrl+Alt+Shift+W",
    ),
    (
        2002,
        CMD_TOGGLE_PANEL,
        MOD_CONTROL | MOD_ALT | MOD_NOREPEAT,
        0x53,  # S
        None,  # S 没有降级：它不是被抢的重灾区
        "Ctrl+Alt+S",
        "Ctrl+Alt+Shift+S",
    ),
    (
        2003,
        CMD_QUIT,
        MOD_CONTROL | MOD_ALT | MOD_NOREPEAT,
        0x51,  # Q
        MOD_CONTROL | MOD_ALT | MOD_SHIFT | MOD_NOREPEAT,
        "Ctrl+Alt+Q",
        "Ctrl+Alt+Shift+Q",
    ),
)

# 窗口过程按 id 反查命令，注册时用同一张表
HOTKEY_IDS = {row[0]: (row[2], row[3], row[1]) for row in _HOTKEY_ACTIONS}

_CLASS_NAME = "ScreenWatermarkTrayWnd"
_TIP_PREFIX = "ScreenWatermark"

# hwnd -> _TrayContext。用字典而不是 GWLP_USERDATA，省掉指针来回转换的坑。
_contexts: dict[int, "_TrayContext"] = {}
_contexts_lock = threading.Lock()


class _TrayContext:
    """一个托盘窗口的状态，给窗口过程用。"""

    def __init__(self, commands: "queue.Queue[str]") -> None:
        self.commands = commands
        self.hwnd = 0
        self.hicon = 0
        self.tip = f"{_TIP_PREFIX} · 已启用"
        self.autostart = False
        self.watermark_visible = True
        self.class_atom = 0
        self.icon_added = False


def _register_window_class(wndproc) -> int:  # noqa: ANN001
    """注册一个后台窗口类。名字固定，重复注册会失败但不影响功能。"""
    hinstance = win32.kernel32.GetModuleHandleW(None)
    wc = WNDCLASSW()
    wc.style = win32.CS_HREDRAW | win32.CS_VREDRAW
    wc.lpfnWndProc = wndproc
    wc.cbClsExtra = 0
    wc.cbWndExtra = 0
    wc.hInstance = hinstance
    wc.hIcon = 0
    wc.hCursor = 0
    wc.hbrBackground = 0
    wc.lpszMenuName = None
    wc.lpszClassName = _CLASS_NAME
    atom = win32.user32.RegisterClassW(ctypes.byref(wc))
    if not atom:
        err = ctypes.get_last_error()
        if err != 1410:  # ERROR_CLASS_ALREADY_EXISTS：之前的托盘线程还没退干净
            print(f"[tray] RegisterClassW 失败 code={err}", file=sys.stderr)
    return int(atom)


def _wnd_proc(hwnd, msg, wparam, lparam):  # noqa: ANN001
    ctx = _contexts.get(int(hwnd))
    if ctx is None:
        return win32.user32.DefWindowProcW(hwnd, msg, wparam, lparam)
    try:
        if msg == WM_TRAYICON:
            event = int(lparam) & 0xFFFF
            if event == win32.WM_LBUTTONDBLCLK:
                ctx.commands.put(CMD_TOGGLE_PANEL)
            elif event in (win32.WM_RBUTTONUP, win32.WM_CONTEXTMENU):
                _show_menu(ctx)
            return 0
        if msg == WM_HOTKEY:
            entry = HOTKEY_IDS.get(int(wparam))
            if entry:
                ctx.commands.put(entry[2])
            return 0
        if msg == win32.WM_CLOSE:
            ctx.commands.put(CMD_QUIT)
            _shutdown(ctx)
            return 0
        if msg == WM_DESTROY:
            win32.user32.PostQuitMessage(0)
            return 0
    except Exception as exc:  # 窗口过程里抛异常会静默吞掉消息，必须自己兜住
        print(f"[tray] 窗口过程异常: {exc!r}", file=sys.stderr)
    return win32.user32.DefWindowProcW(hwnd, msg, wparam, lparam)


def _show_menu(ctx: _TrayContext) -> None:
    """右键菜单。TrackPopupMenu 前必须 SetForegroundWindow，否则菜单点外面不消失。"""
    menu = win32.user32.CreatePopupMenu()
    if not menu:
        return
    try:
        append = win32.user32.AppendMenuW
        if ctx.watermark_visible:
            append(menu, win32.MF_STRING, _MENU_HIDE, "隐藏水印")
        else:
            append(menu, win32.MF_STRING, _MENU_SHOW, "显示水印")
        append(menu, win32.MF_STRING, 1003, "设置…")
        append(menu, win32.MF_SEPARATOR, 0, None)
        append(menu, win32.MF_STRING, 1004, "重新载入配置")
        autostart_flag = win32.MF_CHECKED if ctx.autostart else win32.MF_UNCHECKED
        append(menu, win32.MF_STRING | autostart_flag, 1005, "开机自启")
        append(menu, win32.MF_SEPARATOR, 0, None)
        append(menu, win32.MF_STRING, 1006, "退出")

        pt = win32.POINT()
        win32.user32.GetCursorPos(ctypes.byref(pt))
        win32.user32.SetForegroundWindow(wintypes.HWND(ctx.hwnd))
        # TPM_RETURNCMD：直接把选中的 id 作为返回值给我，省掉 WM_COMMAND 那一趟
        chosen = win32.user32.TrackPopupMenu(
            menu, TPM_RIGHTBUTTON | TPM_RETURNCMD, pt.x, pt.y, 0, wintypes.HWND(ctx.hwnd), None
        )
        command = _MENU_IDS.get(int(chosen)) if chosen else None
        if command:
            ctx.commands.put(command)
    finally:
        win32.user32.DestroyMenu(menu)


def _make_icon() -> int:
    """先用系统默认图标把功能跑通；换 logo 是后续的事。"""
    icon = win32.user32.LoadIconW(None, wintypes.LPCWSTR(win32.IDI_APPLICATION))
    return int(icon) if icon else 0


def _fill_nid(ctx: _TrayContext, flags: int) -> NOTIFYICONDATAW:
    nid = NOTIFYICONDATAW()
    nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
    nid.hWnd = wintypes.HWND(ctx.hwnd)
    nid.uID = 1
    nid.uFlags = flags
    nid.uCallbackMessage = WM_TRAYICON
    nid.hIcon = wintypes.HICON(ctx.hicon)
    nid.szTip = ctx.tip[:127]
    # 故意不调 NIM_SETVERSION：保持经典回调格式，lparam 就是鼠标消息号，最好懂也最稳
    return nid


def _shutdown(ctx: _TrayContext) -> None:
    if ctx.icon_added:
        nid = _fill_nid(ctx, 0)
        win32.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
        ctx.icon_added = False
    win32.user32.PostQuitMessage(0)


class TrayThread:
    """托盘 + 快捷键线程的对外接口。"""

    def __init__(self, commands: "queue.Queue[str]") -> None:
        self.commands = commands
        self._thread: threading.Thread | None = None
        self._ctx: _TrayContext | None = None
        self._wndproc = WNDPROC(_wnd_proc)  # 必须留住引用，否则回调被回收会崩
        self._ready = threading.Event()
        self.started = False
        # 命令 -> 实际生效的组合名，例如 {"toggle_watermark": "Ctrl+Alt+Shift+W"}
        self.active_hotkeys: dict[str, str] = {}

    # -- 线程内 -----------------------------------------------------------

    def _run(self) -> None:
        ctx = _TrayContext(self.commands)
        self._ctx = ctx
        ctx.class_atom = _register_window_class(self._wndproc)
        hinstance = win32.kernel32.GetModuleHandleW(None)
        # 消息窗口：不可见、不显示，只用来收 Shell_NotifyIcon 和 WM_HOTKEY
        hwnd = win32.user32.CreateWindowExW(
            0,
            _CLASS_NAME,
            "ScreenWatermark tray",
            0,
            0,
            0,
            0,
            0,
            None,
            None,
            hinstance,
            None,
        )
        if not hwnd:
            print(f"[tray] CreateWindowExW 失败 code={ctypes.get_last_error()}", file=sys.stderr)
            self._ready.set()
            return
        ctx.hwnd = int(hwnd)
        with _contexts_lock:
            _contexts[ctx.hwnd] = ctx

        ctx.hicon = _make_icon()
        nid = _fill_nid(ctx, NIF_MESSAGE | NIF_ICON | NIF_TIP)
        if win32.shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)):
            ctx.icon_added = True
        else:
            # §7：托盘挂了也要能跑，快捷键和面板还留着
            print(
                f"[tray] 托盘图标注册失败 code={ctypes.get_last_error()}，改用快捷键控制",
                file=sys.stderr,
            )

        self._register_hotkeys()
        # active_hotkeys 在 _ready 之前就填好：主线程 start() 返回后立刻读它，
        # 不能有"还没写完"的中间态
        self.started = True
        self._ready.set()

        msg = wintypes.MSG()
        try:
            while win32.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                win32.user32.TranslateMessage(ctypes.byref(msg))
                win32.user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as exc:
            print(f"[tray] 消息循环异常: {exc!r}", file=sys.stderr)
        finally:
            self._unregister_hotkeys()
            with _contexts_lock:
                _contexts.pop(ctx.hwnd, None)
            if ctx.icon_added:
                nid = _fill_nid(ctx, 0)
                win32.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
                ctx.icon_added = False
            self.started = False

    def _try_register(self, hwnd: int, hotkey_id: int, mods: int, vk: int) -> tuple[bool, int]:
        ctypes.set_last_error(0)  # 否则 last_error 是上一次调用的陈旧值
        ok = bool(win32.user32.RegisterHotKey(wintypes.HWND(hwnd), hotkey_id, mods, vk))
        return ok, ctypes.get_last_error()

    def _register_hotkeys(self) -> None:
        """先注册首选组合，失败就退一级（DESIGN.md §4）。

        降级也失败只打日志：快捷键是便利功能，不能因此挡住程序启动。
        """
        ctx = self._ctx
        if ctx is None:
            return
        for row in _HOTKEY_ACTIONS:
            hotkey_id, command, mods, vk, fallback_mods, primary_name, fallback_name = row
            ok, err = self._try_register(ctx.hwnd, hotkey_id, mods, vk)
            if ok:
                self.active_hotkeys[command] = primary_name
                print(f"[hotkey] {primary_name} -> {command}", flush=True)
                continue

            if fallback_mods is None:
                print(
                    f"[hotkey] {primary_name} 注册失败 code={err}（被别的程序占了），"
                    f"这个功能只能用托盘菜单",
                    file=sys.stderr,
                )
                continue

            ok2, err2 = self._try_register(ctx.hwnd, hotkey_id, fallback_mods, vk)
            if ok2:
                self.active_hotkeys[command] = fallback_name
                # 这是"降级生效"的关键日志：用户按 Ctrl+Alt+W 没反应时，能在这里找到原因
                print(
                    f"[hotkey] {primary_name} 被占用(code={err})，已降级为 {fallback_name} -> {command}",
                    flush=True,
                )
            else:
                print(
                    f"[hotkey] {primary_name} 和降级组合 {fallback_name} 都注册失败 "
                    f"code={err}/{err2}，这个功能只能用托盘菜单",
                    file=sys.stderr,
                )

    def _unregister_hotkeys(self) -> None:
        ctx = self._ctx
        if ctx is None:
            return
        for hotkey_id in HOTKEY_IDS:
            win32.user32.UnregisterHotKey(wintypes.HWND(ctx.hwnd), hotkey_id)
        self.active_hotkeys.clear()

    def hotkey_summary(self) -> str:
        """给设置面板底部提示行用的一行文字，只列真正生效的组合。"""
        if not self.active_hotkeys:
            return "快捷键：不可用（都被别的程序占用了），请用托盘菜单"
        ordered = [
            (CMD_TOGGLE_WATERMARK, "开关水印"),
            (CMD_TOGGLE_PANEL, "开关面板"),
            (CMD_QUIT, "退出"),
        ]
        parts = [f"{self.active_hotkeys[c]} {label}" for c, label in ordered if c in self.active_hotkeys]
        return "快捷键：" + " · ".join(parts)

    # -- 主线程 -----------------------------------------------------------

    def start(self, timeout: float = 2.0) -> bool:
        self._thread = threading.Thread(target=self._run, name="swm-tray", daemon=True)
        self._thread.start()
        self._ready.wait(timeout)
        return self.started

    def update_state(self, *, watermark_visible: bool, autostart: bool) -> None:
        """同步菜单勾选状态和气泡文字。纯粹是跨线程写两个 Python 字段，无需加锁。"""
        ctx = self._ctx
        if ctx is None:
            return
        ctx.watermark_visible = watermark_visible
        ctx.autostart = autostart
        ctx.tip = f"{_TIP_PREFIX} · {'已启用' if watermark_visible else '已隐藏'}"
        if ctx.icon_added and ctx.hwnd:
            nid = _fill_nid(ctx, NIF_TIP)
            win32.shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def stop(self) -> None:
        """让托盘线程自己收尾（删图标 + 退消息循环），主线程只负责叫它一声。"""
        ctx = self._ctx
        if ctx is not None and ctx.hwnd:
            win32.user32.PostMessageW(wintypes.HWND(ctx.hwnd), win32.WM_CLOSE, 0, 0)
        if self._thread is not None:
            self._thread.join(timeout=1.5)
            self._thread = None
