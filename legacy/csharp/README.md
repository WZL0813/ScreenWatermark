# csharp/

> **本实现已冻结在 1.0.0，不再更新。**
> 项目现在只维护 [C++ 版](../../cpp/)。这个 C# 版还能正常编译运行，
> 但新配置项、新行为不会再同步过来。留着当参考实现。

Windows 屏幕水印工具的 C# 实现。规格见 [`../docs/DESIGN.md`](../../docs/DESIGN.md)，第 8 节是本实现专属。

## 为什么是 .NET Framework 4.8 而不是 .NET 8

目标机器上很可能什么都没装。Win10/11 自带 .NET Framework 4.8，所以用系统自带的
`csc.exe` 编出来的 exe **双击就能跑，零依赖、零安装**。代价是编译器只认 C# 5，
写不了 `$"..."`、`?.`、`nameof`、表达式体成员这些语法糖——全仓库一律老写法。

## 编译

```bat
cd legacy\csharp
build.bat
```

输出 `build\ScreenWatermark.exe`。构建脚本先找 64 位编译器，找不到才退回 32 位。
它不用 `dotnet build`，因为本机没有装任何 SDK。

有 VS / MSBuild 的人也可以直接开 `ScreenWatermark.csproj`（net48，SDK 风格），
两边编的是同一批 `src\*.cs`。

## 运行

```bat
build\ScreenWatermark.exe
```

首次运行会在 exe 同级目录生成 `config.json`（UTF-8 无 BOM，和 Python 版字段完全一致）。
该目录不可写时回落到 `%APPDATA%\ScreenWatermark\config.json`。

## 交互

| 操作 | 行为 |
| --- | --- |
| `Ctrl+Alt+W` | 开 / 关水印显示 |
| `Ctrl+Alt+S` | 开 / 关设置面板 |
| `Ctrl+Alt+Q` | 退出程序 |
| 托盘图标左键双击 | 开 / 关设置面板 |
| 托盘图标右键 | 显示/隐藏水印、设置…、重新载入配置、开机自启、退出 |
| 关掉设置面板 | 不退出程序，水印继续挂着 |

## 目录

```
csharp/
├── ScreenWatermark.csproj     # 给装了 VS/MSBuild 的人用的另一条构建路径
├── build.bat                  # 一键：系统自带 csc.exe 编出 build\ScreenWatermark.exe
├── app.manifest               # PerMonitorV2 DPI 感知 + Common Controls v6
├── res/app.ico                # 图标，tools/make_icon.py 生成
├── src/
│   ├── Program.cs             # 入口、单实例互斥、DPI、ApplicationContext
│   ├── Config.cs              # 配置对象 + JSON 读写 + strftime 模板变量
│   ├── NativeMethods.cs       # 所有 P/Invoke 集中放这里
│   ├── WatermarkRenderer.cs   # 平铺参数计算 + GDI+ 画到 32bppPArgb 位图
│   ├── OverlayForm.cs         # 每显示器一个逐像素透明的分层窗口
│   ├── TrayIcon.cs            # NotifyIcon + 右键菜单
│   ├── SettingsForm.cs        # 设置面板
│   └── AppController.cs       # 控制器：串起配置/水印/托盘/面板/快捷键/定时器
└── tools/make_icon.py         # 用 Pillow 生成 res/app.ico
```

## 命令行参数

| 参数 | 说明 |
| --- | --- |
| `--config <路径>` | 用指定配置文件，便于调试互不干扰 |
| `--default` | 忽略磁盘上的配置，用内置默认值启动 |
| `--version` / `-v` | 弹出版本号 |
| `--dump-dpi` | 诊断：把进程 DPI 感知等级 / 物理屏尺寸写进 `build\_dpi_report.txt` 后退出 |
| `--dump-metrics` | 诊断：把 §6 的 `text_width / cell_w / cell_h` 实测值写进 `build\_metrics_report.txt` 后退出 |
| `--dump-panel` | 诊断：把设置面板的控件树 + 布局自检写进 `build\_panel_tree.txt` 后退出 |
| `--dump-labels` | 诊断：把各标签/勾选框文字在真实字体下的实测宽度写进 `build\_labels_report.txt` 后退出 |

## 设置面板的布局约定

面板用绝对坐标手工排版，因此有两条必须守住的规矩，都写成代码里的自检：

1. **`TrackBar` 的高度改不了。** WinForms 会把它顶回最小高度（滑块 + 刻度，
   175% DPI 下是 **80px**）。所以滑块行的行距必须 ≥ 滑块高度 + 行内偏移，
   否则滑块会整块盖住下面一行 —— 实测"水平间距/垂直间距"两个输入框就是这样
   从屏幕上消失的（`Controls` 里还在、`IsWindowVisible` 也是 YES，就是不画）。
