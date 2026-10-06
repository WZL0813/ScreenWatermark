#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""校验截图里确实有水印像素（给 CI / 手工验收用）。

为什么单独写一个：光看“文件存在”不够，全黑或者纯桌面也可能生成文件。
这里直接统计水印灰（#808080 按 15% 不透明度压到桌面后的偏灰像素）占比。
用法：
    python tools/check_shot.py docs/shots/cpp-verify.png
"""

import sys

from PIL import Image


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "docs/shots/cpp-verify.png"
    img = Image.open(path).convert("RGB")
    w, h = img.size
    px = img.load()

    total = w * h
    nonblack = 0
    grayish = 0
    # 水印是低不透明度的中性灰：R/G/B 三通道互相接近，且整体亮度落在中间带
    for y in range(0, h, 2):  # 隔行采样，够用且快
        for x in range(0, w, 2):
            r, g, b = px[x, y]
            if r or g or b:
                nonblack += 1
            mx, mn = max(r, g, b), min(r, g, b)
            if mx - mn <= 12 and 24 <= (r + g + b) // 3 <= 235:
                grayish += 1

    sampled = ((w + 1) // 2) * ((h + 1) // 2)
    print("图像: %s  %dx%d  采样像素 %d" % (path, w, h, sampled))
    print("非黑像素比例: %.4f (%d)" % (nonblack / sampled, nonblack))
    print("中性灰像素比例: %.4f (%d)" % (grayish / sampled, grayish))

    ok = nonblack / sampled > 0.05 and grayish / sampled > 0.002
    print("结论:", "PASS 截图里能看到水印" if ok else "FAIL 水印像素太少")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
