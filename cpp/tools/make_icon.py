#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成 res/app.ico。

为什么用脚本而不是直接塞二进制：图标想改颜色/字号时能重跑，不用求人重新画。
依赖只有 Pillow（本机已装）：
    python tools/make_icon.py
输出覆盖 res/app.ico，多尺寸打包（16/24/32/48/64/128/256），任务栏和小图标都不糊。
"""

import os

from PIL import Image, ImageDraw, ImageFont

# 尺寸从大到小画：先画 256 再缩，抗锯齿靠 resize 的 LANCZOS
SIZES = [256, 128, 64, 48, 32, 24, 16]
# 圆角深灰底 + 白色字，跟水印本身的灰调子统一
BG_TOP = (58, 62, 70)
BG_BOTTOM = (34, 37, 42)
FG = (240, 242, 245)
ACCENT = (255, 176, 72)  # 右下角一点暖色，免得整个图标死气沉沉


def rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return mask


def pick_font(size: int) -> ImageFont.FreeTypeFont:
    # 优先微软雅黑，取不到退回黑体，再取不到就用 Pillow 内置位图字体
    for name in ("msyhbd.ttc", "msyh.ttc", "simhei.ttf", "arialbd.ttf"):
        path = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", name)
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def make_master() -> Image.Image:
    S = 256
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # 竖向渐变底：纯平色在任务栏里看着像一块砖
    grad = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(grad)
    for y in range(S):
        t = y / (S - 1)
        gd.line(
            [(0, y), (S, y)],
            fill=(
                int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t),
                int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t),
                int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t),
                255,
            ),
        )
    img.paste(grad, (0, 0), rounded_mask(S, 56))

    # 右下角暖色小圆点，做点层次
    dot = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(dot).ellipse([S - 86, S - 86, S - 26, S - 26], fill=ACCENT + (210,))
    img = Image.alpha_composite(img, dot)

    # 中间放一个字：水（中文一望即知这是什么工具）
    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    font = pick_font(150)
    text = "水"
    box = d.textbbox((0, 0), text, font=font)
    d.text(
        ((S - (box[2] - box[0])) / 2 - box[0], (S - (box[3] - box[1])) / 2 - box[1] - 6),
        text,
        font=font,
        fill=FG + (255,),
    )
    return Image.alpha_composite(img, layer)


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.join(os.path.dirname(here), "res")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "app.ico")

    master = make_master()
    # 逐个尺寸 resize 再打包，比让 Pillow 自己缩更可控
    master.save(out, format="ICO", sizes=[(s, s) for s in SIZES])
    print("已生成 %s（%d 个尺寸：%s）" % (out, len(SIZES), ", ".join(str(s) for s in SIZES)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
