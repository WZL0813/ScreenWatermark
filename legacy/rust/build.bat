@echo off
rem ===========================================================================
rem ScreenWatermark (Rust) 一键构建
rem   1) windres 把 res\app.rc 编成 COFF 目标文件（图标 + manifest）
rem   2) cargo rustc --release，并把 .res 通过 -C link-arg 塞给链接器
rem 产物：target\release\ScreenWatermark.exe
rem
rem 说明：本机没装 MSVC，走 x86_64-pc-windows-gnu（MinGW-w64 gcc 链接）。
rem 用 RUSTUP_TOOLCHAIN 指定工具链而不是 rust-toolchain.toml —— 后者会让
rem rustup 每次都想同步整个 channel。
rem ===========================================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

set "CARGO_BIN=%USERPROFILE%\.cargo\bin"
if not exist "%CARGO_BIN%\cargo.exe" set "CARGO_BIN=%CARGO_HOME%\bin"
set "CARGO=%CARGO_BIN%\cargo.exe"

rem rustc 的链接器就是 gcc，PATH 里必须有 MinGW。
if exist "D:\MinGW\bin\gcc.exe" set "PATH=D:\MinGW\bin;%PATH%"
set "PATH=%CARGO_BIN%;%PATH%"
set "RUSTUP_TOOLCHAIN=stable-x86_64-pc-windows-gnu"

if not exist "%CARGO%" (
  echo [错误] 找不到 cargo.exe，预期在 %CARGO_BIN%
  echo        请先装 Rust： rustup toolchain install stable-x86_64-pc-windows-gnu
  exit /b 1
)
where gcc >nul 2>nul
if errorlevel 1 (
  echo [警告] PATH 里没有 gcc，链接大概率会失败。
  echo        请确认 D:\MinGW\bin\gcc.exe 存在。
)

rem 资源编译器优先找 MinGW 自带的。
set "WINDRES=windres.exe"
if exist "D:\MinGW\bin\windres.exe" set "WINDRES=D:\MinGW\bin\windres.exe"

if not exist "res\app.ico" (
  echo [提示] res\app.ico 不存在，尝试用 tools\make_icon.py 生成...
  python tools\make_icon.py || echo [警告] 图标生成失败，继续构建（exe 会没有图标）
)

if not exist "build" mkdir build
if not exist "target\release" mkdir "target\release"

echo === [1/2] windres: res\app.rc -^> build\app.res ===
"%WINDRES%" res\app.rc -O coff -o build\app.res
if errorlevel 1 (
  echo [错误] windres 失败
  exit /b 1
)

echo.
echo === [2/2] cargo rustc --release ===
rem %CD% 必须展开成绝对路径：链接器的工作目录未必是这里。
"%CARGO%" rustc --release --message-format=json-render-diagnostics -- -C link-arg=%CD%\build\app.res > "%TEMP%\sw_rust_build.json" 2^>^&1
set "RC=%ERRORLEVEL%"

rem 诊断计数：cargo 的 JSON 里 reason=compiler-message 的条目带 level。
set /a WARN=0
set /a ERR=0
if exist "%TEMP%\sw_rust_build.json" (
  for /f %%c in ('find /c /v "" ^< "%TEMP%\sw_rust_build.json"') do set "LINES=%%c"
  for /f %%c in ('findstr /c:"\"level\":\"warning\"" "%TEMP%\sw_rust_build.json" ^| find /c /v ""') do set "WARN=%%c"
  for /f %%c in ('findstr /c:"\"level\":\"error\"" "%TEMP%\sw_rust_build.json" ^| find /c /v ""') do set "ERR=%%c"
) else (
  set "LINES=0"
)

echo.
echo === 诊断摘要 ===
echo   cargo exit code : %RC%
echo   JSON 输出行数   : %LINES%
echo   warning 计数    : %WARN%
echo   error   计数    : %ERR%
echo   JSON 日志       : %TEMP%\sw_rust_build.json

if not "%RC%"=="0" (
  echo.
  echo [错误] 编译失败，最后 40 行输出：
  powershell -NoProfile -Command "Get-Content -Path $env:TEMP\sw_rust_build.json -Tail 40"
  exit /b %RC%
)

if not exist "target\release\ScreenWatermark.exe" (
  echo [错误] 编译通过但找不到 target\release\ScreenWatermark.exe
  exit /b 1
)

for %%f in ("target\release\ScreenWatermark.exe") do echo.
for %%f in ("target\release\ScreenWatermark.exe") do echo [完成] %%f  ^(%%~zf 字节^)
echo 运行： target\release\ScreenWatermark.exe
echo 自检： target\release\ScreenWatermark.exe --selftest
exit /b 0
