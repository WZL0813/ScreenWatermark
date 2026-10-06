# ScreenWatermark（C++ / Win32 原生版）

> **这是项目唯一在维护的实现。**
> 新功能、新配置项、行为调整都只进这里。
> Python / C# / Rust 三个版本已冻结在 1.0.0，还能用但不再更新。

Windows 桌面水印工具的原生 C++ 实现：在屏幕上盖一层**点得到鼠标下面**的半透明文字水印，
录屏、远程投屏、截图时都能追责。行为契约见 [`../docs/DESIGN.md`](../docs/DESIGN.md) 的 §2～§6、§9。

- 纯 Win32 + GDI+，单 exe，除系统自带的 `gdiplus.dll` 外零第三方依赖（JSON 也是自己写的）
- 每个显示器一个分层窗口（`UpdateLayeredWindow` + 预乘 alpha 的 32bpp DIB）
- 配置与 Python / C# 版共用同一份 `config.json`，UTF-8 无 BOM，字段完全一致

## 一键编译

```bat
cd cpp
build.bat
```

产物：`cpp\build\ScreenWatermark.exe`（约 860 KB）。

`build.bat` 只依赖 MinGW-w64，不需要 CMake：
工具链默认取 `D:\MinGW\bin\g++.exe` 和 `windres.exe`，找不到就退回 PATH。

```bat
build.bat clean     :: 先删 build 目录再编
```

装了 CMake / MSVC 的话也可以用 CMake：

```bat
cmake -S cpp -B cpp/build-msvc -G "Visual Studio 17 2022" -A x64
cmake --build cpp/build-msvc --config Release
```

## 运行

```bat
build\ScreenWatermark.exe                       :: 默认读同目录 config.json，没有就用默认值
build\ScreenWatermark.exe --config D:\my.json   :: 指定配置文件
build\ScreenWatermark.exe --version             :: 打印版本号
```

`--version` 只有 `-mwindows` 的 GUI 子系统，标准输出在有些终端里看不到，可以从别的程序重定向捕获。

## 操作

| 操作 | 行为 |
| --- | --- |
| `Ctrl+Alt+W` | 开 / 关水印显示 |
| `Ctrl+Alt+S` | 开 / 关设置面板 |
| `Ctrl+Alt+Q` | 退出 |
| 托盘图标 左键双击 | 开 / 关设置面板 |
| 托盘图标 右键 | 显示/隐藏水印、设置…、重新载入配置、开机自启、退出 |

**关掉设置面板不会退出程序**，水印继续挂着；退出只能走托盘菜单或快捷键。

> 热键被别的程序占用时（`RegisterHotKey` 返回 false，系统错误码 1409），
> 程序会退一级注册 `Ctrl+Alt+Shift+W` / `Ctrl+Alt+Shift+Q`，并把实际生效的组合写进
> 设置面板底部的提示行；两个都抢不到时不影响其他功能，只是那个快捷键不可用。

## 目录结构

```
cpp/
├── CMakeLists.txt          # 给 MSVC / VS 用
├── build.bat               # 一键：windres + g++（不需要 CMake）
├── src/
│   ├── main.cpp            # wWinMain、单实例互斥、消息窗口、快捷键、控制器
│   ├── config.h/.cpp       # Config 结构 + 自研 JSON 读写 + 模板变量
│   ├── overlay.h/.cpp      # 每显示器一个分层窗口，GDI+ 渲染到 32bpp PARGB DIB
│   ├── tray.h/.cpp         # Shell_NotifyIcon + 右键菜单
│   ├── settings.h/.cpp     # 原生设置面板（14 项控件，实时预览）
│   └── util.h/.cpp         # 字符串 / DPI / 显示器 / 模板变量 / 自启 / 调试日志
├── tools/
│   ├── make_icon.py        # 用 Pillow 生成 res/app.ico（多尺寸）
│   ├── verify_win.ps1      # 枚举水印窗、检查扩展样式、抓全屏截图
│   └── check_shot.py       # 统计截图里的水印像素比例
└── res/
    ├── app.rc              # 图标 + manifest
    ├── app.manifest        # PerMonitorV2 DPI 感知 + Common Controls v6
    └── app.ico
```

设了环境变量 `SW_DEBUG=1` 时，程序会把诊断信息追加写到 exe 同目录的 `debug.log`
（默认不写，不产生垃圾文件）。排查「配置读不进来」「窗口贴图失败」这类问题很有用。
`SW_DUMP_DIB=1` 则会把渲染好的水印位图另存成 `overlay-canvas.png`，
用来确认「画出来的像素」和「屏幕上的样子」是否一致。

## 实现要点

