@echo off
rem 把 Python 版打包成单文件 exe。缺 PyInstaller 时给出可照抄的安装命令，别只报一句错。
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [build] 找不到 python，请先把 Python 加进 PATH。
    exit /b 1
)

python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo [build] 没有 PyInstaller。先装：
    echo     python -m pip install pyinstaller
    echo 或者只想跑脚本的话，直接： python main.py
    exit /b 2
)

echo [build] 开始打包（单文件、无控制台窗口）...
python -m PyInstaller ^
    --noconfirm --clean --onefile --windowed ^
    --name ScreenWatermark ^
    --paths . ^
    main.py
if errorlevel 1 (
    echo [build] 打包失败，看上面的输出。
    exit /b 1
)

echo [build] 完成： dist\ScreenWatermark.exe
echo [build] 注意：首次运行会在 exe 同级生成 config.json。
endlocal
