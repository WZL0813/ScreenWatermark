@echo off
rem ===========================================================================
rem ScreenWatermark hotkey test bench (ASCII only: cmd reads .bat with the OEM
rem code page, and a stray byte in a comment can swallow a quote).
rem
rem Usage:  tests\run_hotkey_tests.bat
rem Output: tests\out\*.log  (one log per case, plus a combined summary)
rem ===========================================================================
setlocal enabledelayedexpansion
chcp 65001 >nul

set "ROOT=%~dp0.."
set "EXE=%ROOT%\build\ScreenWatermark.exe"
set "TESTS=%~dp0"
set "OUT=%TESTS%out"
set "PY=python"
set "PRESS=%TESTS%press_combo.py"
set "PROBE=%ROOT%\tools\probe_hotkey.py"

if not exist "%EXE%" (
  echo [error] exe not found: %EXE%
  exit /b 1
)
if exist "%OUT%" rmdir /s /q "%OUT%"
mkdir "%OUT%"

rem Make sure nothing of ours is holding hotkeys
taskkill /f /im ScreenWatermark.exe >nul 2>nul
timeout /t 1 /nobreak >nul
echo baselines: > "%OUT%\00-baseline.txt"
%PY% "%PROBE%" state Ctrl+Alt+W Ctrl+Alt+S Ctrl+Alt+Q Ctrl+Alt+Shift+W Ctrl+Alt+Shift+S Ctrl+Alt+Shift+Q Ctrl+Alt+F9 Ctrl+Alt+F10 Ctrl+Alt+F11 >> "%OUT%\00-baseline.txt" 2>&1
type "%OUT%\00-baseline.txt"

rem ---------------------------------------------------------------------------
rem Each case: mkdir tests\out\<case>.dir, copy tests\<case>.json to config.json
rem there, then start the exe with --config pointing at that copy.
rem ---------------------------------------------------------------------------
for %%C in (case1_free case2_taken case3_invalid case4_empty case5_noload) do (
  echo.
  echo ===== %%C =====
  call :run_case "%%C"
)

echo.
echo ===== all done =====
echo logs are in %OUT%
endlocal
exit /b 0

rem ---------------------------------------------------------------------------
:run_case
set "CASE=%~1"
set "DIR=%OUT%\%CASE%.dir"
if exist "%DIR%" rmdir /s /q "%DIR%"
mkdir "%DIR%"
copy /y "%TESTS%%CASE%.json" "%DIR%\config.json" >nul

set "LOG=%OUT%\%CASE%.log"
echo --- case %CASE% --- > "%LOG%"
echo [config] >> "%LOG%"
type "%DIR%\config.json" >> "%LOG%"

rem The key we synthesise per case (must match the case json)
set "PRESSKEY="
for /f "usebackq tokens=1,2" %%A in ("%TESTS%%CASE%.key") do set "PRESSKEY=%%B"

start "" /b "%EXE%" --config "%DIR%\config.json" 2> "%OUT%\%CASE%.stderr.txt"
timeout /t 3 /nobreak >nul

echo. >> "%LOG%"
echo [stderr] >> "%LOG%"
if exist "%OUT%\%CASE%.stderr.txt" type "%OUT%\%CASE%.stderr.txt" >> "%LOG%"

echo. >> "%LOG%"
echo [windows] >> "%LOG%"
%PY% "%PROBE%" windows >> "%LOG%" 2>&1

echo. >> "%LOG%"
echo [hotkey probe] >> "%LOG%"
for %%K in (Ctrl+Alt+F9 Ctrl+Alt+F10 Ctrl+Alt+F11 Ctrl+Alt+W Ctrl+Alt+Shift+W Ctrl+Alt+S Ctrl+Alt+Q Ctrl+Alt+Shift+Q) do (
  %PY% "%PROBE%" state %%K >> "%LOG%" 2>&1
)

echo. >> "%LOG%"
echo [press test: %PRESSKEY%] >> "%LOG%"
%PY% "%TESTS%win_state.py" marker >> "%LOG%" 2>&1
%PY% "%PRESS%" %PRESSKEY% >> "%LOG%" 2>&1
timeout /t 1 /nobreak >nul
%PY% "%TESTS%win_state.py" marker >> "%LOG%" 2>&1
%PY% "%PRESS%" %PRESSKEY% >> "%LOG%" 2>&1
timeout /t 1 /nobreak >nul
%PY% "%TESTS%win_state.py" marker >> "%LOG%" 2>&1

taskkill /f /im ScreenWatermark.exe >nul 2>nul
timeout /t 1 /nobreak >nul

echo. >> "%LOG%"
echo [config after run] >> "%LOG%"
type "%DIR%\config.json" >> "%LOG%"
type "%LOG%"
exit /b 0
