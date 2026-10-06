# -*- coding: utf-8 -*-
"""Multi-line text + image watermark verification, measured on the app's own frame.

Clipping and line counts are pixel questions, so every check reads the bitmap the
app renders (--dump-bitmap) instead of a screenshot.

Images used:
  quad64.png  64x64, four solid quadrants (red/blue/green/yellow) - easy to count
  alpha64.png 64x64, horizontal alpha ramp - proves PNG alpha survives

ASCII only.
"""
from __future__ import annotations

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
OUT = os.path.join(HERE, "out", "ml")
DEBUGLOG = os.path.join(CPP, "build", "debug.log")


def make_images():
    os.makedirs(OUT, exist_ok=True)
    q = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    px = q.load()
    for y in range(64):
        for x in range(64):
            if x < 32 and y < 32:
                px[x, y] = (220, 40, 40, 255)      # 左上 红
            elif x >= 32 and y < 32:
                px[x, y] = (40, 80, 220, 255)      # 右上 蓝
            elif x < 32 and y >= 32:
                px[x, y] = (40, 180, 70, 255)      # 左下 绿
            else:
                px[x, y] = (230, 200, 40, 255)     # 右下 黄
    qpath = os.path.join(OUT, "quad64.png")
    q.save(qpath)

    a = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ap = a.load()
    for y in range(64):
        for x in range(64):
            alpha = int(round(255.0 * x / 63.0))   # 从左全透明到右不透明
            ap[x, y] = (255, 0, 0, alpha)
    apath = os.path.join(OUT, "alpha64.png")
    a.save(apath)
    return qpath, apath