2. **控件宽度要按实测文字宽给。** 9pt 微软雅黑 UI 在 175% DPI 下一个汉字 24px，
   四字标签 96px；勾选框还要再加约 16px 的勾选图形。估窄了最后一个字就被截。

`SettingsForm.LayoutProblems()` 会在每次显示面板时做几何自检（重叠 / 超出客户区），
发现问题直接写 stderr。`--dump-panel` 也会把结果一并写进报告。

## 验证工具（`tools/`）

这些脚本是给"改完代码要证明它还能跑"用的，不是运行程序所必需的。

| 脚本 | 干什么 |
| --- | --- |
| `make_icon.py` | 用 Pillow 生成 `res/app.ico`（多尺寸，可复现） |
| `verify.ps1` | 启动、5 秒存活、枚举顶层窗口、校验扩展样式位与尺寸、全屏截图、检查 config.json |
| `final_verify.py` | 最终交付验证：重启法对照 ON/OFF，逐像素求差，输出水印像素占比 |
| `verify_core.py` | 核心契约验证：几何、周期、配置持久化 |
| `check_shot.py` | 数截图里的中性灰像素；ON/OFF 逐像素对照 |
| `probe_dpi.py` | 打印这台机器的 DPI 真相（168 DPI / 2520x1680），避免把逻辑像素当物理像素 |

**踩过的坑，写在这里省得下次再踩**：

1. PowerShell 和 `PIL.ImageGrab` 默认都是 DPI-unaware 的。这台机器是 175% 缩放，
   于是物理 2520x1680 的 overlay 会被它们报成 1440x960，看起来像"窗口尺寸不等于屏幕"。
   `verify.ps1` 第一句就是把本进程声明成 PerMonitorV2。
2. 别用 `Stop-Process` 按进程名杀"测试进程"，如果 exe 是被测试脚本 `Start-Process` 起来的，
   它就在脚本的进程树里；脚本被中断会把 exe 一起带走，之后的测量全是"程序没在跑"的假数据。
   这个坑让我一度怀疑配置监听坏了，实际是进程早就没了。
3. **`build.bat` 必须是纯 ASCII**。cmd.exe 按 OEM 代码页（这里是 GBK）解析 .bat，
   UTF-8 写的中文 `echo` 会被切成半截字节，变成一堆"不是内部或外部命令"。
   同理源文件要配 `/codepage:65001`，否则 csc 按 GBK 读 BOM-less UTF-8 源码，
   中文字符串会双重编码写进 config.json。
4. **`Console.Error` 写中文会乱码且不可逆**（它用控制台 OEM 代码页）。日志改成直接往
   标准错误流写 UTF-8 字节，见 `src/Log.cs`。
5. **`DrawToBitmap` 会把布局 bug 藏起来**。它逐个控件调 `OnPaint`，不经过真实的
   z 序合成，所以"被别的控件盖住"的控件在它画出来是好的。判断"控件在屏幕上到底
   显示没有"必须用 `PrintWindow` 或抓屏，或者直接看几何自检。
6. **`FileSystemWatcher` 在本机完全不工作**（D: 和 `C:\Temp` 都实测 0 事件），
   所以别用它来验证配置热载。

## 已知限制

- **外部直接编辑 `config.json` 不会热载**（这台机器的 `FileSystemWatcher` 一个事件都不发，
  在 D: 和 `C:\Temp` 都实测过 0 事件，属于系统级问题，不是本程序的问题）。
  这个功能是"锦上添花"：配置改动请走**设置面板的「应用」**（立即生效），
  或者托盘右键「重新载入配置」，或者重启程序。程序自己保存配置（面板「保存配置」）不受影响。
- 托盘「开机自启」写的是 EXE 绝对路径，移动/改名 EXE 后需要重新勾一次。
- 只有一块显示器时 `all_monitors` 开关看不出区别；显示器插拔会重建全部 overlay 窗口。
- 模板变量只认 `{time}` `{date}` `{user}` `{host}` `{ip}` 和 `{{` `}}`；
  `time_format` 实现的是 Python strftime 的子集（`%Y %y %m %d %H %I %M %S %j %p %b %B %a %A %x %X %f %%`），
  认不出的转换符原样输出。
- 关掉「鼠标穿透」后水印会真的挡住桌面（这是调试用途，规格 §2 就说了），
  此时只能靠托盘或 `Ctrl+Alt+S` 改回来；程序会弹一次气泡提醒。
- `res/app.ico` 是脚本画的，风格朴素；换图标直接替换该文件即可，不用改代码。
- 多显示器代码路径**没有实机验证**（本机只有一块屏），只验证了单屏时行为正确。
- 设置面板为了放下所有控件做成了 910x604；在 100% 缩放的机器上会比这里看着小一些
  （尺寸是逻辑像素，随 DPI 缩放）。


