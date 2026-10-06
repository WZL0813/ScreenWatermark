"""控制器：把配置、水印窗、托盘/快捷键、设置面板、定时器串起来。

线程约定（很重要）：
- 主线程只跑 tkinter，所有控件操作都在这里。
- 托盘/快捷键在另一个线程，它只往 queue 里塞命令字符串。
- 主线程每 50ms 轮询那个 queue，再动手改界面。
"""

from __future__ import annotations

import queue
import sys
import tkinter as tk
import traceback
from dataclasses import replace
from datetime import datetime

from . import config as cfgmod
from . import overlay, panel, tray, win32

# 轮询间隔：50ms 对人是"立刻"，对 CPU 可以忽略
POLL_MS = 50
# 顶 z 序的间隔。§6 的"定时顶一下"只改样式不重画，所以不违反"静置近 0% CPU"
KEEP_TOP_MS = 4000
# 外部脚本让运行中的实例重读配置用的私有消息号
RELOAD_MESSAGE = 0x8000 + 10


class App:
    def __init__(
        self,
        cfg: cfgmod.Config,
        *,
        use_tray: bool = True,
        start_hidden_panel: bool = True,
    ) -> None:
        self.cfg = cfg
        self.use_tray = use_tray

        self.root = tk.Tk()
        # 主窗口不显示：它只是 tkinter 的解释器宿主，真正见人的是水印窗和面板
        self.root.withdraw()
        self.root.title("ScreenWatermark")
        self.root.report_callback_exception = self._on_tk_error

        self.commands: "queue.Queue[str]" = queue.Queue()
        self.overlays = overlay.OverlaySet(self.root)
        self.panel: panel.SettingsPanel | None = None
        self.tray: tray.TrayThread | None = None

        self._cmd_poll_id: str | None = None
        self._keep_top_id: str | None = None
        self._refresh_id: str | None = None
        self._last_template_text: str = ""
        self._quitting = False

        self.monitors = win32.enum_monitors()
        self.overlays.rebuild(self.cfg, self.monitors)

        self.panel = panel.SettingsPanel(
            self.root,
            self.cfg,
            on_apply=self.apply_config,
            on_toggle_visible=self.toggle_watermark,
            on_save=self.save_config,
            on_reset=self.reset_config,
            on_autostart=self.apply_autostart,
            watermark_visible=self.cfg.enabled,
        )
        if start_hidden_panel:
            self.panel.hide()

        self.render_watermark(force=True)
        if self.cfg.enabled:
            self.overlays.show(self.cfg, self._text())
        else:
            self.overlays.hide(self.cfg)
        self.panel.set_watermark_visible(self.cfg.enabled)

        if self.use_tray:
            self.tray = tray.TrayThread(self.commands)
            if self.tray.start():
                self._sync_tray()
                self._sync_hotkey_hint()
            else:
                # §7：托盘起不来不能崩，快捷键和面板继续可用
                print("[app] 托盘不可用，请看托盘菜单或用面板操作", file=sys.stderr)

        self._cmd_poll_id = self.root.after(POLL_MS, self._poll_commands)
        self._keep_top_id = self.root.after(KEEP_TOP_MS, self._keep_on_top)
        self._schedule_refresh()
        self._install_reload_hook()

    def _sync_hotkey_hint(self) -> None:
        """把"实际生效的快捷键组合"写进设置面板底部的提示行（DESIGN.md §4）。

        降级发生时用户看到的必须是真组合，不然按 Ctrl+Alt+W 没反应会以为是 bug。
        """
        if self.panel is None or self.tray is None:
            return
        self.panel.set_hotkey_hint(self.tray.hotkey_summary())

    def _install_reload_hook(self) -> None:
        """给主窗口挂一个 WM_APP+10 → 重新载入配置的钩子。

        为什么需要它：脚本或外部工具想让"正在跑的那个实例"重读配置，除了托盘菜单和
        快捷键没有别的入口。tkinter 不暴露窗口过程，所以只能自己把 wndproc 换成
        "先看是不是我的消息，不是就转交给 Tk 原来的过程"。
        """
        try:
            import ctypes
            from ctypes import wintypes

            self._root_hwnd = win32.top_level_hwnd(int(self.root.winfo_id()))
            wndproc_type = ctypes.WINFUNCTYPE(
                ctypes.c_longlong, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
            )
            # 取出原过程：SetWindowLongPtrW 返回旧值，restype 要点成函数指针才能直接调用
            win32.user32.SetWindowLongPtrW.restype = wndproc_type
            original = win32.user32.SetWindowLongPtrW(
                wintypes.HWND(self._root_hwnd), win32.GWLP_WNDPROC, 0
            )
            win32.user32.SetWindowLongPtrW.restype = ctypes.c_longlong
            self._tk_wndproc = original
            self._own_wndproc = wndproc_type(self._reload_wndproc)
            win32.user32.SetWindowLongPtrW(
                wintypes.HWND(self._root_hwnd),
                win32.GWLP_WNDPROC,
                ctypes.cast(self._own_wndproc, ctypes.c_void_p).value,
            )
        except Exception as exc:  # 挂不上不影响正常使用，只是少了个自动化入口
            self._own_wndproc = None
            print(f"[app] 自动化重载入口不可用: {exc!r}", file=sys.stderr)

    def _reload_wndproc(self, hwnd, msg, wparam, lparam):  # noqa: ANN001
        import ctypes

        try:
            if msg == RELOAD_MESSAGE:
                # 消息可能来自任意线程，统一塞队列，由主线程的轮询去执行
                self.commands.put(tray.CMD_RELOAD)
                return 0
            return win32.user32.CallWindowProcW(
                ctypes.cast(self._tk_wndproc, ctypes.c_void_p), hwnd, msg, wparam, lparam
            )
        except Exception as exc:  # 窗口过程里抛异常会让消息静默丢失
            print(f"[app] wndproc 异常: {exc!r}", file=sys.stderr)
            return win32.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    # -- 主循环 -----------------------------------------------------------

    def run(self) -> int:
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            self.request_quit()
        return 0

    def _on_tk_error(self, exc_type, exc_value, exc_tb) -> None:  # noqa: ANN001
        """tkinter 回调里的异常默认只打印，这里加一层上下文方便定位。"""
        print("[app] tkinter 回调异常:", file=sys.stderr)
        traceback.print_exception(exc_type, exc_value, exc_tb, file=sys.stderr)

    # -- 命令轮询 ---------------------------------------------------------

    def _poll_commands(self) -> None:
        try:
            while True:
                command = self.commands.get_nowait()
                self._handle_command(command)
        except queue.Empty:
            pass
        except Exception as exc:  # 单条命令出错不能把轮询定时器弄没
            print(f"[app] 处理命令出错: {exc!r}", file=sys.stderr)
        if not self._quitting:
            self._cmd_poll_id = self.root.after(POLL_MS, self._poll_commands)

    def _handle_command(self, command: str) -> None:
        if command == tray.CMD_TOGGLE_WATERMARK:
            self.toggle_watermark()
        elif command in (tray.CMD_TOGGLE_PANEL, tray.CMD_SETTINGS):
            self.toggle_panel()
        elif command == tray.CMD_QUIT:
            self.request_quit()
        elif command == tray.CMD_RELOAD:
            self.reload_config()
        elif command == tray.CMD_TOGGLE_AUTOSTART:
            self.apply_autostart(not self.cfg.autostart)
            if self.panel is not None:
                self.panel.load_from(self.cfg)
        elif command == tray.CMD_SHOW:
            self.set_watermark(True)
        elif command == tray.CMD_HIDE:
            self.set_watermark(False)

    # -- 水印 -------------------------------------------------------------

    def _text(self) -> str:
        return cfgmod.expand_template(self.cfg.text, self.cfg)

    def render_watermark(self, *, force: bool = False) -> float:
        """重画（不重建窗口）。返回最慢一块屏的耗时毫秒数。"""
        text = self._text()
        if not force and text == self._last_template_text and self.cfg.enabled:
            return 0.0
        self._last_template_text = text
        slowest = self.overlays.repaint(self.cfg, text)
        return slowest

    def set_watermark(self, enabled: bool) -> None:
        self.cfg.enabled = bool(enabled)
        if self.cfg.enabled:
            self.render_watermark(force=True)
            self.overlays.show(self.cfg, self._text())
        else:
            self.overlays.hide(self.cfg)
        if self.panel is not None:
            self.panel.set_watermark_visible(self.cfg.enabled)
        self._sync_tray()

    def toggle_watermark(self) -> None:
        self.set_watermark(not self.cfg.enabled)

    def apply_config(self, new_cfg: cfgmod.Config) -> None:
        """面板/命令行改完参数后走这里：只重画，不重建窗口。"""
        old_monitors = self.cfg.all_monitors
        self.cfg = new_cfg
        if old_monitors != new_cfg.all_monitors or not self.overlays.windows:
            self.overlays.rebuild(self.cfg, self.monitors)
        self.overlays.apply_click_through(self.cfg.click_through)
        if self.cfg.enabled:
            self.render_watermark(force=True)
            self.overlays.show(self.cfg, self._text())
        else:
            self.overlays.hide(self.cfg)
        if self.panel is not None:
            self.panel.set_watermark_visible(self.cfg.enabled)
            # 让面板的回退基准跟上当前配置，否则非法输入的回退会用过期字段
            self.panel.set_base_config(self.cfg)
        self._schedule_refresh()
        self._sync_tray()

    def save_config(self) -> None:
        try:
            path = cfgmod.save(self.cfg)
            print(f"[app] 配置已保存: {path}", flush=True)
        except OSError as exc:
            print(f"[app] 保存配置失败: {exc}", file=sys.stderr)
            if self.panel is not None:
                self.panel.flash("保存失败，见控制台")

    def reload_config(self) -> None:
        """从磁盘重读。托盘菜单里的"重新载入配置"就指这个。"""
        try:
            fresh = cfgmod.load(self.cfg.path)
        except Exception as exc:
            print(f"[app] 载入配置失败: {exc!r}", file=sys.stderr)
            return
        if self.cfg.text_override:
            fresh = replace(fresh, text=self.cfg.text, text_override=True)
        self.apply_config(fresh)
        if self.panel is not None:
            self.panel.load_from(self.cfg)
            self.panel.flash("已重新载入配置")
        # load_from 只回填配置控件，快捷键提示行得单独刷一遍，别把降级后的组合覆盖掉
        self._sync_hotkey_hint()

    def reset_config(self) -> None:
        fresh = cfgmod.reset_to_defaults(self.cfg)
        self.apply_config(fresh)
        if self.panel is not None:
            self.panel.load_from(self.cfg)
            self.panel.flash("已恢复默认值")

    def apply_autostart(self, enabled: bool) -> None:
        ok = win32.set_autostart(enabled)
        self.cfg.autostart = bool(enabled) if ok else win32.get_autostart()
        if not ok:
            print("[app] 设置开机自启失败（注册表不可写？）", file=sys.stderr)
        self._sync_tray()

    # -- 定时器 -----------------------------------------------------------

    def _schedule_refresh(self) -> None:
        """只有模板里真的含时间变量才需要定时重画；否则静置时一个定时器都不留。"""
        if self._refresh_id is not None:
            try:
                self.root.after_cancel(self._refresh_id)
            except (tk.TclError, ValueError):
                pass
            self._refresh_id = None
        if self.cfg.template and cfgmod.has_time_variable(self.cfg):
            interval = max(5, int(self.cfg.refresh_seconds)) * 1000
            self._refresh_id = self.root.after(interval, self._on_refresh)

    def _on_refresh(self) -> None:
        self._refresh_id = None
        if self.cfg.enabled and cfgmod.has_time_variable(self.cfg):
            # 时间没跳到下一分钟就别白画一遍
            text = self._text()
            if text != self._last_template_text:
                self._last_template_text = text
                self.overlays.repaint(self.cfg, text)
        self._schedule_refresh()

    def _keep_on_top(self) -> None:
        if not self._quitting:
            self.overlays.keep_on_top()
            self._keep_top_id = self.root.after(KEEP_TOP_MS, self._keep_on_top)

    # -- 面板 -------------------------------------------------------------

    def toggle_panel(self) -> None:
        if self.panel is None:
            return
        self.panel.toggle(self.cfg)

    # -- 退出 -------------------------------------------------------------

    def _sync_tray(self) -> None:
        if self.tray is not None:
            self.tray.update_state(watermark_visible=self.cfg.enabled, autostart=self.cfg.autostart)

    def request_quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        for attr in ("_cmd_poll_id", "_keep_top_id", "_refresh_id"):
            job = getattr(self, attr)
            if job is not None:
                try:
                    self.root.after_cancel(job)
                except (tk.TclError, ValueError):
                    pass
                setattr(self, attr, None)
        if self.tray is not None:
            self.tray.stop()
        self.overlays.destroy_all()
        if self.panel is not None:
            self.panel.destroy()
        try:
            self.root.quit()
            self.root.destroy()
        except tk.TclError:
            pass


def diagnostic(cfg: cfgmod.Config) -> None:
    """--selftest：不开窗口，只把关键判断打出来，方便无桌面环境下排查。"""
    import tkinter.font as tkfont  # noqa: F401  仅用于确认模块可导入

    monitors = win32.enum_monitors()
    print(f"dpi={win32.primary_dpi()} monitors={len(monitors)}")
    for mon in monitors:
        print(f"  monitor primary={mon.primary} rect=({mon.left},{mon.top},{mon.right},{mon.bottom})")
    root = tk.Tk()
    root.withdraw()
    from . import render

    font = render.build_font(root, cfg)
    text = cfgmod.expand_template(cfg.text, cfg)
    summary = render.plan_summary(cfg, text, font, monitors[0].width, monitors[0].height)
    print(f"font={font.actual('family')} size={font.actual('size')} text={text!r}")
    print(f"plan: {summary}")
    print(f"color={cfg.color} opacity={cfg.opacity} key={overlay.OverlaySet.KEY_COLORS[0]}")
    root.destroy()
