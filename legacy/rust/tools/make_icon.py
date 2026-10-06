# -*- coding: utf-8 -*-
"""生成 res/app.ico：一块半透明底 + 斜排的水印字样。

为什么自己画：仓库里不想塞二进制美术资源，图标能复现比好看更重要。
需要 Pillow。用法： python tools/make_icon.py
"""
import os
from PIL import Image, ImageDraw, ImageFont

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "res", "app.ico")
SIZE = 256


def pick_font(px):
    """找一个能画出中文字的字体，找不到就退到 Pillow 自带位图字体。"""
    for name in ("msyhbd.ttc", "msyh.ttc", "simhei.ttf", "simsun.ttc"):
        path = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", name)
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, px)
            except Exception:
                pass
    return ImageFont.load_default()


def main():
    # 4 倍超采样再缩回来，省得边缘长毛刺。
    ss = 4
    n = SIZE * ss
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 圆角深色底：水印工具本身要低调，不能抢桌面视觉。
    pad = int(n * 0.03)
    radius = int(n * 0.22)
    d.rounded_rectangle([pad, pad, n - pad, n - pad], radius=radius, fill=(28, 32, 38, 255))
    # 一圈亮边，缩到 16px 时还能看出轮廓。
    d.rounded_rectangle([pad, pad, n - pad, n - pad], radius=radius,
                        outline=(120, 170, 210, 255), width=max(2, int(n * 0.022)))

    # 主体：斜排的“水印”二字，角度和默认配置的 -30 度呼应。
    font = pick_font(int(n * 0.34))
    layer = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    text = "水印"
    box = ld.textbbox((0, 0), text, font=font)
    tw, th = box[2] - box[0], box[3] - box[1]
    ld.text(((n - tw) / 2 - box[0], (n - th) / 2 - box[1]), text,
            font=font, fill=(235, 242, 248, 235))
    layer = layer.rotate(-30, resample=Image.BICUBIC, center=(n / 2, n / 2))
    img = Image.alpha_composite(img, layer)

    # 角落小锁点，暗示“防泄露”。
    d = ImageDraw.Draw(img)
    r = int(n * 0.035)
    cx, cy = int(n * 0.78), int(n * 0.22)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(96, 200, 150, 255))

    img = img.resize((SIZE, SIZE), Image.LANCZOS)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    img.save(OUT, format="ICO",
             sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote %s (%d bytes)" % (os.path.normpath(OUT), os.path.getsize(OUT)))


if __name__ == "__main__":
    main()
