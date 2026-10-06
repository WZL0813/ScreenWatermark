"""生成 res/app.ico —— 托盘和 EXE 图标。

为什么要自己画：这个仓库不引入任何二进制素材来源，图标必须是可复现的。
跑一次把 ico 落进 res/，之后 build.bat 用 /win32icon: 挂上去。

用法：
    python tools/make_icon.py
"""
import os
from PIL import Image, ImageDraw, ImageFont

# 多尺寸是给 Windows 用的：任务栏要 16/32，Alt+Tab 和资源管理器大图标要 256。
SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]

# 深蓝底 + 浅灰字，和默认水印色 (#808080) 是一个色系，色调不打架。
BG_TOP = (28, 52, 92)
BG_BOTTOM = (14, 26, 48)
FG = (214, 222, 235)
FG_DIM = (140, 156, 180)


def _font(size):
    """挑一个能画出中文/字母的粗体字。找不到就退回 Pillow 内置位图字体。"""
    for name in ("msyhbd.ttc", "msyh.ttc", "segoeuib.ttf", "arialbd.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render(size):
    """画一张：深色圆角方块 + 斜排的 W。

    斜排的 W 是故意的 —— 呼应水印本身的倾斜角度，一眼能认出这是哪个程序。
    """
    scale = 8  # 先按 8 倍画再缩小，边缘才不会有锯齿（Pillow 的 draw 没有抗锯齿）。
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 竖向渐变底：纯平色在小尺寸下看着很"贴纸"，加一点渐变就有厚度。
    grad = Image.new("RGBA", (s, s))
    gd = ImageDraw.Draw(grad)
    for y in range(s):
        t = y / max(1, s - 1)
        c = tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3))
        gd.line([(0, y), (s, y)], fill=c + (255,))

    # 圆角遮罩
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=255)
    img.paste(grad, (0, 0), mask)

    # 斜排的 W。先单独画到透明层再旋转，直接 rotate 整张会把圆角也转了。
    layer = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    f = _font(int(s * 0.62))
    text = "W"
    box = ld.textbbox((0, 0), text, font=f)
    tw, th = box[2] - box[0], box[3] - box[1]
    ld.text(((s - tw) / 2 - box[0], (s - th) / 2 - box[1]), text, font=f, fill=FG)
    layer = layer.rotate(30, resample=Image.BICUBIC, center=(s / 2, s / 2))

    img = Image.alpha_composite(img, layer)
    img = img.resize((size, size), Image.LANCZOS)
    return img


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.join(os.path.dirname(here), "res")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "app.ico")

    frames = [render(n) for n in SIZES]
    # 用最大一张当主图，sizes= 让 Pillow 把全部尺寸都塞进一个 ico。
    frames[-1].save(out, format="ICO", sizes=[(n, n) for n in SIZES])
    print("wrote %s (%d bytes)" % (out, os.path.getsize(out)))
    for n in SIZES:
        print("  size %3d ok" % n)


if __name__ == "__main__":
    main()
