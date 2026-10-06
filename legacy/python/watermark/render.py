"""平铺参数计算与 Canvas 绘制。

这里只管"画哪儿、画什么"，不碰窗口句柄 —— 窗口在 overlay.py。
关键约定（要和 C++ 版对齐，见 DESIGN.md §6）：
- cell_w = 文字宽 + gap_x，cell_h = 行高 * line_spacing + gap_y
- 起点故意放在 -cell_w / -cell_h，四边各多铺一圈，旋转后不留白边
- 正角度 = 逆时针。Tk 的 create_text(angle=) 角度就是逆时针为正，直接传即可。
"""

from __future__ import annotations

import math
import time
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass

from . import config as cfgmod

# 单元数上限。极端参数（字号 8 + 间距 0）下不设上限会把界面冻住几秒
MAX_CELLS = 20000
# 超过这个数就主动稀疏，并提示用户参数太密
SPARSIFY_THRESHOLD = 3000
# 单次重绘的目标时间，超了打警告（§6 要求 < 200ms）
TARGET_REDRAW_MS = 200.0

# Windows 上常见的等宽/黑体回退顺序，挨个试到有为止
FALLBACK_FAMILIES = (
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "SimHei",
    "SimSun",
    "Segoe UI",
)


@dataclass
class Cell:
    """一个水印单元。x/y 是"未旋转的左上角"，绘制时绕这个点逆时针转。"""

    x: float
    y: float


@dataclass
class TilePlan:
    cell_w: float
    cell_h: float
    cols: int
    rows: int
    step_col: int
    step_row: int
    phase_offset: bool

    @property
    def step_x(self) -> float:
        return self.cell_w * self.step_col

    @property
    def step_y(self) -> float:
        return self.cell_h * self.step_row

    @property
    def estimate(self) -> int:
        """真正会创建出来的单元数，用于验证 20000 上限。"""
        half = self.cell_w / 2.0
        total = 0
        for row in range(self.rows):
            base = -self.cell_w
            if self.phase_offset and row % 2 == 1:
                base += half
            total += self.cols
        return total

    def iter_cells(self):
        """按行序生成单元位置。故意用生成器：20000 个 Cell 对象没必要同时存在。"""
        half = self.cell_w / 2.0
        for row in range(self.rows):
            y = -self.cell_h + row * self.step_y
            base = -self.cell_w
            if self.phase_offset and row % 2 == 1:
                base += half
            for col in range(self.cols):
                yield Cell(base + col * self.step_x, y)


def _pick_step(cell_w: float, cell_h: float, width: int, height: int, phase_offset: bool) -> int:
    """算出最小稀疏倍数，使单元数落在 SPARSIFY_THRESHOLD 以内。

    行列用同一个倍数是为了保住图案的规则感；只稀一行或一列会变成条纹，很难看。
    """
    for step in range(1, 64):
        cols = int(width / (cell_w * step)) + 4
        rows = int(height / (cell_h * step)) + 4
        if cols * rows <= SPARSIFY_THRESHOLD:
            return step
    return 64


def compute_plan(
    text_width: float,
    line_height: float,
    cfg: cfgmod.Config,
    width: int,
    height: int,
) -> TilePlan:
    cell_w = max(8.0, float(text_width) + float(cfg.gap_x))
    cell_h = max(8.0, float(line_height) * float(cfg.line_spacing) + float(cfg.gap_y))
    width = max(1, int(width))
    height = max(1, int(height))
    step = _pick_step(cell_w, cell_h, width, height, cfg.phase_offset)
    cols = int(width / (cell_w * step)) + 4
    rows = int(height / (cell_h * step)) + 4
    return TilePlan(
        cell_w=cell_w,
        cell_h=cell_h,
        cols=cols,
        rows=rows,
        step_col=step,
        step_row=step,
        phase_offset=bool(cfg.phase_offset),
    )


def resolve_family(available: set[str], requested: str) -> str:
    """找一个真的存在的字体名。Tk 找不到字体会静默换字体，不报错，所以只能自己查。"""
    def exists(name: str) -> bool:
        # "@SimSun" 是竖排变体，选它文字会转 90 度，必须排除
        return bool(name) and not name.startswith("@") and name in available

    if exists(requested):
        return requested
    for name in FALLBACK_FAMILIES:
        if exists(name):
            return name
    return "TkDefaultFont"


def build_font(root: tk.Misc, cfg: cfgmod.Config) -> tkfont.Font:
    """按配置造字体对象。font_size 按 §2 是"磅"，Tk 的 size 正数即磅，交给 Tk 换算 DPI。"""
    available = set(root.tk.call("font", "families"))
    family = resolve_family(available, cfg.font_family)
    return tkfont.Font(
        root=root,
        family=family,
        size=int(cfg.font_size),
        weight="bold" if cfg.bold else "normal",
        # Tk 的斜体取值是 roman/italic，没有 "normal" 这个说法
        slant="italic" if cfg.italic else "roman",
    )


def measure_text(font: tkfont.Font, text: str) -> tuple[float, float]:
    """返回 (文字宽, 单行行高)。多行取最宽一行；行高统一按第一行算。"""
    lines = text.split("\n") if text else [""]
    width = max((font.measure(line) for line in lines), default=0)
    metrics = font.metrics()
    ascent = int(metrics.get("ascent", 0) or 0)
    descent = int(metrics.get("descent", 0) or 0)
    line_height = ascent + descent
    if line_height <= 0:
        line_height = int(font.measure("Hg") or 1)
    return float(width), float(line_height)