- **贴图路径**：默认用 `Gdiplus::Bitmap(w,h,PixelFormat32bppPARGB)` 自己渲染，
  再 `GetHBITMAP` 取出预乘好的 HBITMAP 交给 `UpdateLayeredWindow`。
  设计规格 §9 原本写的是「自己 `CreateDIBSection` 再用 `Bitmap` 包住像素」，
  但本机实测这条路会让 `UpdateLayeredWindow` 稳定返回 `ERROR_GEN_FAILURE(31)`
  （`Graphics`/`Bitmap` 都析构了也一样），换 GDI+ 自管位图就正常。
  DIB 路径保留在代码里，`SW_GDI_DIB=1` 可以复现，方便换机器时对比。
- **预乘 alpha**：PARGB 要求颜色分量已经乘过 alpha，GDI+ 不会再帮你乘，
  所以文字色是手动预乘后交给 `SolidBrush` 的，漏了这步画出来会发黑。
- **旋转方向**：配置里 `angle` 是「逆时针为正」，GDI+ 的 `RotateTransform` 正角度是顺时针，
  所以传进去的是 `-angle`。
- **四边不留白**：每个单元的平移量里额外加一个 `pad`（文字对角线长度 + 间距），
  否则旋转后文字会被位图边缘切掉，铺出来四周会有一圈空白带。
- **重绘策略**：配置变 / 显示器变 / `{time}` 跳变才重画；另有 `SetTimer` 每 3 秒
  `SetWindowPos(HWND_TOPMOST, SWP_NOACTIVATE|SWP_NOMOVE|SWP_NOSIZE)` 顶一下。
  静置时一个像素都不重画，CPU 接近 0。
- **单元数上限 20000**：间距取 0、字号取 8pt 这种极端参数下单元会爆到几十万，
  超过上限就隔行隔列抽稀，宁可疏一点也不卡死。
- **退出顺序**：控制器 `App` 是函数内 static，析构顺序不可控，所以 `wWinMain` 结尾
  显式按依赖顺序调 `settings.Shutdown()` / `tray.Remove()` / `overlay.Shutdown()`，
  避免出现「面板还活着但字体已经被删掉」的悬空状态。
- **DPI**：manifest 里声明 PerMonitorV2，启动时再查一次实际 awareness 并写进调试日志。
  manifest 没生效时才会去补一刀（已经是 aware 的进程再调设置 API 会失败，硬调反而更乱）。

## 验证方法

```bat
:: 1) 编译（0 error / 0 warning）
cd cpp && build.bat clean

:: 2) 依赖只有系统库
D:\MinGW\bin\objdump.exe -p build\ScreenWatermark.exe | findstr "DLL Name"

:: 3) 起进程，等 5 秒看是否存活
powershell -Command "Start-Process build\ScreenWatermark.exe; Start-Sleep 5; Get-Process ScreenWatermark"

:: 4) 枚举窗口、检查扩展样式、抓全屏截图（脚本会先把 PowerShell 标成 DPI 感知，
::    否则进程外读到的窗口矩形会被 DPI 虚拟化，看着像尺寸不对）
powershell -ExecutionPolicy Bypass -File tools\verify_win.ps1

:: 5) 统计截图里的水印像素
python tools\check_shot.py ..\docs\shots\cpp-verify.png
```

本机实测结果（2026-10-06，Windows，物理屏幕 2520x1680 / 175% 缩放）：
编译 0 error / 0 warning；`objdump -p` 只列出 10 个系统 DLL；
水印窗口 `EX=0x080800A8`（含 LAYERED 0x80000 / TRANSPARENT 0x20 / TOOLWINDOW 0x80 /
NOACTIVATE 0x8000000），矩形 2520x1680 @ (0,0) 与屏幕等大；
整屏 BitBlt 截图 2520x1680，非黑像素 95.83%，中性灰像素 37.58%。


## 已知限制

- 混合 DPI 的多显示器环境下，字号按「水印窗口所在显示器的 DPI」统一计算，
  不同缩放的两块屏之间字号会有一点视觉差异（不会错位，只是大小不完全一致）。
- 托盘图标用 `LoadImageW(GetModuleHandleW(nullptr), MAKEINTRESOURCEW(1), ...)` 取；
  极端情况下资源取不到会退回 `IDI_APPLICATION`。
- 设置面板不记忆位置，每次打开都居中到鼠标所在显示器。
- 热键是全局互斥的：本机同时跑着多个实现时（Python / Rust / C# / C++ 抢同一组键），
  后注册的一方会失败。程序会退级到 `Ctrl+Alt+Shift+W/Q` 并把实际组合写进面板提示行，
  但两个都被占用时就只剩托盘菜单可用了。
- `SW_GDI_DIB=1` 的 DIB 路径在本机是坏的（见上文），留着只为换机器时做对照，
  不要拿它当默认。
