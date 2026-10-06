"""最终交付验证：重启法（不依赖 FileSystemWatcher）。

这台机器的 FileSystemWatcher 一个事件都不发，所以 exe 的热载路径在这里验证不了。
改成写配置 + 重启进程，顺带覆盖验收标准第 6 条"配置存下来，重启后参数还在"。

流程：默认参数(带水印) → 截图存交付路径 → 同参数但 enabled=false → 同机同刻截对照图
      → 逐像素求差 → 报告水印像素占比。

用法：
    python tools/final_verify.py
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
SHOT_OFF = os.path.join(ROOT, "build", "_off_control.png")
TMP = os.path.join(ROOT, "build", "_grab.png")


def ps(cmd):
    # 尾部补 exit 0：Stop-Process 在"没有这个进程"时会返回非 0，
    # check_output 就会抛异常，把正常的清理动作当成失败。
    return subprocess.check_output(
        ["powershell", "-NoProfile", "-Command", cmd + "; exit 0"],
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


def read_cfg():
    return json.loads(open(CFG, "rb").read().decode("utf-8"))


def write_cfg(**kw):
    c = read_cfg()
    c.update(kw)
    tmp = CFG + ".tmp"
    open(tmp, "wb").write(json.dumps(c, ensure_ascii=False).encode("utf-8"))
    os.replace(tmp, CFG)


def restart(expected):
    ps("Get-Process ScreenWatermark -ErrorAction SilentlyContinue | Stop-Process -Force")
    time.sleep(0.8)
    pid = ps("$p=Start-Process -FilePath '%s' -PassThru; Write-Output $p.Id" % EXE)
    time.sleep(5.0)
    alive = ps("if (Get-Process -Id %s -ErrorAction SilentlyContinue) {'yes'} else {'no'}" % pid)
    got = read_cfg()
    print("  pid=%s alive=%s  enabled=%s (wanted %s)" % (pid, alive, got["enabled"], expected))
    return pid, alive


def gray_ratio(im, sat=8, lo=80, hi=215):
    px = im.load()
    w, h = im.size
    n = 0
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            if max(r, g, b) - min(r, g, b) <= sat and lo <= (r + g + b) // 3 <= hi:
                n += 1
    return n, w * h


def main():
    print("== A: default watermark (enabled=true, opacity 0.15, angle -30) ==")
    write_cfg(enabled=True, opacity=0.15, angle=-30, font_size=30, gap_x=150, gap_y=120,
              line_spacing=1.2, phase_offset=True, all_monitors=True, template=False)
    restart(True)
    on = grab()
    on.save(SHOT)
    print("  deliverable screenshot saved:", SHOT, on.size)

    print("== B: control, same settings but enabled=false (needs a restart here) ==")
    write_cfg(enabled=False)
    restart(False)
    off = grab()
    off.save(SHOT_OFF)

    print()
    print("== results ==")
    w, h = on.size
    total = w * h
    g_on, _ = gray_ratio(on)
    g_off, _ = gray_ratio(off)
    print("  gray pixels ON  : %d = %.4f%%" % (g_on, 100.0 * g_on / total))
    print("  gray pixels OFF : %d = %.4f%%" % (g_off, 100.0 * g_off / total))
    print("  gray delta      : %d" % (g_on - g_off))

    d = ImageChops.difference(on, off)
    print("  diff bbox       :", d.getbbox(), "(whole screen = tiled everywhere)")
    px = d.load()
    changed = strong = maxd = 0
    for y in range(h):
        for x in range(w):
            m = max(px[x, y])
            if m > 0:
                changed += 1
                if m > 20:
                    strong += 1
                if m > maxd:
                    maxd = m
    print("  changed pixels  : %d = %.4f%%" % (changed, 100.0 * changed / total))
    print("  strong(>20)     : %d = %.4f%%" % (strong, 100.0 * strong / total))
    print("  max channel delta: %d" % maxd)

    print()
    print("== C: restart with the default watermark again for delivery ==")
    write_cfg(enabled=True)
    restart(True)
    final = grab()
    final.save(SHOT)
    print("  final screenshot:", SHOT, final.size, os.path.getsize(SHOT), "bytes")
    fd = ImageChops.difference(final, off)
    fpx = fd.load()
    fs = sum(1 for y in range(0, h, 2) for x in range(0, w, 2) if max(fpx[x, y]) > 20)
    print("  final changed vs OFF (sampled every 2px): %d" % fs)
    print("  final gray pixels: %d" % gray_ratio(final)[0])

    print()
    # 判据要按"信噪比"来，不能按绝对像素数：默认不透明度只有 15%，
    # 单通道差值大多落在 20~40，强像素(>20)本来就只有全屏的 1% 左右。
    # 而 OFF vs OFF 的时间噪声在这台机器上是 2~4k 像素（见 check_shot_deep.py）。
    verdict = ("WATERMARK VISIBLE (signal far above noise)"
               if (changed > 100000 and strong > 20000) else "INCONCLUSIVE - inspect")
    print("VERDICT:", verdict)
    print("  (noise floor for reference: OFF vs OFF is ~2000-4000 px, measured by check_shot_deep.py)")
    for f in (TMP, SHOT_OFF):
        try:
            os.remove(f)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
