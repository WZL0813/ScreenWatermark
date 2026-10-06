# verify_win.ps1 —— 水印窗口验证：尺寸必须等于物理屏幕，扩展样式必须含四个关键位。
# 必须先把 PowerShell 自己标成 PerMonitorV2：否则进程外查询拿到的窗口矩形会被
# DPI 虚拟化（本机实测：物理 2520x1680 被报成 1440x960），看起来像「尺寸不对」。
Add-Type @"
using System; using System.Text; using System.Collections.Generic; using System.Runtime.InteropServices;
public class DpiWin {
  [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr ctx);
  [DllImport("user32.dll")] public static extern int GetSystemMetrics(int i);
  public delegate bool EnumProc(IntPtr h, IntPtr p);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetWindowLongPtr(IntPtr h, int i);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L,T,R,B; }
  public static bool Aware() { return SetProcessDpiAwarenessContext((IntPtr)(-4)); }
  public static List<string> All(){ var r=new List<string>();
    EnumWindows((h,p)=>{ var sb=new StringBuilder(256); GetClassName(h,sb,256); string c=sb.ToString();
      if (c.IndexOf("ScreenWatermark")>=0) { uint pid; GetWindowThreadProcessId(h, out pid); RECT rc; GetWindowRect(h, out rc);
        long ex=(long)GetWindowLongPtr(h,-20);
        r.Add(string.Format("{0,-28} pid={1,-6} visible={2,-5} {3}x{4} @ {5},{6} EX=0x{7:X8} [LAYERED={8} TRANSPARENT={9} TOOLWINDOW={10} NOACTIVATE={11}]",
          c,pid,IsWindowVisible(h),rc.R-rc.L,rc.B-rc.T,rc.L,rc.T,ex,
          (ex&0x80000)!=0,(ex&0x20)!=0,(ex&0x80)!=0,(ex&0x8000000)!=0)); }
      return true; }, IntPtr.Zero); return r; }
}
"@ -ReferencedAssemblies System.Drawing
[void][DpiWin]::Aware()
Write-Host ("物理屏幕: {0}x{1}" -f [DpiWin]::GetSystemMetrics(0), [DpiWin]::GetSystemMetrics(1))
[DpiWin]::All() | ForEach-Object { "  $_" }

Add-Type -AssemblyName System.Drawing
Add-Type @"
using System; using System.Runtime.InteropServices;
public class GdiCap {
  [DllImport("user32.dll")] public static extern IntPtr GetDC(IntPtr h);
  [DllImport("user32.dll")] public static extern int ReleaseDC(IntPtr h, IntPtr dc);
  [DllImport("gdi32.dll")] public static extern bool BitBlt(IntPtr dst, int x, int y, int w, int h, IntPtr src, int sx, int sy, int rop);
  [DllImport("gdi32.dll")] public static extern IntPtr CreateCompatibleDC(IntPtr dc);
  [DllImport("gdi32.dll")] public static extern IntPtr CreateCompatibleBitmap(IntPtr dc, int w, int h);
  [DllImport("gdi32.dll")] public static extern IntPtr SelectObject(IntPtr dc, IntPtr obj);
  [DllImport("gdi32.dll")] public static extern bool DeleteDC(IntPtr dc);
  [DllImport("gdi32.dll")] public static extern bool DeleteObject(IntPtr obj);
  [DllImport("user32.dll")] public static extern int GetSystemMetrics(int i);
  public static void Capture(string path) {
    int w = GetSystemMetrics(0), h = GetSystemMetrics(1);
    IntPtr screen = GetDC(IntPtr.Zero);
    IntPtr mem = CreateCompatibleDC(screen);
    IntPtr bmp = CreateCompatibleBitmap(screen, w, h);
    IntPtr old = SelectObject(mem, bmp);
    BitBlt(mem, 0, 0, w, h, screen, 0, 0, 0x00CC0020);
    using (var img = System.Drawing.Image.FromHbitmap(bmp))
      img.Save(path, System.Drawing.Imaging.ImageFormat.Png);
    SelectObject(mem, old); DeleteObject(bmp); DeleteDC(mem); ReleaseDC(IntPtr.Zero, screen);
    Console.WriteLine("截图 " + w + "x" + h + " -> " + path);
  }
}
"@ -ReferencedAssemblies System.Drawing
[GdiCap]::Capture("D:\Code\ScreenWatermark\docs\shots\cpp-verify.png")
