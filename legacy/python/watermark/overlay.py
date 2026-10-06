"""每个显示器一个 tkinter Toplevel 水印窗。

窗口本身只是"一块画布 + 特殊的扩展样式"，重绘永远是删掉 Canvas item 再画，
不销毁重建窗口 —— 那样会闪、会丢 z 序、句柄也就没法给验收脚本核对。
"""

from __future__ import annotations

import os
import tkinter as tk
from dataclasses import dataclass

from . import config as cfgmod
from . import render, win32


@dataclass
class OverlayWindow:
    index: int
    monitor: win32.Monitor
    toplevel: tk.Toplevel
    canvas: tk.Canvas
    painter: render.WatermarkPainter
    hwnd: int
    key_color: str

    @property
    def width(self) -> int:
        return self.monitor.width

    @property
    def height(self) -> int:
        return self.monitor.height


class OverlaySet:
    """管理全部水印窗：创建、重绘、显隐、点击穿透切换。"""

    # 键色候选：从漂亮的深色里挑，万一和文字色撞了就换下一个（见 _pick_key_color）
    KEY_COLORS = ("#101010", "#0E0E12", "#0C1014", "#120E10", "#0A0E0A", "#101018")

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.windows: list[OverlayWindow] = []
        self._visible = True

    # -- 生命周期 ---------------------------------------------------------

    def rebuild(self, cfg: cfgmod.Config, monitors: list[win32.Monitor]) -> None:
        """显示器数量/布局变了才需要真的拆窗重建。"""
        if not cfg.all_monitors:
            monitors = [m for m in monitors if m.primary] or monitors[:1]
        old_count = len(self.windows)
        if old_count == len(monitors) and all(
            w.monitor == m for w, m in zip(self.windows, monitors)
        ):
            return
        self.destroy_all()
        for index, monitor in enumerate(monitors, start=1):
            self.windows.append(self._create_one(cfg, monitor, index))

    def _create_one(self, cfg: cfgmod.Config, monitor: win32.Monitor, index: int) -> OverlayWindow:
        key = self._pick_key_color(cfg)
        top = tk.Toplevel(self.root)
        top.withdraw()  # 先把样式都配好再显示，避免闪一下普通窗口
        top.overrideredirect(True)  # 无边框：没有标题栏，也不进任务栏
        top.title(f"ScreenWatermark 水印 {index}")
        top.geometry(f"{monitor.width}x{monitor.height}+{monitor.left}+{monitor.top}")

        canvas = tk.Canvas(
            top,
            width=monitor.width,
            height=monitor.height,
            highlightthickness=0,
            borderwidth=0,
            bg=key,
        )
        canvas.pack(fill="both", expand=True)
        top.update_idletasks()  # 必须让 Tk 真的建出 HWND，才能取句柄

        hwnd = self._hwnd(top, index)
        win32.make_overlay_window(hwnd, self._colorref(key), cfg.click_through, topmost=True)
        # 再压一次：Tk 可能在 attributes 里改过 z 序
        win32.raise_topmost(hwnd)
        return OverlayWindow(
            index=index,
            monitor=monitor,
            toplevel=top,
            canvas=canvas,
            painter=render.WatermarkPainter(canvas, key),
            hwnd=hwnd,
            key_color=key,
        )

    def _hwnd(self, top: tk.Toplevel, index: int) -> int:
        """拿真正的顶层句柄。

        Tk 的 winfo_id() 给的是解释器内部窗口（它是真正的顶层窗口的子窗口）。
        点击穿透的样式必须打在顶层窗口上：打在子窗口上，顶层照样截住鼠标。
        """
        try:
            inner = int(top.winfo_id())
        except tk.TclError as exc:
            raise RuntimeError(f"拿不到第 {index} 块水印窗的句柄") from exc
        hwnd = win32.top_level_hwnd(inner)
        if not hwnd:
            raise RuntimeError(f"第 {index} 块水印窗没有顶层句柄")
        return hwnd

    def _colorref(self, color: str) -> int:
        """COLORREF 是 0x00BBGGRR（蓝绿红反着来）。"""
        r = int(color[1:3], 16)
        g = int(color[3:5], 16)
        b = int(color[5:7], 16)
        return (b << 16) | (g << 8) | r

    def _pick_key_color(self, cfg: cfgmod.Config) -> str:
        """键色不能和文字色太近，否则半透明文字会被当成背景一起抠掉。"""
        target = cfg.color.upper()
        for candidate in self.KEY_COLORS:
            if _distance(candidate, target) > 60:
                return candidate
        return "#010101"

    def destroy_all(self) -> None:
        for win in self.windows:
            try:
                win.toplevel.destroy()
            except tk.TclError:
                pass
        self.windows = []

    # -- 渲染 -------------------------------------------------------------

    def repaint(self, cfg: cfgmod.Config, text: str) -> float:
        """按当前参数重画所有屏幕。返回最慢一块的耗时（毫秒）。"""
        slowest = 0.0
        items = 0
        for win in self.windows:
            win.painter.repaint(cfg, text, win.width, win.height)
            slowest = max(slowest, win.painter.last_ms)
            items += win.painter.last_items
        self.write_status(cfg, text, items, slowest)
        return slowest

    def write_status(self, cfg: cfgmod.Config, text: str, items: int, slowest_ms: float) -> None:
        """把最近一次重绘的结果写到 config 旁边的 run-status.json。

        为什么落盘：水印窗是键控透明的，从外面截屏数像素会被桌面噪声淹没，
        所以需要一个确定性的"我确实按这套参数重画了"凭据。出问题时它也是第一手线索。
        写失败静默忽略 —— 这只是诊断信息，绝不能因此影响水印。
        """
        if cfg.path is None:
            return
        self._repaint_seq = getattr(self, "_repaint_seq", 0) + 1
        payload = {
            "repaint_seq": self._repaint_seq,
            "monitors": len(self.windows),
            "items": items,
            "slowest_ms": round(slowest_ms, 1),
            "text": text,
            "text_chars": len(text),
            "angle": cfg.angle,
            "gap_x": cfg.gap_x,
            "gap_y": cfg.gap_y,
            "opacity": round(float(cfg.opacity), 3),
            "font_size": cfg.font_size,
            "color": cfg.color,
            "enabled": cfg.enabled,
            "visible": self._visible,
            "click_through": cfg.click_through,
            "all_monitors": cfg.all_monitors,
            "phase_offset": cfg.phase_offset,
        }
        try:
            import json

            target = cfg.path.with_name("run-status.json")
            tmp = target.with_name(target.name + ".tmp")
            with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
                # ensure_ascii=False：中文原样存，方便人直接看
                fh.write(json.dumps(payload, ensure_ascii=False))
            os.replace(tmp, target)
        except OSError:
            pass

    def apply_click_through(self, click_through: bool) -> None:
        for win in self.windows:
            win32.set_click_through(win.hwnd, click_through)

    def show(self, cfg: cfgmod.Config, text: str) -> None:
        for win in self.windows:
            win.toplevel.deiconify()
            win.toplevel.attributes("-topmost", True)
            win32.make_overlay_window(
                win.hwnd, self._colorref(win.key_color), cfg.click_through, topmost=True
            )
            win32.raise_topmost(win.hwnd)
            win.painter.repaint(cfg, text, win.width, win.height)
        self._visible = True
        # 显示路径也要落状态：hide() 不重绘，光靠重绘落盘会留下过期记录
        self.write_status(cfg, text, self.total_items(), max((w.painter.last_ms for w in self.windows), default=0.0))

    def hide(self, cfg: cfgmod.Config | None = None) -> None:
        for win in self.windows:
            win.painter.clear()
            win.toplevel.withdraw()
        self._visible = False
        if cfg is not None:
            self.write_status(cfg, "", 0, 0.0)

    @property
    def visible(self) -> bool:
        return self._visible

    def keep_on_top(self) -> None:
        """别人开全屏程序会把我们压下去，定时轻推一下（只改 z 序，不重画）。"""
        for win in self.windows:
            win32.raise_topmost(win.hwnd)

    def exstyles(self) -> list[tuple[str, int]]:
        """自检用：每块屏幕的标题和扩展样式位。"""
        return [(f"monitor{win.index}", win32.get_exstyle(win.hwnd)) for win in self.windows]

    def total_items(self) -> int:
        return sum(win.painter.last_items for win in self.windows)


def _distance(a: str, b: str) -> int:
    try:
        ar, ag, ab = int(a[1:3], 16), int(a[3:5], 16), int(a[5:7], 16)
        br, bg, bb = int(b[1:3], 16), int(b[3:5], 16), int(b[5:7], 16)
    except (ValueError, IndexError):
        return 255
    return max(abs(ar - br), abs(ag - bg), abs(ab - bb))