def blend_on_key(color: str, opacity: float, key: str) -> str:
    """把不透明度烘焙进文字颜色：在纯色（键色）背景上，等效于 alpha 混合的结果。

    为什么不直接把 alpha 写进 #RRGGBBAA：Tk 的 -transparentcolor 键控是逐像素精确匹配，
    半透明边缘像素的颜色和键色不同，于是会留下一圈毛边。
    """
    try:
        cr, cg, cb = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
        kr, kg, kb = int(key[1:3], 16), int(key[3:5], 16), int(key[5:7], 16)
    except (ValueError, IndexError):
        return color
    ratio = max(0.0, min(1.0, float(opacity)))
    r = int(round(cr * ratio + kr * (1.0 - ratio)))
    g = int(round(cg * ratio + kg * (1.0 - ratio)))
    b = int(round(cb * ratio + kb * (1.0 - ratio)))
    return f"#{r:02X}{g:02X}{b:02X}"


def rotate_offset(dx: float, dy: float, angle_deg: float) -> tuple[float, float]:
    """把未旋转坐标系里的偏移转到旋转后的屏幕坐标系。

    数学上 (x,y) 顺时针转 a 是 (x*cos + y*sin, -x*sin + y*cos)（屏幕 y 轴朝下）。
    我们要的是"绕单元原点逆时针转 a"，所以代入 -a 即可。
    """
    a = math.radians(float(angle_deg))
    cos_a = math.cos(a)
    sin_a = math.sin(a)
    return (dx * cos_a + dy * sin_a, -dx * sin_a + dy * cos_a)


class WatermarkPainter:
    """往一块 Canvas 上画水印。配置变了就 repaint()，绝不动窗口本身。"""

    def __init__(self, canvas: tk.Canvas, key_color: str) -> None:
        self.canvas = canvas
        self.key_color = key_color
        self.last_ms: float = 0.0
        self.last_items: int = 0
        self.last_plan: TilePlan | None = None
        self.sparsified = False

    def clear(self) -> None:
        self.canvas.delete("wm")

    def repaint(self, cfg: cfgmod.Config, text: str, width: int, height: int) -> None:
        started = time.perf_counter()
        self.clear()
        self.last_items = 0
        self.last_plan = None
        self.sparsified = False
        if not cfg.enabled or not text or width <= 0 or height <= 0:
            self.last_ms = (time.perf_counter() - started) * 1000.0
            return

        font = build_font(self.canvas, cfg)
        text_width, line_height = measure_text(font, text)
        plan = compute_plan(text_width, line_height, cfg, width, height)
        self.last_plan = plan
        self.sparsified = plan.step_col > 1 or plan.step_row > 1

        fill = blend_on_key(cfg.color, cfg.opacity, self.key_color)
        angle = float(cfg.angle)
        created = 0
        create_text = self.canvas.create_text
        for cell in plan.iter_cells():
            # 每个单元：先平移到单元原点，再绕原点旋转 angle，最后左对齐画字。
            # Tk 用 anchor="w" + angle 时就是绕这个锚点转，正好契合 §6 的约定。
            # 注意 Canvas 的 create_text 没有 spacing1/2/3（那是 Text 组件的选项），
            # 多行行距只能靠 cell_h 里的 line_spacing 反映在单元高度上。
            create_text(
                cell.x,
                cell.y,
                text=text,
                font=font,
                fill=fill,
                angle=angle,
                anchor="w",
                justify="left",
                tags="wm",
            )
            created += 1
        self.last_items = created
        self.last_ms = (time.perf_counter() - started) * 1000.0
        self._publish_stats(cfg, plan)
        if self.last_ms > TARGET_REDRAW_MS * 5:
            # 只在远超预算时吵闹：正常 30~80ms 属预期
            print(
                f"[render] 重绘 {self.last_ms:.0f}ms / {self.last_items} 单元，参数过密",
                flush=True,
            )

    def _publish_stats(self, cfg: cfgmod.Config, plan: TilePlan) -> None:
        """把最近一次重绘的结果写进 Tcl 变量 swm_stats。

        为什么要有这个：水印窗是键控透明的，从外面截屏数像素会被桌面噪声淹没，
        根本证明不了"到底画了多少"。留一个只读变量，外部脚本（tcl send / 测试）
        就能确定性地看到渲染结果。没有解释器时静默跳过。
        """
        try:
            canvas = self.canvas
            canvas.tk.call(
                "set",
                "swm_stats",
                f"items {self.last_items} ms {self.last_ms:.1f} "
                f"cell_w {plan.cell_w:.0f} cell_h {plan.cell_h:.0f} "
                f"cols {plan.cols} rows {plan.rows} step {plan.step_col} "
                f"angle {cfg.angle} gap_x {cfg.gap_x} gap_y {cfg.gap_y} "
                f"opacity {cfg.opacity:.2f} font_size {cfg.font_size}",
            )
        except (tk.TclError, AttributeError, ValueError):
            pass


def plan_summary(cfg: cfgmod.Config, text: str, font: tkfont.Font, width: int, height: int) -> str:
    """给日志/自检用的一行摘要。"""
    text_width, line_height = measure_text(font, text)
    plan = compute_plan(text_width, line_height, cfg, width, height)
    return (
        f"cell={plan.cell_w:.0f}x{plan.cell_h:.0f} cols={plan.cols} rows={plan.rows} "
        f"step={plan.step_col} cells={plan.estimate}"
    )
