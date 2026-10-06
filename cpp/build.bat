@echo off
rem ===========================================================================
rem ScreenWatermark C++ 版一键构建：windres 编资源 + g++ 编译链接。
rem 不依赖 CMake，只要本机有 MinGW-w64 就能出 exe。
rem
rem 用法：
rem   build.bat            正常编译
rem   build.bat clean      先清掉 build 目录再编译
rem ===========================================================================
setlocal enabledelayedexpansion
chcp 65001 >nul

set "ROOT=%~dp0"
set "BUILD=%ROOT%build"

rem 注意：这里不能用 where 检查，where 只认 PATHEXT 里的短名，给完整路径会报 pattern 错误
set "MINGW=D:\MinGW\bin"
if not exist "%MINGW%\g++.exe" set "MINGW="
if "%MINGW%"=="" (
  set "CXX=g++"
  set "WINDRES=windres"
) else (
  set "CXX=%MINGW%\g++.exe"
  set "WINDRES=%MINGW%\windres.exe"
)

"%CXX%" --version >nul 2>nul
if errorlevel 1 (
  echo [错误] 找不到可用的 g++。请把 MinGW-w64 的 bin 目录加进 PATH，或放到 D:\MinGW\bin。
  exit /b 1
)
"%WINDRES%" --version >nul 2>nul
if errorlevel 1 (
  echo [错误] 找不到 windres。它通常和 g++ 在同一个目录。
  exit /b 1
)

if /i "%~1"=="clean" (
  echo [1/4] 清理 %BUILD%
  if exist "%BUILD%" rmdir /s /q "%BUILD%"
)
if not exist "%BUILD%" mkdir "%BUILD%"

echo [2/4] 编译资源 res\app.rc -^> build\app.res
"%WINDRES%" "%ROOT%res\app.rc" -O coff -o "%BUILD%\app.res"
if errorlevel 1 (
  echo [错误] 资源编译失败。
  exit /b 1
)

echo [3/4] 编译链接 src\*.cpp -^> build\ScreenWatermark.exe
rem -municode 走 wWinMain；-mwindows 不弹控制台；静态链接 libgcc/libstdc++ 免装运行库。
rem -Wall -Wextra 开着，目标是零 warning。
"%CXX%" -std=c++17 -O2 -Wall -Wextra -municode -mwindows ^
  -static-libgcc -static-libstdc++ ^
  -finput-charset=UTF-8 -fexec-charset=UTF-8 ^
  -o "%BUILD%\ScreenWatermark.exe" ^
  "%ROOT%src\main.cpp" "%ROOT%src\config.cpp" "%ROOT%src\overlay.cpp" ^
  "%ROOT%src\tray.cpp" "%ROOT%src\settings.cpp" "%ROOT%src\util.cpp" "%ROOT%src\hotkey.cpp" ^
  "%BUILD%\app.res" ^
  -lgdiplus -luser32 -lgdi32 -lshell32 -ladvapi32 -lole32 -lcomctl32 -lcomdlg32 -liphlpapi
if errorlevel 1 (
  echo [错误] 编译失败。
  exit /b 1
)

echo [4/4] 完成: %BUILD%\ScreenWatermark.exe
for %%F in ("%BUILD%\ScreenWatermark.exe") do echo     大小: %%~zF 字节
endlocal
exit /b 0
