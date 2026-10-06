# -*- coding: utf-8 -*-
"""Measure the text bounding box inside the app's own rendered frame.

Clipping is a pixel question, so the check is: dump the frame the app actually
renders (--dump-bitmap) and look at where the alpha channel is non-zero. If any
text pixel touches an edge, the frame is clipped.

Also prints the horizontal bands (an "auto" fallback for counting rows): for a
grid with N rows the ink must form exactly N vertical bands.

ASCII only.
"""
from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys
import time

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
CPP = os.path.dirname(HERE)
EXE = os.path.join(CPP, "build", "ScreenWatermark.exe")
OUT = os.path.join(HERE, "out", "overflow")
DEBUGLOG = os.path.join(CPP, "build", "debug.log")


def kill_stale():
    subprocess.run(["taskkill", "/f", "/im", "ScreenWatermark.exe"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        out = subprocess.run(["tasklist", "/fi", "IMAGENAME eq ScreenWatermark.exe"],
                             capture_output=True, text=True).stdout
        if "ScreenWatermark.exe" not in out:
            return
        time.sleep(0.25)
    raise RuntimeError("ScreenWatermark.exe still running")


def write_cfg(path, cols, rows, angle, font_size=30, text="GRID"):
    cfg = {
        "text": text,
        "font_family": "Microsoft YaHei",
        "font_size": font_size,
        "bold": False,
        "italic": False,
        "color": "#808080",
        "opacity": 0.5,
        "angle": angle,
        "gap_x": 150,
        "gap_y": 120,
        "cols": cols,
        "rows": rows,
        "line_spacing": 1.2,
        "enabled": True,
        "click_through": True,
        "template": False,
        "time_format": "%Y-%m-%d %H:%M",
        "refresh_seconds": 30,
        "all_monitors": True,
        "phase_offset": True,
        "autostart": False,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def bands(mask_rows, thr=0):
    """Contiguous runs of rows that contain ink (thr=0 means 'any ink at all')."""
    out = []
    s = None
    for i, v in enumerate(mask_rows):
        if v > thr and s is None:
            s = i
        elif v <= thr and s is not None:
            out.append((s, i - 1))
            s = None
    if s is not None:
        out.append((s, len(mask_rows) - 1))
    return out


def run_case(name, cols, rows, angle, font_size=30):
    cfg = os.path.join(OUT, name + ".json")
    frame = os.path.join(OUT, name + ".png")
    write_cfg(cfg, cols, rows, angle, font_size)
    for p in (frame, DEBUGLOG):
        if os.path.exists(p):
            os.remove(p)
    env = dict(os.environ)
    env["SW_DEBUG"] = "1"
    proc = subprocess.Popen([EXE, "--config", cfg, "--dump-bitmap", frame],
                            env=env, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    # wait for the first frame dump
    ok = False
    for _ in range(80):
        if os.path.exists(frame) and os.path.getsize(frame) > 1000:
            ok = True
            break
        time.sleep(0.1)
    time.sleep(1.0)  # let the file settle
    alive = proc.poll() is None
    proc.kill()
    kill_stale()
    if not ok:
        print("[%s] FAIL: no frame dumped" % name)
        return None

    grid = ""
    drawn = ""
    cells = []
    if os.path.exists(DEBUGLOG):
        with open(DEBUGLOG, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("网格:") and "外延" in line:
                    grid = re.sub(r"\s+", " ", line.strip())
                elif line.startswith("网格: 实际绘制"):
                    drawn = re.sub(r"\s+", " ", line.strip())
                else:
                    m = re.match(r"^\s*单元#(\d+): x=([-\d.]+) y=([-\d.]+) \(列(\d+) 行(\d+)\)"
                                 r" 画在=([-\d.]+),([-\d.]+)", line)
                    if m:
                        cells.append(tuple(float(m.group(i)) for i in (2, 3, 6, 7)) +
                                     (int(m.group(4)), int(m.group(5))))

    a = np.array(Image.open(frame).split()[-1], dtype=np.uint8)
    h, w = a.shape
    ink = a > 8
    if not ink.any():
        print("[%s] FAIL: frame has no ink" % name)
        return None
    ys, xs = np.where(ink)
    y0, y1 = int(ys.min()), int(ys.max())
    x0, x1 = int(xs.min()), int(xs.max())
    rb = bands(ink.sum(axis=1) > 0)
    inside = (y0 >= 0 and x0 >= 0 and y1 <= h - 1 and x1 <= w - 1)
    touches = (y0 <= 1 or x0 <= 1 or y1 >= h - 2 or x1 >= w - 2)
    # 自动模式本来就会向屏幕外多铺一圈来补旋转后的四角，所以它「贴边」是设计如此
    is_auto = (cols == 0 and rows == 0)

    print("[%s]  alive=%s" % (name, alive))
    print("    %s" % grid)
    print("    %s" % drawn)
    if cells:
        lx = sorted({round(c[0], 1) for c in cells})
        ly = sorted({round(c[1], 1) for c in cells})
        px = sorted({round(c[2], 1) for c in cells})
        py = sorted({round(c[3], 1) for c in cells})
        print("    逻辑 x 值(%d 个)=%s" % (len(lx), lx))
        print("    逻辑 y 值(%d 个)=%s" % (len(ly), ly))
        print("    实际画在 x(%d 个)=%s" % (len(px), px))
        print("    实际画在 y(%d 个)=%s" % (len(py), py))
        print("    首个单元 = 列%d 行%d" % (cells[0][4], cells[0][5]))
    print("    帧 %dx%d  文字像素 y=[%d,%d] x=[%d,%d]  行向文字带=%d 个 %s"
          % (w, h, y0, y1, x0, x1, len(rb), rb if len(rb) <= 8 else rb[:8]))
    if is_auto:
        print("    自动模式：允许向画布外多铺一格（补旋转四角），越界属正常")
    else:
        print("    强制模式验收: y 在 [0,%d) 内=%s ; x 在 [0,%d) 内=%s ; 贴边=%s"
              % (h, y1 < h, w, x1 < w, touches))
    if len(rb) > 1:
        gaps = [rb[i + 1][0] - rb[i][0] for i in range(len(rb) - 1)]
        print("    行带起点间距=%s" % gaps)
    return {"y0": y0, "y1": y1, "x0": x0, "x1": x1, "h": h, "w": w,
            "rows": len(rb), "inside": inside, "touches": touches, "auto": is_auto}


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    kill_stale()
    cases = [
        ("O1_4x3_neg30", 4, 3, -30, 30),
        ("O2_4x3_pos30", 4, 3, 30, 30),
        ("O3_3x4_neg60", 3, 4, -60, 30),
        ("O4_auto_neg30", 0, 0, -30, 30),
        ("O5_4x3_flat", 4, 3, 0, 30),
    ]
    bad = []
    for name, c, r, ang, fs in cases:
        res = run_case(name, c, r, ang, fs)
        if res is None:
            bad.append(name)
            continue
        if res["auto"]:
            print("  -> 自动模式：只核对参数一致性（见上），不做四边判定\n")
            continue
        if not res["inside"]:
            bad.append(name + "(越界)")
        if res["touches"]:
            bad.append(name + "(贴边)")
        if res["rows"] != r:
            bad.append("%s(行带 %d != %d)" % (name, res["rows"], r))
        print()
    print("=== 结论: %s ===" % ("强制模式全部四边未切、行数正确" if not bad
                                else "有问题: " + ", ".join(bad)))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
