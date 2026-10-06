"""在"外部配置改动不会热载"的前提下，验证核心契约仍然成立。

为什么改用重启来测：这台机器的 FileSystemWatcher 一个事件都不发（D: 和 C:\\Temp 都试过），
所以 exe 的热载路径在这里测不出来。改成——写 config.json → 重启进程 → 量像素。
这正好也覆盖了验收标准第 6 条"配置存下来，重启后参数还在"。

用法：
    python tools/verify_core.py
"""
import json
import os
import subprocess
import sys
import time

from PIL import Image, ImageChops

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = os.path.join(ROOT, "build", "ScreenWatermark.exe")
CFG = os.path.join(ROOT, "build", "config.json")
SHOT = r"D:\Code\ScreenWatermark\docs\shots\csharp-verify.png"
TMP = os.path.join(ROOT, "build", "_grab.png")


def ps(cmd):
    return subprocess.check_output(["powershell", "-NoProfile", "-Command", cmd],
                                  universal_newlines=True).strip()


def grab():
    p = (
        "$src='using System.Runtime.InteropServices; public class Dpi{"
        "[DllImport(\"user32.dll\")] public static extern bool "
        "SetProcessDpiAwarenessContext(System.IntPtr v);}';"
        "Add-Type -TypeDefinition $src;"
        "[void][Dpi]::SetProcessDpiAwarenessContext([System.IntPtr](-4));"
        "Add-Type -AssemblyName System.Drawing; Add-Type -AssemblyName System.Windows.Forms;"
        "$b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds;"
        "$bmp=New-Object System.Drawing.Bitmap($b.Width,$b.Height,"
        "[System.Drawing.Imaging.PixelFormat]::Format32bppArgb);"
        "$g=[System.Drawing.Graphics]::FromImage($bmp);"
        "$g.CopyFromScreen($b.X,$b.Y,0,0,(New-Object System.Drawing.Size($b.Width,$b.Height)),"
        "[System.Drawing.CopyPixelOperation]::SourceCopy);"
        "$g.Dispose();"
        "$bmp.Save($env:SHOT_OUT,[System.Drawing.Imaging.ImageFormat]::Png);"
        "$bmp.Dispose()"
    )
    env = dict(os.environ)
    env["SHOT_OUT"] = TMP
    subprocess.check_output(["powershell", "-NoProfile", "-Command", p], env=env)
    return Image.open(TMP).convert("RGB")


def kill_app():
    ps("Get-Process ScreenWatermark -ErrorAction SilentlyContinue | Stop-Process -Force")
    time.sleep(0.8)


def launch_app():
    out = ps("$p=Start-Process -FilePath '%s' -PassThru; Write-Output $p.Id" % EXE)
    time.sleep(5.0)
    alive = ps("if (Get-Process -Id %s -ErrorAction SilentlyContinue) {'yes'} else {'no'}" % out)
    return out, alive


def read_cfg():
    return json.loads(open(CFG, "rb").read().decode("utf-8"))


def write_cfg(**kw):
    c = read_cfg()
    c.update(kw)
    tmp = CFG + ".tmp"
    open(tmp, "wb").write(json.dumps(c, ensure_ascii=False).encode("utf-8"))
    os.replace(tmp, CFG)


def nchg(a, b, thr=25):
    d = ImageChops.difference(a, b)
    px = d.load()
    w, h = d.size
    n = 0
    for y in range(h):
        for x in range(w):
            if max(px[x, y]) > thr:
                n += 1
    return n


def run_phase(label, **cfg):
    """写配置 → 重启 → 截图。返回 (pid, image)。"""
    write_cfg(**cfg)
    kill_app()
    pid, alive = launch_app()
    print("  [%s] pid=%s alive=%s cfg=%s" % (label, pid, alive, {k: read_cfg()[k] for k in cfg}))
    return pid, grab()


def main():
    print("== phase A: geometry (dense) ==")
    pa, dense = run_phase("A", enabled=True, opacity=0.6, angle=0, font_size=30,
                          gap_x=150, gap_y=120, line_spacing=1.2, phase_offset=True)

    print("== phase B: watermarked, default opacity 0.15, angle -30 ==")
    pb, default_on = run_phase("B", enabled=True, opacity=0.15, angle=-30, font_size=30)
    default_on.save(SHOT)
    print("      deliverable screenshot:", SHOT, default_on.size)

    print("== phase C: same settings but enabled=false (control) ==")
    pc, off = run_phase("C", enabled=False)
    off.save(os.path.join(ROOT, "build", "_off.png"))

    print()
    print("== results ==")
    print("  ON(default 0.15) vs OFF  changed(>25) = %d" % nchg(default_on, off))
    print("  ON(dense 0.6)   vs OFF  changed(>25) = %d" % nchg(dense, off))
    print("  dense vs default        changed(>25) = %d" % nchg(dense, default_on))

    # 周期性：用 dense(0.6) 与 off 的差值做自相关（同角度同几何，只是有没有墨）
    from PIL import ImageChops as IC
    d = IC.difference(dense, off)
    px = d.load()
    w, h = d.size
    m = bytearray(w * h)
    for y in range(h):
        b = y * w
        for x in range(w):
            if max(px[x, y]) > 10:
                m[b + x] = 1
    total = sum(m)
    print("\n== tiling periodicity (dense vs off, angle=0) ==")
    print("  mask pixels: %d (%.3f%% of screen)" % (total, 100.0 * total / (w * h)))

    def overlap(dx, dy):
        inter = union = 0
        for y in range(h):
            sy = y + dy
            if sy < 0 or sy >= h:
                continue
            b = y * w
            sb = sy * w
            for x in range(w):
                sx = x + dx
                if sx < 0 or sx >= w:
                    continue
                a = m[b + x]
                bb = m[sb + sx]
                if a and bb:
                    inter += 1
                if a or bb:
                    union += 1
        return inter / float(union) if union else 0.0

    # §6: cell_w = text_width + gap_x ; cell_h = text_height*line_spacing + gap_y
    # --dump-metrics 给的是 Microsoft YaHei 30pt @168dpi：580.8+150=730.8 / 92.4*1.2+120=230.9
    for label, dx, dy in (("cell_w 731", 731, 0), ("cell_h 231", 0, 231),
                          ("both", 731, 231), ("2*cell_w", 1462, 0), ("2*cell_h", 0, 462)):
        print("  overlap at %-11s (%4d,%4d) = %.4f" % (label, dx, dy, overlap(dx, dy)))

    best = (0, 0, -1.0)
    for dy in range(-300, 301, 3):
        if dy == 0:
            continue
        v = overlap(0, dy)
        if v > best[2]:
            best = (0, dy, v)
    print("  best vertical lag   : %d px (%.4f)" % (best[1], best[2]))
    bestx = (0, -1.0)
    for dx in range(200, 1400, 4):
        v = overlap(dx, 0)
        if v > bestx[1]:
            bestx = (dx, v)
    print("  best horizontal lag : %d px (%.4f)" % bestx)

    print("\n== final: restart with defaults for delivery ==")
    write_cfg(enabled=True, opacity=0.15, angle=-30, font_size=30)
    kill_app()
    pid, alive = launch_app()
    final = grab()
    final.save(SHOT)
    print("  pid=%s alive=%s  screenshot=%s %s" % (pid, alive, SHOT, final.size))
    print("  changed vs OFF control: %d" % nchg(final, off))

    try:
        os.remove(TMP)
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
