# -*- coding: utf-8 -*-
"""验收脚本：统计截图里"灰色水印像素"的比例。

判据（和 C++/C# 版保持一致的思路）：
- 接近配置里的文字颜色（默认 #808080），差值阈值 24；
- 同时接近灰阶（R/G/B 三通道互相差不超过 12），排除彩色内容；
- 只统计"水印灰"，不统计纯黑纯白，避免把大片桌面背景算进来。

用法： python tools/analyze_shot.py <png> [--color 808080] [--tol 24] [--gray 12]
"""
import argparse
import os
import sys

from PIL import Image


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("png")
    ap.add_argument("--color", default="808080", help="水印文字颜色，RRGGBB")
    ap.add_argument("--tol", type=int, default=24, help="颜色接近阈值（每通道）")
    ap.add_argument("--gray", type=int, default=12, help="灰阶判定阈值")
    args = ap.parse_args()

    if not os.path.exists(args.png):
        print("FAIL 找不到文件 %s" % args.png)
        return 2

    hexs = args.color.lstrip("#")
    tr, tg, tb = (int(hexs[i:i + 2], 16) for i in (0, 2, 4))

    im = Image.open(args.png).convert("RGB")
    w, h = im.size
    px = im.load()
    tol, grayt = args.tol, args.gray

    hits = 0
    total = w * h
    # 逐行扫，纯 Python 在这个分辨率下几秒能跑完。
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            if (abs(r - tr) <= tol and abs(g - tg) <= tol and abs(b - tb) <= tol
                    and abs(r - g) <= grayt and abs(g - b) <= grayt):
                hits += 1

    ratio = hits / float(total)
    print("ANALYZE file=%s" % os.path.abspath(args.png))
    print("ANALYZE size=%dx%d total=%d target=#%02X%02X%02X tol=%d gray=%d"
          % (w, h, total, tr, tg, tb, tol, grayt))
    print("ANALYZE gray_watermark_pixels=%d ratio=%.6f percent=%.4f%%"
          % (hits, ratio, ratio * 100.0))
    print("ANALYZE verdict=%s" % ("PASS" if hits > 0 else "FAIL(zero gray pixels)"))
    return 0 if hits > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
