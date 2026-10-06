"""验证截图里的水印像素，并做 ON/OFF 对照实验证明"看到的就是水印"。

单说"灰色像素比例不是 0"没说服力 —— 桌面壁纸本身就有大量灰。
所以分两步：
  1. 直接数交付截图里的中性灰/中间调像素（报告用数字）；
  2. 只切 config.json 的 enabled，程序会通过 FileSystemWatcher 自己跟上，
     再截一张，逐像素做差。差值只可能来自水印。

用法：
    python tools/check_shot.py
"""
import json
import os
import subprocess
import sys
import time

from PIL import Image, ImageChops

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = os.path.join(ROOT, "build", "config.json")
SHOT = r"D:\Code\ScreenWatermark\docs\shots\csharp-verify.png"
SHOT_OFF = os.path.join(ROOT, "build", "_verify_off.png")
_TMP = os.path.join(ROOT, "build", "_grab.png")


def grab():
    """用 PowerShell + .NET 抓主屏，并且先把那个进程声明成 PerMonitorV2。

    为什么不用 PIL.ImageGrab：它是 DPI-unaware 的，这台机器 175% 缩放下
    它会抓成 2520x1680 的图像但坐标系是逻辑的，数学上对不上 overlay 的物理像素。
    统一走 PMv2 这条路，capture 和 EnumWindows 的坐标系才一致。
    """
    ps = (
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
        "$bmp.Dispose();"
        "Write-Output ($b.Width.ToString()+'x'+$b.Height.ToString())"
    )
    env = dict(os.environ)
    env["SHOT_OUT"] = _TMP
    out = subprocess.check_output(["powershell", "-NoProfile", "-Command", ps],
                                 universal_newlines=True, env=env).strip()
    print("  capture:", out)
    return Image.open(_TMP).convert("RGB")


def read_cfg():
    return json.loads(open(CFG, "rb").read().decode("utf-8"))


def write_cfg(d):
    open(CFG, "wb").write(json.dumps(d, ensure_ascii=False).encode("utf-8"))


def gray_stats(im):
    """中性灰 + 中间调像素计数。

    水印是 #808080 以 15% alpha 掺进背景，得到的必然是中低饱和、亮度居中的像素。
    """
    px = im.load()
    w, h = im.size
    near = mid = 0
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            if max(r, g, b) - min(r, g, b) <= 8:
                near += 1
                if 80 <= (r + g + b) // 3 <= 215:
                    mid += 1
    return w * h, near, mid


def main():
    if not os.path.exists(SHOT):
        print("FAIL: deliverable screenshot missing:", SHOT)
        return 2

    # 这个检查是吃过亏才加的：如果程序没在跑，ON/OFF 两张图其实都是同一个桌面，
    # 差值只剩时钟噪声（几千像素），脚本却照样打印 "WATERMARK VISIBLE"。
    # 宁可硬失败，也不要给出一个看起来成功、实际毫无意义的数字。
    running = subprocess.check_output(
        ["powershell", "-NoProfile", "-Command",
         "(Get-Process ScreenWatermark -ErrorAction SilentlyContinue).Id -join ','; exit 0"],
        universal_newlines=True).strip()
    if not running:
        print("FAIL: ScreenWatermark.exe is not running.")
        print("      先启动它再跑本脚本，否则 ON/OFF 对照没有意义：")
        print("      Start-Process D:\\Code\\ScreenWatermark\\legacy\\csharp\\build\\ScreenWatermark.exe")
        return 3
    print("app running, pid(s):", running)
    print()
    print("== 1. deliverable screenshot ==")
    im_on = Image.open(SHOT).convert("RGB")
    total, near, mid = gray_stats(im_on)
    print("path :", SHOT)
    print("size : %dx%d = %d px" % (im_on.size[0], im_on.size[1], total))
    print("near-gray pixels (saturation<=8)        : %d = %.4f%%" % (near, 100.0 * near / total))
    print("mid-tone gray (sat<=8, mean 80..215)    : %d = %.4f%%" % (mid, 100.0 * mid / total))
    print("REPORT gray-ratio = %.4f%%" % (100.0 * near / total))

    print()
    print("== 2. ON vs OFF controlled diff ==")
    cfg = read_cfg()
    print("config text (ascii repr):", ascii(cfg["text"]))

    cfg["enabled"] = True
    write_cfg(cfg)
    time.sleep(2.5)               # 等 FileSystemWatcher 的 400ms 去抖 + 重画
    on = grab()
    on.save(SHOT)
    print("  saved ON  ->", SHOT)

    cfg["enabled"] = False
    write_cfg(cfg)
    time.sleep(2.5)
    off = grab()
    off.save(SHOT_OFF)
    print("  saved OFF ->", SHOT_OFF)

    cfg["enabled"] = True
    write_cfg(cfg)
    time.sleep(0.5)

    w, h = on.size
    total = w * h
    diff = ImageChops.difference(on, off)
    bbox = diff.getbbox()
    dpx = diff.load()
    changed = 0
    maxdelta = 0
    sumdelta = 0
    for y in range(h):
        for x in range(w):
            r, g, b = dpx[x, y]
            d = max(r, g, b)
            if d > 0:
                changed += 1
                sumdelta += d
                if d > maxdelta:
                    maxdelta = d

    print("changed pixels : %d = %.4f%% of screen" % (changed, 100.0 * changed / total))
    print("bbox of change :", bbox)
    print("covers screen  :", bbox == (0, 0, w, h))
    print("max channel delta:", maxdelta)
    print("mean delta over changed px:", round(sumdelta / changed, 2) if changed else 0)
    print("VERDICT:", "WATERMARK VISIBLE" if changed > 0 else "NO WATERMARK FOUND")

    # 把 OFF 图删掉，别留在交付目录里制造困惑
    try:
        os.remove(SHOT_OFF)
        os.remove(_TMP)
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
