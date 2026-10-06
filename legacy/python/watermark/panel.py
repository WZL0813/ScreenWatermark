"""设置面板（DESIGN.md §5 的 14 项）。

面板只是"配置的编辑器"：改动先进 draft，再通过回调交给 App 去应用。
面板自己不认识水印窗，这样关掉面板不会影响水印。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import colorchooser, font as tkfont, ttk
from typing import Callable

from . import config as cfgmod
from . import render

WINDOW_TITLE = "ScreenWatermark 设置"

# §5 第 14 项：一行快捷键说明
HOTKEY_HINT = "快捷键：Ctrl+Alt+W 开关水印 · Ctrl+Alt+S 开关面板 · Ctrl+Alt+Q 退出"


class SettingsPanel:
    def __init__(
        self,
        master: tk.Misc,
        cfg: cfgmod.Config,
        *,
        on_apply: Callable[[cfgmod.Config], None],
        on_toggle_visible: Callable[[], None],
        on_save: Callable[[], None],
        on_reset: Callable[[], None],
        on_autostart: Callable[[bool], None],
        watermark_visible: bool = True,
    ) -> None:
        self.master = master
        self.on_apply = on_apply
        self.on_toggle_visible = on_toggle_visible
        self.on_save = on_save
        self.on_reset = on_reset
        self.on_autostart = on_autostart
        self.watermark_visible = watermark_visible

        self.win = tk.Toplevel(master)
        self.win.title(WINDOW_TITLE)
        self.win.resizable(False, False)
        # 关掉面板只是隐藏：§4 明确要求面板关闭后程序继续挂着
        self.win.protocol("WM_DELETE_WINDOW", self.hide)

        self.vars: dict[str, tk.Variable] = {}
        self.live = tk.BooleanVar(value=True)
        self._pending: str | None = None
        self._loading = False
        # 「应用」要基于最近一次已应用的配置做增量覆盖，否则面板会拿着过期字段去覆盖水印
        self._base: cfgmod.Config = cfg

        self._build(cfg)

    # -- 构建 -------------------------------------------------------------

    def _build(self, cfg: cfgmod.Config) -> None:
        outer = ttk.Frame(self.win, padding=12)
        outer.grid(sticky="nsew")
        outer.columnconfigure(1, weight=1)

        row = 0
        # 1 水印文本
        self.vars["text"] = tk.StringVar(value=cfg.text)
        row = self._entry(outer, row, "水印文本", "text", width=42)

        # 7 字体名
        self.vars["font_family"] = tk.StringVar(value=cfg.font_family)
        row = self._font_chooser(outer, row, cfg)

        # 2 字体大小
        self.vars["font_size"] = tk.IntVar(value=cfg.font_size)
        row = self._spin(outer, row, "字体大小", "font_size", 8, 400)

        # 3 不透明度（滑块 1..100，显示百分比）
        self.vars["opacity_pct"] = tk.IntVar(value=int(round(cfg.opacity * 100)))
        row = self._scale(outer, row, "不透明度", "opacity_pct", 1, 100, suffix="%")

        # 4 旋转角度
        self.vars["angle"] = tk.IntVar(value=cfg.angle)
        row = self._scale(outer, row, "旋转角度", "angle", -90, 90, suffix="°")

        # 5 水平/垂直间距
        self.vars["gap_x"] = tk.IntVar(value=cfg.gap_x)
        row = self._spin(outer, row, "水平间距", "gap_x", 0, 2000)
        self.vars["gap_y"] = tk.IntVar(value=cfg.gap_y)
        row = self._spin(outer, row, "垂直间距", "gap_y", 0, 2000)

        # 6 文字颜色
        self.vars["color"] = tk.StringVar(value=cfg.color)
        row = self._color_picker(outer, row)

        # 8 粗体 / 斜体
        self.vars["bold"] = tk.BooleanVar(value=cfg.bold)
        self.vars["italic"] = tk.BooleanVar(value=cfg.italic)
        style_row = ttk.Frame(outer)
        style_row.grid(row=row, column=1, sticky="w", pady=2)
        self._check(style_row, "粗体", "bold").pack(side="left")
        self._check(style_row, "斜体", "italic").pack(side="left", padx=(12, 0))
        ttk.Label(outer, text="字形").grid(row=row, column=0, sticky="w", padx=(0, 8), pady=2)
        row += 1

        # 9 模板变量 + 时间格式
        self.vars["template"] = tk.BooleanVar(value=cfg.template)
        self.vars["time_format"] = tk.StringVar(value=cfg.time_format)
        tpl_row = ttk.Frame(outer)
        tpl_row.grid(row=row, column=1, sticky="we", pady=2)
        self._check(tpl_row, "启用模板变量", "template").pack(side="left")
        ttk.Label(tpl_row, text="时间格式").pack(side="left", padx=(12, 4))
        ttk.Entry(tpl_row, textvariable=self.vars["time_format"], width=18).pack(side="left")
        ttk.Label(outer, text="模板").grid(row=row, column=0, sticky="w", padx=(0, 8), pady=2)
        row += 1

        # 行距倍数：§2 有这个字段，C++ 版要能读到，所以面板也得能改
        self.vars["line_spacing"] = tk.DoubleVar(value=cfg.line_spacing)
        row = self._scale_float(outer, row, "行距倍数", "line_spacing", 0.5, 3.0)

        # 刷新间隔
        self.vars["refresh_seconds"] = tk.IntVar(value=cfg.refresh_seconds)
        row = self._spin(outer, row, "刷新间隔(秒)", "refresh_seconds", 5, 3600)

        # 10 实时预览
        self._check(outer, "实时预览（改动立即重画）", "live", var=self.live, grid=(row, 0, 2))
        row += 1

        # 11 全部显示器 / 12 行错位 / 穿透 / 开机自启
        self.vars["all_monitors"] = tk.BooleanVar(value=cfg.all_monitors)
        self.vars["phase_offset"] = tk.BooleanVar(value=cfg.phase_offset)
        self.vars["click_through"] = tk.BooleanVar(value=cfg.click_through)
        self.vars["autostart"] = tk.BooleanVar(value=cfg.autostart)
        toggles = ttk.Frame(outer)
        toggles.grid(row=row, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self._check(toggles, "全部显示器", "all_monitors").pack(side="left")
        self._check(toggles, "行错位", "phase_offset").pack(side="left", padx=(12, 0))
        self._check(toggles, "鼠标穿透", "click_through").pack(side="left", padx=(12, 0))
        self._check(toggles, "开机自启", "autostart").pack(side="left", padx=(12, 0))
        row += 1

        # 13 按钮
        buttons = ttk.Frame(outer)
        buttons.grid(row=row, column=0, columnspan=2, sticky="we", pady=(12, 4))
        ttk.Button(buttons, text="应用", command=self.apply_now).pack(side="left")
        self.visibility_var = tk.StringVar(value=self._visibility_text())
        ttk.Button(buttons, textvariable=self.visibility_var, command=self.toggle_visible).pack(
            side="left", padx=6
        )
        ttk.Button(buttons, text="保存配置", command=self.save_now).pack(side="left", padx=6)
        ttk.Button(buttons, text="重置默认", command=self.reset_now).pack(side="left", padx=6)
        row += 1

        # 14 快捷键提示。内容等主程序把"实际生效的组合"告诉我之后再填（见 set_hotkey_hint）
        self.hotkey_label = ttk.Label(outer, text=HOTKEY_HINT, foreground="#555555")
        self.hotkey_label.grid(row=row, column=0, columnspan=2, sticky="w", pady=(8, 0))
        row += 1
        self.status = ttk.Label(outer, text="", foreground="#126b12")
        self.status.grid(row=row, column=0, columnspan=2, sticky="w")

        self.win.bind("<Escape>", lambda _e: self.hide())
        self._center()

    # -- 控件小工具 -------------------------------------------------------

    def _label(self, parent: tk.Misc, row: int, text: str) -> None:
        ttk.Label(parent, text=text).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=2)

    def _entry(self, parent: tk.Misc, row: int, text: str, key: str, width: int = 20) -> int:
        self._label(parent, row, text)
        entry = ttk.Entry(parent, textvariable=self.vars[key], width=width)
        entry.grid(row=row, column=1, sticky="we", pady=2)
        self._watch(key)
        return row + 1

    def _spin(self, parent: tk.Misc, row: int, text: str, key: str, lo: int, hi: int) -> int:
        self._label(parent, row, text)
        spin = ttk.Spinbox(
            parent, from_=lo, to=hi, textvariable=self.vars[key], width=8, command=lambda k=key: self._on_change(k)
        )
        spin.grid(row=row, column=1, sticky="w", pady=2)
        spin.bind("<KeyRelease>", lambda _e, k=key: self._on_change(k))
        spin.bind("<FocusOut>", lambda _e, k=key: self._on_change(k))
        return row + 1

    def _scale(
        self, parent: tk.Misc, row: int, text: str, key: str, lo: int, hi: int, suffix: str = ""
    ) -> int:
        self._label(parent, row, text)
        holder = ttk.Frame(parent)
        holder.grid(row=row, column=1, sticky="we", pady=2)
        holder.columnconfigure(0, weight=1)
        scale = ttk.Scale(
            holder,
            from_=lo,
            to=hi,
            orient="horizontal",
            length=240,
            command=lambda _v, k=key: self._on_change(k),
        )
        # ttk.Scale 是浮点的，用 IntVar 会显示成小数，所以另配一个只读数字
        scale.set(float(self.vars[key].get()))
        scale.grid(row=0, column=0, sticky="we")
        value_label = ttk.Label(holder, width=6)

        def sync(*_args, k=key, var=self.vars[key], lab=value_label) -> None:
            try:
                lab.configure(text=f"{int(var.get())}{suffix}")
            except (tk.TclError, ValueError):
                lab.configure(text="?")

        var = self.vars[key]
        var.trace_add("write", sync)
        sync()
        value_label.grid(row=0, column=1, sticky="w", padx=(6, 0))
        # Scale 的 command 拿不到"我要写到哪个变量"，这里补一次绑定
        scale.configure(command=lambda v, k=key, s=scale: self._on_scale(k, v, s))
        return row + 1

    def _scale_float(
        self, parent: tk.Misc, row: int, text: str, key: str, lo: float, hi: float
    ) -> int:
        self._label(parent, row, text)
        holder = ttk.Frame(parent)
        holder.grid(row=row, column=1, sticky="we", pady=2)
        scale = ttk.Scale(holder, from_=lo, to=hi, orient="horizontal", length=240)
        scale.set(float(self.vars[key].get()))
        scale.grid(row=0, column=0, sticky="we")
        label = ttk.Label(holder, width=6)
        label.grid(row=0, column=1, sticky="w", padx=(6, 0))

        def on_move(value: str, k: str = key, lab: ttk.Label = label) -> None:
            rounded = round(float(value), 2)
            self.vars[k].set(rounded)  # 写回变量后再统一走 _on_change
            lab.configure(text=f"{rounded:.2f}")

        scale.configure(command=on_move)
        label.configure(text=f"{float(self.vars[key].get()):.2f}")
        return row + 1

    def _on_scale(self, key: str, value: str, scale: ttk.Scale) -> None:
        """ttk.Scale 给的是字符串浮点，写回整型变量再触发预览。"""
        try:
            int_value = int(round(float(value)))
        except (TypeError, ValueError):
            return
        if int_value != self.vars[key].get():
            self.vars[key].set(int_value)
        self._on_change(key)

    def _check(
        self,
        parent: tk.Misc,
        text: str,
        key: str | None = None,
        var: tk.Variable | None = None,
        grid: tuple[int, int, int] | None = None,
    ) -> ttk.Checkbutton:
        target = var if var is not None else self.vars[key]
        check = ttk.Checkbutton(parent, text=text, variable=target)
        if grid is not None:
            check.grid(row=grid[0], column=grid[1], columnspan=grid[2], sticky="w", pady=2)
        if key is not None:
            self._watch(key)
        elif var is not None:
            var.trace_add("write", lambda *_a: self._on_change("live"))
        return check

    def _color_picker(self, parent: tk.Misc, row: int) -> int:
        self._label(parent, row, "文字颜色")
        holder = ttk.Frame(parent)
        holder.grid(row=row, column=1, sticky="w", pady=2)
        swatch = tk.Label(holder, width=4, relief="solid", borderwidth=1, bg=self.vars["color"].get())
        swatch.pack(side="left")
        ttk.Button(holder, text="选择…", command=self._pick_color).pack(side="left", padx=6)
        self.color_entry = ttk.Entry(holder, textvariable=self.vars["color"], width=10)
        self.color_entry.pack(side="left")
        self.vars["color"].trace_add("write", lambda *_a: self._sync_swatch())
        self.swatch = swatch
        self._watch("color")
        return row + 1

    def _sync_swatch(self) -> None:
        value = self.vars["color"].get()
        if len(value) == 7 and value.startswith("#"):
            try:
                self.swatch.configure(bg=value)
            except tk.TclError:
                pass

    def _font_chooser(self, parent: tk.Misc, row: int, cfg: cfgmod.Config) -> int:
        self._label(parent, row, "字体名")
        holder = ttk.Frame(parent)
        holder.grid(row=row, column=1, sticky="we", pady=2)
        holder.columnconfigure(0, weight=1)
        families = self._families()
        combo = ttk.Combobox(holder, textvariable=self.vars["font_family"], values=families, width=32)
        combo.grid(row=0, column=0, sticky="we")
        # 只读下拉会限制自由输入；这里允许键入，选不存在的字体在 render 层会回退
        combo.bind("<<ComboboxSelected>>", lambda _e: self._on_change("font_family"))
        combo.bind("<KeyRelease>", lambda _e: self._on_change("font_family"))
        ttk.Label(holder, text=f"（本机实测可用：{render.resolve_family(set(families), cfg.font_family)}）").grid(
            row=0, column=1, sticky="w", padx=(6, 0)
        )
        return row + 1

    @staticmethod
    def _families() -> list[str]:
        """@ 开头的是竖排字体，选它文字会竖过来，列表里直接不显示。"""
        try:
            names = list(tkfont.families())
        except tk.TclError:
            return []
        return sorted({n for n in names if not n.startswith("@")})

    def _pick_color(self) -> None:
        current = self.vars["color"].get()
        chosen = colorchooser.askcolor(color=current, title="选择水印文字颜色", parent=self.win)
        if chosen and chosen[1]:
            self.vars["color"].set(str(chosen[1]).upper())

    def _watch(self, key: str) -> None:
        """任何控件变化都进这里，再由 _on_change 决定要不要立刻重画。"""
        if key in self.vars:
            self.vars[key].trace_add("write", lambda *_a, k=key: self._on_change(k))

    # -- 行为 -------------------------------------------------------------

    def _on_change(self, key: str) -> None:
        if self._loading:
            return
        if key == "autostart":
            # 自启是立即生效的副作用，不进实时预览队列
            self.on_autostart(bool(self.vars["autostart"].get()))
            return
        if not self.live.get():
            return
        # 连续拖动滑块会产生大量事件，攒 60ms 再重画，免得把主线程堵住
        if self._pending is not None:
            try:
                self.win.after_cancel(self._pending)
            except (tk.TclError, ValueError):
                pass
        self._pending = self.win.after(60, self._fire_preview)

    def _fire_preview(self) -> None:
        self._pending = None
        self.on_apply(self.collect())

    def collect(self) -> cfgmod.Config:
        """把控件值收成一份 Config。数值非法时退回当前 cfg 的对应字段，不炸。"""
        base = self._base_cfg()
        values = {name: getattr(base, name) for name in cfgmod._DEFAULTS}

        def safe_int(key: str, fallback: int) -> int:
            try:
                return int(float(self.vars[key].get()))
            except (tk.TclError, ValueError, TypeError):
                return fallback

        def safe_float(key: str, fallback: float) -> float:
            try:
                return float(self.vars[key].get())
            except (tk.TclError, ValueError, TypeError):
                return fallback

        values["text"] = self.vars["text"].get()
        values["font_family"] = self.vars["font_family"].get().strip() or base.font_family
        values["font_size"] = safe_int("font_size", base.font_size)
        values["bold"] = bool(self.vars["bold"].get())
        values["italic"] = bool(self.vars["italic"].get())
        values["color"] = self.vars["color"].get().strip().upper()
        values["opacity"] = safe_int("opacity_pct", int(base.opacity * 100)) / 100.0
        values["angle"] = safe_int("angle", base.angle)
        values["gap_x"] = safe_int("gap_x", base.gap_x)
        values["gap_y"] = safe_int("gap_y", base.gap_y)
        values["line_spacing"] = safe_float("line_spacing", base.line_spacing)
        values["enabled"] = base.enabled
        values["click_through"] = bool(self.vars["click_through"].get())
        values["template"] = bool(self.vars["template"].get())
        values["time_format"] = self.vars["time_format"].get() or base.time_format
        values["refresh_seconds"] = safe_int("refresh_seconds", base.refresh_seconds)
        values["all_monitors"] = bool(self.vars["all_monitors"].get())
        values["phase_offset"] = bool(self.vars["phase_offset"].get())
        values["autostart"] = bool(self.vars["autostart"].get())

        raw = cfgmod.to_mapping(base)
        raw.update(values)
        new_cfg = cfgmod.from_mapping(raw, base.path)
        new_cfg.unknown = dict(base.unknown)
        new_cfg.text_override = base.text_override
        return new_cfg

    def _base_cfg(self) -> cfgmod.Config:
        return self._base

    def load_from(self, cfg: cfgmod.Config) -> None:
        """外部改了配置（比如快捷键切换、重新载入配置）后回填控件，不触发预览。"""
        self._base = cfg
        self._loading = True
        try:
            self.vars["text"].set(cfg.text)
            self.vars["font_family"].set(cfg.font_family)
            self.vars["font_size"].set(cfg.font_size)
            self.vars["bold"].set(cfg.bold)
            self.vars["italic"].set(cfg.italic)
            self.vars["color"].set(cfg.color)
            self.vars["opacity_pct"].set(int(round(cfg.opacity * 100)))
            self.vars["angle"].set(cfg.angle)
            self.vars["gap_x"].set(cfg.gap_x)
            self.vars["gap_y"].set(cfg.gap_y)
            self.vars["line_spacing"].set(round(cfg.line_spacing, 2))
            self.vars["template"].set(cfg.template)
            self.vars["time_format"].set(cfg.time_format)
            self.vars["refresh_seconds"].set(cfg.refresh_seconds)
            self.vars["all_monitors"].set(cfg.all_monitors)
            self.vars["phase_offset"].set(cfg.phase_offset)
            self.vars["click_through"].set(cfg.click_through)
            self.vars["autostart"].set(cfg.autostart)
            self.visibility_var.set(self._visibility_text())
        finally:
            self._loading = False

    def _visibility_text(self) -> str:
        return "隐藏水印" if self.watermark_visible else "显示水印"

    def set_watermark_visible(self, visible: bool) -> None:
        self.watermark_visible = visible
        try:
            self.visibility_var.set(self._visibility_text())
        except tk.TclError:
            pass

    def set_base_config(self, cfg: cfgmod.Config) -> None:
        """同步"回退基准"，但不动控件里的值。

        应用成功后调用：这样用户把某个数字框填成非法内容时，回退的是刚生效的参数，
        而不是上次 load_from 时的旧值。
        """
        self._base = cfg

    def set_hotkey_hint(self, text: str) -> None:
        """显示实际生效的快捷键组合。

        首选组合被别的程序占用时程序会自动降级，这里必须显示降级后的真实组合，
        否则用户按 Ctrl+Alt+W 没反应，还以为是程序坏了。
        """
        if not text:
            return
        try:
            self.hotkey_label.configure(text=text)
        except tk.TclError:
            pass

    def apply_now(self) -> None:
        self.on_apply(self.collect())
        self.flash("已应用")

    def save_now(self) -> None:
        self.on_save()
        self.flash("已保存配置")

    def reset_now(self) -> None:
        self.on_reset()

    def toggle_visible(self) -> None:
        self.on_toggle_visible()

    def flash(self, message: str) -> None:
        try:
            self.status.configure(text=message)
            self.win.after(2000, lambda: self.status.configure(text=""))
        except tk.TclError:
            pass

    # -- 显隐 -------------------------------------------------------------

    def _center(self) -> None:
        self.win.update_idletasks()
        width = max(520, self.win.winfo_reqwidth())
        height = self.win.winfo_reqheight()
        screen_w = self.win.winfo_screenwidth()
        screen_h = self.win.winfo_screenheight()
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 3)
        self.win.geometry(f"+{x}+{y}")

    def show(self, cfg: cfgmod.Config | None = None) -> None:
        if cfg is not None:
            self.load_from(cfg)
        self.win.deiconify()
        self.win.attributes("-topmost", True)
        self.win.lift()
        self.win.focus_force()

    def hide(self) -> None:
        self.win.withdraw()

    def toggle(self, cfg: cfgmod.Config | None = None) -> None:
        if self.win.winfo_viewable():
            self.hide()
        else:
            self.show(cfg)

    @property
    def visible(self) -> bool:
        try:
            return bool(self.win.winfo_viewable())
        except tk.TclError:
            return False

    def destroy(self) -> None:
        try:
            self.win.destroy()
        except tk.TclError:
            pass
