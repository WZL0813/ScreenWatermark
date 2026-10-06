@echo off
rem ===========================================================================
rem  ScreenWatermark (C#) one-shot build script.
rem
rem  Why not `dotnet build`: this machine only has .NET runtimes, no SDK at all.
rem  The only usable compiler is the in-box .NET Framework csc.exe (C# 5 only).
rem
rem  NOTE: this file is deliberately pure ASCII. cmd.exe parses .bat with the OEM
rem  codepage, so a UTF-8 file with Chinese echo text gets chopped into garbage
rem  commands (verified the hard way). All user-facing Chinese lives in the exe
rem  (MessageBox / tray), not here.
rem ===========================================================================
setlocal
set "ROOT=%~dp0"
cd /d "%ROOT%"

rem Prefer the 64-bit compiler; fall back to the 32-bit path if it is missing.
set "CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not exist "%CSC%" set "CSC=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe"
if not exist "%CSC%" (
  echo [build] FATAL: csc.exe not found - no .NET Framework 4.x on this machine.
  exit /b 1
)

if not exist "%ROOT%build" mkdir "%ROOT%build"
if not exist "%ROOT%res\app.ico" (
  echo [build] WARN: res\app.ico missing. Run: python tools\make_icon.py
)

echo [build] compiler: %CSC%
echo [build] output  : %ROOT%build\ScreenWatermark.exe

rem /platform:x64    -> 64-bit only, matches the PerMonitorV2 manifest assumption
rem /win32manifest   -> DPI awareness + Common Controls v6
rem /win32icon       -> tray + shell icon (read back via ExtractAssociatedIcon)
rem /warnaserror-    -> warnings do not stop the build; we still aim for zero
rem /codepage:65001   -> src files are BOM-less UTF-8. Without this csc reads them
rem                      as GBK and mangles every Chinese string literal.
"%CSC%" /nologo /target:winexe ^
  /platform:x64 /optimize+ /warnaserror- /codepage:65001 ^
  /out:build\ScreenWatermark.exe ^
  /win32icon:res\app.ico /win32manifest:app.manifest ^
  /reference:System.dll /reference:System.Core.dll /reference:System.Drawing.dll ^
  /reference:System.Windows.Forms.dll /reference:System.Web.Extensions.dll ^
  src\*.cs
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
  echo [build] FAILED, csc exit code %RC%
  exit /b %RC%
)
echo [build] OK: build\ScreenWatermark.exe
endlocal
