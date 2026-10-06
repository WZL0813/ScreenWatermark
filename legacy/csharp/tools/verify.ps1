# verify.ps1 —— 运行验证的全部原始输出（一次跑完，自己负责收尾）。
#
# 关键坑 1：PowerShell 默认 DPI-unaware。这台机器 175% 缩放，物理 2520x1680 的
#   overlay 会被报成 1440x960，看起来像"窗口尺寸不等于屏幕"。所以第一句就是把
#   本进程声明成 PerMonitorV2。
# 关键坑 2：不能用 Stop-Process 按名字杀测试进程树 —— 本脚本启动的 exe 是自己的
#   子进程，脚本被中断时会连带把 exe 带走，后续测量就全是"程序没在跑"的假数据。

$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Add-Type -Namespace P -Name Dpi -MemberDefinition @'
[DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(System.IntPtr v);
[DllImport("user32.dll")] public static extern uint GetDpiForSystem();
'@
[void][P.Dpi]::SetProcessDpiAwarenessContext([System.IntPtr](-4))

$D    = 'D:\Code\ScreenWatermark\legacy\csharp'
$exe  = "$D\build\ScreenWatermark.exe"
$shot = 'D:\Code\ScreenWatermark\docs\shots\csharp-verify.png'
$cfg  = "$D\build\config.json"

Write-Host ("[harness] PMv2 harness, system dpi = " + [P.Dpi]::GetDpiForSystem())

Write-Host ''
Write-Host '===== 1. cleanup ====='
Get-Process ScreenWatermark -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 600
if (Test-Path $cfg) { Remove-Item $cfg -Force; Write-Host "removed stale $cfg" } else { Write-Host 'no stale config' }

Write-Host ''
Write-Host '===== 2. launch, check 5s liveness ====='
$p = Start-Process -FilePath $exe -PassThru
Write-Host ("started pid = " + $p.Id)
Start-Sleep -Seconds 5
$p.Refresh()
$alive = -not $p.HasExited
Write-Host ("alive after 5s : " + $alive)
if ($alive) {
  Write-Host ("exit code      : '" + $p.ExitCode + "'  (empty string = no exit code, still running)")
  Write-Host ("responding     : " + $p.Responding)
  Write-Host ("working set MB : " + [math]::Round($p.WorkingSet64 / 1MB, 2))
} else {
  Write-Host ("EXITED EARLY code=" + $p.ExitCode)
}

Write-Host ''
Write-Host '===== 3. enumerate top-level windows of that pid ====='
Add-Type -Namespace W -Name U -MemberDefinition @'
[DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc cb, IntPtr p);
public delegate bool EnumWindowsProc(IntPtr h, IntPtr p);
[DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, System.Text.StringBuilder s, int n);
[DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassNameW(IntPtr h, System.Text.StringBuilder s, int n);
[DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
[DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
[DllImport("user32.dll", EntryPoint="GetWindowLongPtrW")] public static extern IntPtr GetWindowLongPtrW(IntPtr h, int i);
[DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
[DllImport("user32.dll")] public static extern uint GetDpiForWindow(IntPtr h);
[StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
'@

$targetPid = $p.Id
$found = New-Object System.Collections.ArrayList
$cb = [W.U+EnumWindowsProc]{
  param($h, $l)
  $pid2 = 0
  [void][W.U]::GetWindowThreadProcessId($h, [ref]$pid2)
  if ($pid2 -eq $targetPid) {
    $cls = New-Object System.Text.StringBuilder 256; [void][W.U]::GetClassNameW($h, $cls, 256)
    $txt = New-Object System.Text.StringBuilder 256; [void][W.U]::GetWindowTextW($h, $txt, 256)
    $r = New-Object W.U+RECT; [void][W.U]::GetWindowRect($h, [ref]$r)
    $ex = [W.U]::GetWindowLongPtrW($h, -20).ToInt64()
    [void]$found.Add([pscustomobject]@{
      Handle = ('0x{0:X}' -f $h.ToInt64()); Class = $cls.ToString(); Title = $txt.ToString()
      Visible = [W.U]::IsWindowVisible($h)
      X = $r.Left; Y = $r.Top; W = ($r.Right - $r.Left); H = ($r.Bottom - $r.Top)
      ExStyle = ('0x{0:X8}' -f $ex); ExLong = $ex; Dpi = [W.U]::GetDpiForWindow($h) })
  }
  return $true
}
[void][W.U]::EnumWindows($cb, [IntPtr]::Zero)

Add-Type -AssemblyName System.Windows.Forms
$screen = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
Write-Host ("primary screen (physical, seen by a PMv2 process): {0}x{1}" -f $screen.Width, $screen.Height)
foreach ($w in $found) {
  Write-Host ("  {0} dpi={1} vis={2} rect=({3},{4} {5}x{6}) exstyle={7} title='{8}'" -f `
    $w.Handle, $w.Dpi, $w.Visible, $w.X, $w.Y, $w.W, $w.H, $w.ExStyle, $w.Title)
}

Write-Host ''
Write-Host '===== 4. overlay assertions ====='
$need = 0x80000 -bor 0x20 -bor 0x80 -bor 0x8000000   # LAYERED|TRANSPARENT|TOOLWINDOW|NOACTIVATE
$overlays = @($found | Where-Object { ($_.ExLong -band 0x80000) -ne 0 })
Write-Host ("layered windows: " + $overlays.Count)
foreach ($o in $overlays) {
  Write-Host ("  handle {0}   exstyle {1}" -f $o.Handle, $o.ExStyle)
  Write-Host ("    required mask 0x{0:X8} fully contained = {1}" -f $need, (($o.ExLong -band $need) -eq $need))
  Write-Host ("    WS_EX_LAYERED    0x00080000 present = " + (($o.ExLong -band 0x80000)    -ne 0))
  Write-Host ("    WS_EX_TRANSPARENT 0x00000020 present = " + (($o.ExLong -band 0x20)       -ne 0))
  Write-Host ("    WS_EX_TOOLWINDOW  0x00000080 present = " + (($o.ExLong -band 0x80)       -ne 0))
  Write-Host ("    WS_EX_NOACTIVATE  0x08000000 present = " + (($o.ExLong -band 0x8000000)  -ne 0))
  Write-Host ("    size {0}x{1} == screen {2}x{3} -> {4}" -f $o.W, $o.H, $screen.Width, $screen.Height,
    (($o.W -eq $screen.Width) -and ($o.H -eq $screen.Height)))
}

Write-Host ''
Write-Host '===== 5. full-screen screenshot ====='
Add-Type -AssemblyName System.Drawing
$vs = [System.Windows.Forms.SystemInformation]::VirtualScreen
$bmp = New-Object System.Drawing.Bitmap($vs.Width, $vs.Height, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($vs.X, $vs.Y, 0, 0, (New-Object System.Drawing.Size($vs.Width, $vs.Height)), [System.Drawing.CopyPixelOperation]::SourceCopy)
$g.Dispose()
New-Item -ItemType Directory -Force -Path (Split-Path $shot) | Out-Null
$bmp.Save($shot, [System.Drawing.Imaging.ImageFormat]::Png)
Write-Host ("saved {0} ({1} bytes, {2}x{3})" -f $shot, (Get-Item $shot).Length, $bmp.Width, $bmp.Height)
$bmp.Dispose()

Write-Host ''
Write-Host '===== 6. config.json ====='
$bytes = [System.IO.File]::ReadAllBytes($cfg)
Write-Host ("path  : " + $cfg)
Write-Host ("bytes : " + $bytes.Length)
$bom = ($bytes[0] -eq 0xEF) -and ($bytes[1] -eq 0xBB) -and ($bytes[2] -eq 0xBF)
Write-Host ("UTF-8 BOM present (must be False) : " + $bom)
$obj = [System.IO.File]::ReadAllText($cfg, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
Write-Host ("field count : " + ($obj.PSObject.Properties | Measure-Object).Count + "  (DESIGN.md §2 lists 19)")
Write-Host ("text utf-8 bytes : " + (([System.Text.Encoding]::UTF8.GetBytes($obj.text) | ForEach-Object { '{0:X2}' -f $_ }) -join ' '))
Write-Host '--- raw ---'
[System.IO.File]::ReadAllText($cfg, [System.Text.Encoding]::UTF8)

Write-Host ''
Write-Host ("===== PID " + $p.Id + " left running (killed by the caller) =====")
