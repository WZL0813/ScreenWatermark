# ScreenWatermark · Python 版

> **本实现已冻结在 1.0.0，不再更新。**
> 项目现在只维护 [C++ 版](../../cpp/)。这个 Python 版还能正常跑，
> 但新配置项、新行为不会再同步过来。留着当参考实现，以及快速改参数试效果的试验田。

在屏幕上盖一层**点得到鼠标下面**的半透明文字水印，录屏、远程投屏、截图时都能追责。

只用标准库：`tkinter` + `ctypes` + `json` + `threading`，零第三方依赖。
托盘图标是纯 ctypes 的 `Shell_NotifyIcon`，没有 `pystray`。

## 跑起来

```bat
python main.py
```

要 3.10 以上（开发机 3.12.10，Tk 8.6）。第一次运行会在脚本同级生成 `config.json`；
如果那个目录写不了（比如装在 `Program Files`），自动回落到 `%APPDATA%\ScreenWatermark\config.json`。

也可以 `python -m watermark`，行为一样。

### 命令行参数

| 参数 | 作用 |
| --- | --- |
| `--text "临时文字"` | 临时换水印文字，不写回配置文件 |
| `--config PATH` | 指定配置文件 |
| `--no-tray` | 不起托盘，只挂水印 |
| `--show-panel` | 启动就把设置面板亮出来 |
| `--check` | 只打印显示器/字体/平铺参数，不开窗口（排查用） |
| `-v` / `--version` | 版本号 |

## 怎么用

| 操作 | 效果 |
| --- | --- |
| `Ctrl+Alt+W` | 开/关水印 |
| `Ctrl+Alt+S` | 开/关设置面板 |
| `Ctrl+Alt+Q` | 退出 |
| 托盘图标双击 | 开/关设置面板 |
| 托盘图标右键 | 显示/隐藏水印、设置…、重新载入配置、开机自启、退出 |

关掉设置面板**不会退出程序**，水印继续挂着。退出只能走托盘菜单或 `Ctrl+Alt+Q`。

### 快捷键被占用时会自动降级

`Ctrl+Alt+W` 和 `Ctrl+Alt+Q` 在很多机器上已经被别的常驻软件占了，
所以首选组合注册失败时会**自动退一级**（DESIGN.md §4 的硬性要求）：

| 想按的 | 被占用后自动换成 |
| --- | --- |
| `Ctrl+Alt+W` 开关水印 | `Ctrl+Alt+Shift+W` |
| `Ctrl+Alt+Q` 退出 | `Ctrl+Alt+Shift+Q` |
| `Ctrl+Alt+S` 开关面板 | 不变（它不是被抢的重灾区，注册失败就只能用托盘菜单） |

**实际生效的组合**会写进日志（stdout），也显示在设置面板最下面那行提示里，
所以不会出现"按了半天没反应还找不到原因"。两档都失败也只打日志，程序照常跑，
此时唯一入口就是托盘菜单。

注意：**同时跑多个版本会互相抢键**，先注册的那个拿到，后面的版本会自己往下降级甚至失败，
关掉多余的就行。

## 配置文件

字段和取值范围见 `../docs/DESIGN.md` §2，和 C# 版、C++ 版、Rust 版共用同一份格式，可以互换。
写出来是 UTF-8 无 BOM；解析失败会把坏文件备份成 `config.bad.json` 再用默认值继续跑。

程序还会在配置旁边写一个 `run-status.json`：每次重绘后记录一次单元数、耗时、
实际生效的参数。水印窗是键控透明的，从外面截屏数像素证明不了什么，
这个文件就是"我确实按这套参数重画了"的凭据，排查问题先看它。
它只是诊断信息，随时可以删。

`template: true` 时水印文字里可以用模板变量：

| 变量 | 含义 |
| --- | --- |
| `{time}` | 当前时间，按 `time_format` 格式化 |
| `{date}` | 当前日期 |
| `{user}` | 当前用户名 |
| `{host}` | 计算机名 |
| `{ip}` | 本机内网 IPv4，取不到就是空串 |
| `{{` `}}` | 字面量的 `{` `}` |

## 实现要点

- **点击穿透**：`WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE`，
  改完扩展样式补一次 `SetWindowPos(..., SWP_FRAMECHANGED | ...)`，否则窗口管理器可能不认。
- **不抢焦点**：`WS_EX_NOACTIVATE` + `overrideredirect`，不进 Alt+Tab、不上任务栏。
- **透明度**：不用 `-alpha`（会把文字一起变淡，而且闪），改成把不透明度烘焙进文字颜色，
  背景用 `-transparentcolor` 同款键控色抠成全透明。
- **DPI**：进程启动最早处 `SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)`。
- **多显示器**：`EnumDisplayMonitors`，每块屏一个 Toplevel。
- **托盘 + 快捷键**：独立线程 + 自己的 `GetMessageW` 循环，通过 `queue.Queue` 把命令
  交给主线程 `root.after(50, poll)` 执行；那个线程里不碰任何 tkinter 控件。
- **重绘**：`Canvas.create_text(angle=...)` 逐单元绘制，参数一变只重画不重建窗口。
  单元数超过 3000 自动整格稀疏（上限 20000），极端参数也不会卡死。
- **静置省电**：只有模板含 `{time}`/`{date}` 才起重绘定时器；顶 z 序只改样式不重画。

## 打包

```bat
build.bat
```

依赖 PyInstaller（没装会打印安装命令）。产物是 `dist\ScreenWatermark.exe`。
