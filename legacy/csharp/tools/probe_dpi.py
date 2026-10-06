"""量一下这台机器的 DPI 真相 + 数一数最终交付截图里的水印像素。

为什么要专门查：PowerShell 和 .NET 都报主屏 1440x960，但 PIL.ImageGrab 抓到的是
2520x1680（1.75 倍）。这两个数字不可能同时对，必须用 ctypes 直接问系统拿底数，
否则"截图证明水印可见"这句话的坐标系就是含糊的。
"""
import ctypes
import ctypes.wintypes as wt
import os
import sys

from PIL import Image

SHOT = r"D:\Code\ScreenWatermark\docs\shots\csharp-verify.png"


def probe_dpi():
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    # 先按 PerMonitorV2 声明，再看系统到底给了什么。
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception as e:
        print("SetProcessDpiAwarenessContext failed:", e)

    print("== DPI / geometry ground truth (this python process, PMv2) ==")
    print("GetDpiForSystem      :", user32.GetDpiForSystem())
    hdc = user32.GetDC(0)
    print("LOGPIXELSX (device)  :", gdi32.GetDeviceCaps(hdc, 88))
    print("LOGPIXELSY (device)  :", gdi32.GetDeviceCaps(hdc, 90))
    print("HORZRES   (device)   :", gdi32.GetDeviceCaps(hdc, 8))
    print("VERTRES   (device)   :", gdi32.GetDeviceCaps(hdc, 10))
    print("DESKTOPHORZRES       :", gdi32.GetDeviceCaps(hdc, 118))
    print("DESKTOPVERTRES       :", gdi32.GetDeviceCaps(hdc, 117))
    user32.ReleaseDC(0, hdc)
    print("GetSystemMetrics(0,1) (screen):",
          user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))
    print("SM_CXVIRTUALSCREEN   :",
          user32.GetSystemMetrics(78), user32.GetSystemMetrics(79))

    # 主屏矩形（物理像素）
    rect = wt.RECT()
    user32.GetWindowRect(user32.GetDesktopWindow(), ctypes.byref(rect))
    print("desktop window rect  : %dx%d" % (rect.right - rect.left, rect.bottom - rect.top))


def count_watermark_pixels(im):
    """数"低饱和 + 中间调"的像素。

    水印是纯灰 #808080 以 15% alpha 掺进背景，结果一定是中性灰且亮度落在中间地带。
    壁纸本身也可能有灰，所以这个数字只用来说明"截图里确实有水墨一样的像素"，
    真正的因果证明在 check_shot.py 的 ON/OFF 逐像素对照里。
    """
    px = im.load()
    w, h = im.size
    sat = lambda r, g, b: max(r, g, b) - min(r, g, b)
    near = mid = 0
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            s = sat(r, g, b)
            if s <= 8:
                near += 1
                if 80 <= (r + g + b) // 3 <= 215:
                    mid += 1
    return w * h, near, mid


def main():
    probe_dpi()
    print()
    print("== deliverable screenshot ==")
    im = Image.open(SHOT).convert("RGB")
    total, near, mid = count_watermark_pixels(im)
    print("path:", SHOT)
    print("size: %dx%d = %d px" % (im.size[0], im.size[1], total))
    print("near-gray (sat<=8)        : %d  = %.4f%%" % (near, 100.0 * near / total))
    print("mid-tone gray (sat<=8,80-215): %d  = %.4f%%" % (mid, 100.0 * mid / total))
    print("file bytes:", os.path.getsize(SHOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