def kill_stale():
    subprocess.run(["taskkill", "/f", "/im", "ScreenWatermark.exe"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        out = subprocess.run(["tasklist", "/fi", "IMAGENAME eq ScreenWatermark.exe"],
                             capture_output=True, text=True).stdout
        if "ScreenWatermark.exe" not in out:
            return
        time.sleep(0.25)
    raise RuntimeError("ScreenWatermark.exe still running")


def base_cfg():
    return {
        "text": "SINGLE",
        "font_family": "Microsoft YaHei",
        "font_size": 30,
        "bold": False,
        "italic": False,
        "color": "#808080",
        "opacity": 0.5,
        "angle": 0,
        "gap_x": 150,
        "gap_y": 120,
        "cols": 0,
        "rows": 0,
        "line_spacing": 1.2,
        "image": "",
        "image_scale": 1.0,
        "enabled": True,
        "click_through": True,
        "template": False,
        "time_format": "%Y-%m-%d %H:%M",
        "refresh_seconds": 30,
        "all_monitors": True,
        "phase_offset": True,
        "autostart": False,
    }


def run_case(name, **over):
    cfg = base_cfg()
    cfg.update(over)
    os.makedirs(OUT, exist_ok=True)
    cfgpath = os.path.join(OUT, name + ".json")
    frame = os.path.join(OUT, name + ".png")
    with open(cfgpath, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    for p in (frame, DEBUGLOG):
        if os.path.exists(p):
            os.remove(p)
    env = dict(os.environ)
    env["SW_DEBUG"] = "1"
    proc = subprocess.Popen([EXE, "--config", cfgpath, "--dump-bitmap", frame],
                            env=env, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    ok = False
    for _ in range(120):
        if os.path.exists(frame) and os.path.getsize(frame) > 1000:
            ok = True
            break
        time.sleep(0.1)
    time.sleep(0.8)
    alive = proc.poll() is None
    proc.kill()
    # read the log before kill_stale wipes anything
    grid, drawn, warns = "", "", []
    if os.path.exists(DEBUGLOG):
        with open(DEBUGLOG, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                s = line.strip()
                if s.startswith("网格:") and "外延" in s:
                    grid = re.sub(r"\s+", " ", s)
                elif s.startswith("网格: 实际绘制"):
                    drawn = re.sub(r"\s+", " ", s)
                elif "警告" in s:
                    warns.append(s)
    kill_stale()
    if not ok:
        return None
    return {"frame": frame, "grid": grid, "drawn": drawn, "warns": warns, "alive": alive}


def ink_bbox(frame):
    a = np.array(Image.open(frame).split()[-1], dtype=np.uint8)
    h, w = a.shape
    ink = a > 8
    if not ink.any():
        return None
    ys, xs = np.where(ink)
    return {"w": w, "h": h, "y0": int(ys.min()), "y1": int(ys.max()),
            "x0": int(xs.min()), "x1": int(xs.max()), "ink": int(ink.sum())}


def row_bands(frame):
    a = np.array(Image.open(frame).split()[-1], dtype=np.uint8)
    rows = (a > 8).sum(axis=1)
    out, s = [], None
    for i, v in enumerate(rows):
        if v > 0 and s is None:
            s = i
        elif v == 0 and s is not None:
            out.append((s, i - 1))
            s = None
    if s is not None:
        out.append((s, len(rows) - 1))
    return out


def main() -> int:
    qpath, apath = make_images()
    print("测试图片: %s / %s" % (qpath, apath))
    kill_stale()
    bad = []

    # ---------- 多行 ----------
    print("\n=== 多行文字 ===")
    for name, text, ls in [
        ("L1_ls12", "AAAA\nBB\n\nCCCCC", 1.2),
        ("L2_ls20", "AAAA\nBB\n\nCCCCC", 2.0),
        ("L3_single", "SINGLE", 1.2),
        ("L4_empty", "", 1.2),
        ("L5_onlynl", "\n\n", 1.2),
        ("L6_100lines", "\n".join("L%d" % i for i in range(100)), 1.2),
    ]:
        r = run_case(name, text=text, line_spacing=ls)
        if not r:
            print("[%s] FAIL: 没落帧" % name)
            bad.append(name)
            continue
        print("[%s] alive=%s" % (name, r["alive"]))
        print("    %s" % r["grid"])
        print("    %s" % r["drawn"])
        if os.path.exists(r["frame"]):
            bb = ink_bbox(r["frame"])
            rb = row_bands(r["frame"])
            if bb is None:
                print("    位图无墨水（空文本/只有换行时属正常）")
            else:
                print("    帧 %dx%d 墨水像素=%d 包围盒 y=[%d,%d] x=[%d,%d]"
                      % (bb["w"], bb["h"], bb["ink"], bb["y0"], bb["y1"], bb["x0"], bb["x1"]))
                print("    行向文字带=%d 个 %s" % (len(rb), rb if len(rb) <= 6 else rb[:6]))
                if len(rb) > 1:
                    print("    行带间距=%s" % [rb[i+1][0] - rb[i][0] for i in range(len(rb)-1)])
        print()

    # ---------- 图片 ----------
    print("=== 图片水印 ===")
    for name, img, scale in [
        ("P1_quad_scale2", qpath, 2.0),
        ("P2_alpha", apath, 2.0),
        ("P3_missing", os.path.join(OUT, "no_such_file.png"), 1.0),
        ("P4_empty", "", 1.0),
    ]:
        r = run_case(name, image=img, image_scale=scale, text="SINGLE")
        if not r:
            print("[%s] FAIL: 没落帧" % name)
            bad.append(name)
            continue
        print("[%s] alive=%s" % (name, r["alive"]))
        print("    %s" % r["grid"])
        print("    %s" % r["drawn"])
        for wl in r["warns"]:
            print("    %s" % wl)
        if os.path.exists(r["frame"]):
            bb = ink_bbox(r["frame"])
            if bb:
                print("    帧 %dx%d 墨水像素=%d 包围盒 y=[%d,%d] x=[%d,%d]"
                      % (bb["w"], bb["h"], bb["ink"], bb["y0"], bb["y1"], bb["x0"], bb["x1"]))
        print()

    print("=== 结论 ===")
    print("有问题的用例: %s" % (", ".join(bad) if bad else "(无)"))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
