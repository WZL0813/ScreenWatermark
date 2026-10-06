# ScreenWatermark 设计规格（四个实现共用）

> 本文件是四个实现（Python / C# / C++ / Rust）的共同契约。改行为先改这里。
> 许可：AGPL-3.0-or-later。
>
> **维护状态**：项目现在只维护 **C++ 实现**（§9）。
> §7（Python）、§8（C#）、§10（Rust）三节保留下来当历史资料和参考实现的对照，
> **冻结在 1.0.0，不再随本文件演进而更新**。
> 以后新增的配置字段和交互，只需要 §9 跟着改；另外三个会把未知字段原样保留，读不丢。

## 0. 一句话

在屏幕上盖一层**点得到鼠标下面**的半透明文字水印，录屏、远程投屏、截图时都能追责。

## 1. 目标平台

- Windows 10 1809 及以上（x64）。不用考虑 XP/Win7。
- 不做 macOS / Linux。代码里出现 `#ifdef` 跨平台分支属于跑题。

## 2. 配置文件

**唯一真相来源**：可执行文件/脚本同级目录下的 `config.json`（UTF-8 无 BOM）。
若该目录不可写，回落到 `%APPDATA%\ScreenWatermark\config.json`。
两个实现必须能互相读对方的 config.json —— 字段名、类型、取值范围完全一致。

```jsonc
{
  "text": "内部资料 请勿外传",   // string，水印文字。**可多行**：用 \n 换行，空行照样占一行高度
                                //   （设置面板里对应一个多行输入框，回车即可换行，见 §5）
  "image": "",                   // string，图片水印路径。非空且能加载时**用图片平铺并忽略 text**；
                                //   加载失败退回文字水印并写警告。空 = 不用图片
  "image_scale": 1.0,            // float, 0.05..20，图片缩放倍数，1.0 = 原始像素大小
  "font_family": "Microsoft YaHei", // string，字体名，找不到就回退系统默认 UI 字体
  "font_size": 30,               // int, 8..400，逻辑像素（96 DPI 下的磅值概念，用 pt 也行，两个实现都用“磅”）
  "bold": true,                  // bool
  "italic": false,               // bool
  "color": "#808080",            // string，"#RRGGBB"，不含 alpha
  "opacity": 0.15,               // float, 0.01..1.0，整体水印不透明度
  "angle": -30,                  // int, -90..90，逆时针为正（和 Qt/GDI+ 的旋转方向保持一致）
  "gap_x": 150,                  // int, 0..2000，同一行相邻水印的水平间距（像素）
  "gap_y": 120,                  // int, 0..2000，相邻行的垂直间距（像素）
  "cols": 0,                     // int, 0..200，每屏强制几列；0 = 自动（用 gap_x 算）
  "rows": 0,                     // int, 0..200，每屏强制几行；0 = 自动（用 gap_y 算）
  "line_spacing": 1.2,           // float, 0.5..3.0，多行文本的行距倍数（单行时不影响结果）
  "enabled": true,               // bool，水印是否显示
  "click_through": true,         // bool，true = 鼠标穿透；false = 水印挡住鼠标（调试用）
  "template": false,             // bool，是否启用模板变量替换
  "time_format": "%Y-%m-%d %H:%M", // string，strftime 格式；C++ 端用等价实现
  "refresh_seconds": 30,         // int, 5..3600，模板变量刷新间隔
  "all_monitors": true,          // bool，true = 所有显示器铺满；false = 只铺主显示器
  "phase_offset": true,          // bool，true = 每行水平错开半格，看起来不像网格
  "autostart": false,            // bool，开机自启（写 HKCU\...\Run）
  "hotkeys": {                   // object，全局快捷键，三个动作各一个组合字符串
    "toggle": "Ctrl+Alt+W",      //   开关水印显示
    "settings": "Ctrl+Alt+S",    //   开/关设置面板
    "quit": "Ctrl+Alt+Q"         //   退出程序
  }
}
```

### cols / rows 字段的写法

- **`0` = 自动**：`cell_w = 文字宽 + gap_x`、`cell_h = 文字高 × line_spacing + gap_y`，
  并从屏幕外各多铺一格补旋转后的四角。**老配置（没有这两个字段）走的就是这条分支，行为不变。**
- **`>0` = 强制**：`cell_w = 屏宽 / cols`、`cell_h = 屏高 / rows`，
  从 `x=0` / `y=0` 起**正好画 cols 列、rows 行**，不再向屏幕外扩。
  含义是「**每块屏幕** cols 列 rows 行」。
- 两个方向互相独立：可以只强制列数、行数仍自动（反之亦然）。
- `cols > 0` 时 `gap_x` 被忽略（字段保留，自动模式下仍生效）；`rows > 0` 时 `gap_y` 同理。
- `line_spacing` 只影响自动模式的行高（`font_px * line_spacing`），强制模式下被 `rows` 取代。
- `phase_offset` 两种模式都照旧生效（奇数行右移半格）。
- 兜底：算出来的 `cell_w` / `cell_h` 不足 1 像素就跳过这一帧，不许死循环。
- **四边不许切字**：文字是绕单元左上角旋转的，旋转后它会比单元矩形大。强制模式会把每一格的
  文字盒夹进画布内（`x ∈ [0, w)`、`y ∈ [0, h)`），并对强制的那一维再做一次越界丢弃兜底，
  所以 `angle` 取任何值（含主人常用的 `-30`）都不会出现被切掉半截的字。
  自动模式不参与这个夹取——它本来就靠「向屏幕外多铺一圈」来补旋转后的四角，属正常手法。

### hotkeys 字段的写法

- 组合字符串大小写不敏感，形如 `修饰键+修饰键+主键`，例如 `"Ctrl+Alt+F9"`、`"control+shift+w"`。
- 修饰键：`Ctrl`（也接受 `Control`）、`Alt`、`Shift`、`Win`；主键：`A`-`Z`、`0`-`9`、`F1`-`F24`。
- **空字符串 `""` 表示不要这个快捷键**（不注册，不是错误）。
- 整段 `hotkeys` 缺失时，三个动作都用上面的默认值补上（老配置文件必须照常工作）。
- 某一项写法不合法（例如 `"Foo+Bar"`）时，**只让这一项退回它的默认值**，并在 stderr/日志里
  写明是哪一项、原文是什么；另外两项照常注册，其它配置字段一律不受影响。
- 写回配置时 `hotkeys` 放在 `autostart` 之后、未知字段之前。

缺字段一律用上面的默认值补齐；未知字段保留不删（写回时带上）。
解析失败不要崩：备份坏文件为 `config.bad.json`，用默认值继续跑。

## 3. 模板变量（`template: true` 时生效）

| 变量 | 含义 | Windows 取法 |
| --- | --- | --- |
| `{time}` | 当前时间 | 按 `time_format` 格式化 |
| `{date}` | 当前日期 | `%Y-%m-%d` |
| `{user}` | 当前用户名 | `GetUserNameW` / `getpass.getuser()` |
| `{host}` | 计算机名 | `GetComputerNameW` / `socket.gethostname()` |
| `{ip}` | 本机内网 IPv4（取不到就空串） | 见下 |
| `{{` `}}` | 字面量 `{` `}` | — |

`{time}` 会变，所以水印要按 `refresh_seconds` 自动重绘。其它变量在一轮进程里是常量。

## 4. 交互契约（四个实现必须一致）

| 操作 | 行为 |
| --- | --- |
| 全局快捷键（可自定义，见 §2 `hotkeys`） | `toggle` 开/关水印显示、`settings` 开/关设置面板、`quit` 退出程序；默认 `Ctrl+Alt+W` / `Ctrl+Alt+S` / `Ctrl+Alt+Q` |

> **热键降级（必须实现）**：`Ctrl+Alt+W` 和 `Ctrl+Alt+Q` 在很多机器上已经被别的常驻软件占了
> （本机实测就是：`RegisterHotKey` 返回 1409，把本程序全部杀掉后依然如此）。
> 所以首选组合注册失败时，**必须自动退一级**去注册「加 Shift」的版本
> （`Ctrl+Alt+W` → `Ctrl+Alt+Shift+W`），并把**实际生效**的组合写进日志和设置面板底部的提示行
> —— 别让用户按了半天没反应还找不到原因。降级版也注册不上时只打日志，程序继续跑。
> 配置里某一项是空串则直接跳过（不注册，不算错误）。
| 托盘图标 左键双击 | 开/关设置面板 |
| 托盘图标 右键 | 弹出菜单：显示/隐藏水印、设置…、重新载入配置、开机自启（勾选项）、退出 |
| 托盘提示文字 | `ScreenWatermark · 已启用` / `已隐藏` |
| 关掉设置面板 | **不退出程序**，水印继续挂着；退出只能走托盘或快捷键 |

水印窗口本身**不吃焦点、不进 Alt+Tab、不出现在任务栏**。
`click_through: true` 时鼠标事件完全穿透（`WS_EX_TRANSPARENT`）。

## 5. 设置面板要有哪些控件

按参考项目来，一个都不能少，另外补齐：

1. 水印文本（**多行**输入框，约 3~4 行高；回车换行，任意位置能留空行）
2. 字体大小（数值框，8..400）
3. 不透明度（滑块 1..100，显示百分比）
4. 旋转角度（滑块 -90..90）
5. 水平间距 / 垂直间距（两个数值框）
6. 文字颜色（颜色选择）
7. 字体名（下拉或输入）
8. 粗体 / 斜体（勾选）
9. 启用模板变量（勾选）+ 时间格式输入框
10. 实时预览勾选框（默认开）
11. 全部显示器（勾选）
12. 行错位（勾选）
12b. 每行个数 / 每列个数（两个数值框，`0 = 自动`，范围 0..200）
12c. 水印图片：路径显示（只读）+「选择…」+「清除」+「缩放」数值框（0.05..20）
13. 按钮：应用、隐藏水印、保存配置、重置默认
14. 全局快捷键：三个输入框（开关水印 / 设置面板 / 退出程序）+ 每个配一个「录制」按钮
15. 两行提示：一行写**实际生效**的快捷键组合（含降级结果），一行写注册失败的原因

**快捷键输入框与录制按钮**：
- 输入框可以直接手敲组合文本（如 `Ctrl+Alt+F9`），失焦或点「应用」时按 §2 的规则解析；
  不合法的项退回该项默认值，并在提示行说明是哪一项。
- 点「录制」后按钮文字变成「按下组合…」，此时抓用户按下的组合填进输入框：
  **单独按下的修饰键不算**，`Esc` 取消录制。
- 录制期间必须把已经注册的全局热键**整体撤掉**，否则用户按到自己的热键会先把水印关了；
  录制结束（填值 / 取消 / 关面板 / 退出）一定要恢复。
- 录完或改完要立刻尝试重新注册（先 `UnregisterHotKey` 再 `RegisterHotKey`），
  成功就刷新提示行，失败就在提示行写明「XX 被别的程序占用」。

**实时预览**：勾上时，改任何控件立刻重新渲染水印（不要销毁重建窗口，要改参数后重画）。

## 6. 渲染规则（四个实现的像素级约定）

- 水印是一张**预渲染的位图**，周期性（或配置变化时）重画，不是每帧重画。
- 平铺算法：
  - 单元宽度 `cell_w = text_width + gap_x`
  - 单元高度 `cell_h = text_line_height * line_spacing + gap_y`
  - 从 `x = -cell_w` 开始铺到 `宽 + cell_w`，`y = -cell_h` 铺到 `高 + cell_h`（负起点和溢出是为了旋转后四边不留白）
  - `phase_offset` 为真时，奇数行 `x` 再加 `cell_w / 2`
- 每个单元：先平移，再绕单元原点旋转 `angle`，然后左对齐绘制文字。
- 文字颜色 = `color` × `opacity`（作为 alpha 通道），抗锯齿开。
- 铺完后整张位图用 `UpdateLayeredWindow`（C++）/ Canvas 图像（Python）贴到屏幕上。
- **性能**：1920×1080 一屏平铺通常 100~400 个单元，单次重绘必须 < 200ms。角度/间距极端值下也不能卡死（单元数上限 20000 个）。

### 6.1 多行文字与图片水印

- **多行**：`text` 里的 `\n` 是硬换行，**不自动折行**。单元尺寸必须用实测的多行文字盒：
  `text_w` = 各行宽度的最大值，`text_h` = 行数 × 行高 × `line_spacing`；
  **空行照样占一行高度**。自动模式下 `cell_h = text_h + gap_y`
  （不再是单行那套 `字号像素 × line_spacing + gap_y`）。
  行距由 `line_spacing` 决定，所以得**逐行绘制**（GDI+ 的 `DrawString` 管不了行距倍数），
  整体旋转一次再逐行画。
- **图片**：`image` 非空且加载成功时，一个「单元」的内容从文字换成图片；
  平铺、旋转、透明度、`gap_*`、`cols`/`rows` 全部共用同一套逻辑。
  图片按 `image_scale` 缩放，整体透明度用 `opacity`，**PNG 的 alpha 必须保留**
  （别把透明区域画成黑块）。加载失败要退回文字水印并写警告，
  按「路径 + 文件修改时间 + 缩放倍数」缓存，不要每帧读盘。

## 7. Python 实现（`legacy/python/`，已冻结）

- **只用标准库**，零第三方依赖。`tkinter` + `ctypes` + `json` + `threading`。不要 PySide6/PyQt。
- 入口：`python main.py`（`main.py` 在 `legacy/python/` 根）。也可以 `python -m watermark`。
- 目录结构：

```
python/
├── main.py                  # 入口：解析 --config/--text/--no-tray 等参数
├── watermark/
│   ├── __init__.py
│   ├── config.py            # 配置 dataclass、加载/保存、模板变量替换
│   ├── win32.py             # ctypes 帮手：DPI、显示器枚举、点击穿透、置顶、开机自启
│   ├── render.py            # 平铺参数计算 + PIL-free 的绘制（见下）
│   ├── overlay.py           # 每个显示器一个 tkinter Toplevel 水印窗
│   ├── tray.py              # 纯 ctypes 的 Shell_NotifyIcon 托盘 + 右键菜单
│   ├── panel.py             # tkinter 设置面板
│   └── app.py               # 控制器：串起配置/水印/托盘/面板/快捷键/定时器
├── build.bat                # PyInstaller 打包成单文件 exe（可选，缺 PyInstaller 要友好报错）
└── README.md
```

关键实现要求：

- **点击穿透**：`tkinter` 窗口用 `root.attributes('-topmost', True)` + `-transparentcolor` 之外，必须用 ctypes：
  `GWL_EXSTYLE` 加上 `WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE`。
- **不要用 `-alpha` 做整体透明**（那会把内容也变淡且闪）。透明度直接烘焙进文字颜色里。
- **DPI 感知**：进程启动最早处调 `SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)`；tkinter 拿到的坐标要和物理像素对齐。
- **绘制**：tkinter `Canvas` 上用 `create_text(..., angle=...)` 逐单元绘制（Tk 8.6 支持 `angle`）。单元太多会慢 → 单元数超过阈值（比如 3000）时自动降低密度提示一次，别卡死。
- **托盘**：纯 ctypes 实现。要点：
  - 在**独立线程**里创建隐藏窗口类（`RegisterClassW` + `CreateWindowExW`）并跑自己的 `GetMessageW` 循环，别和 tkinter 的 mainloop 抢。
  - `Shell_NotifyIconW(NIM_ADD, ...)`，`uCallbackMessage = WM_APP + 1`，右键弹 `TrackPopupMenu`（要先 `SetForegroundWindow`，否则菜单不消失）。
  - 图标用 `LoadIconW(None, IDI_APPLICATION)` 或 `LoadImageW` 加载内嵌 ICO；先能跑起来优先，图标丑可以后补。
  - `NIM_ADD` 失败不要崩，打印警告并让程序继续（此时只能靠快捷键和面板控制）。
- **快捷键**：`RegisterHotKey` 在托盘线程的那个消息循环里注册并在循环里处理 `WM_HOTKEY`，回调里通过线程安全的方式通知 tkinter（`root.after(0, ...)` 或队列 + 轮询）。**不要**在线程里直接碰 tkinter 控件。
- **多显示器**：`EnumDisplayMonitors` 拿每个显示器的物理矩形，每个显示器一个 Toplevel。
- 首次运行 `python main.py` 要能直接出水印，不能要求先配什么东西。

## 8. C# 实现（`legacy/csharp/`，已冻结）

**为什么不用 .NET 8 / dotnet SDK**：本机只装了 .NET 运行时（10.0.12 / 8.0.31 / 6.0.36），**没有装任何 SDK**，`dotnet build` 跑不了。所以走 .NET Framework 4.8 + WinForms，用系统自带的编译器编：

```
C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe      (4.8.9221.0，64 位)
C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe        (32 位回退)
```

Win10/11 自带 .NET Framework 4.8，所以编出来的 exe **双击就能跑，不用装任何运行时**。

> **编译器的硬限制**：这个内置 csc 只支持 **C# 5**。以下语法一律不能用，用了直接编译报错：
> 字符串内插 `$"..."`、`?.`、`nameof`、表达式体成员 `=>`、自动属性初始化器 `{ get; set; } = x`、`using static`、元组、局部函数、`out var`。
> 用 `string.Format(...)`、`Math.Min` 之类老写法。这个坑我已经实测确认过（`error CS1056: 意外的字符“$”`）。

- 目录结构：

```
csharp/
├── ScreenWatermark.csproj     # 给装了 VS/MSBuild 的人用（net48，SDK 风格）
├── build.bat                  # 一键：调内置 csc 编出 build\ScreenWatermark.exe
├── app.manifest               # PerMonitorV2 DPI 感知 + Common Controls v6
├── res/app.ico                # 图标（用 csc /win32icon: 挂上去）
├── src/
│   ├── Program.cs             # 入口、单实例互斥、DPI、ApplicationContext
│   ├── Config.cs              # 配置对象 + JSON 读写 + 模板变量
│   ├── NativeMethods.cs       # 所有 P/Invoke 集中放这里
│   ├── WatermarkRenderer.cs   # 平铺参数计算 + GDI+ 画到 32bppPArgb 位图
│   ├── OverlayForm.cs         # 每显示器一个分层窗口
│   ├── TrayIcon.cs            # NotifyIcon + 右键菜单
│   ├── SettingsForm.cs        # 设置面板
│   └── AppController.cs       # 控制器：串起配置/水印/托盘/面板/快捷键/定时器
└── README.md
```

编译命令形状（build.bat 里就是这条，参数别写错）：

```bat
"%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /nologo /target:winexe ^
  /platform:x64 /optimize+ /warnaserror- ^
  /out:build\ScreenWatermark.exe ^
  /win32icon:res\app.ico /win32manifest:app.manifest ^
  /reference:System.dll /reference:System.Core.dll /reference:System.Drawing.dll ^
  /reference:System.Windows.Forms.dll /reference:System.Web.Extensions.dll ^
  src\*.cs
```

关键实现要求：

- **逐像素透明窗口**（不是 `TransparencyKey`，那个会把抗锯齿边缘啃出锯齿）：
  - `OverlayForm` 重写 `CreateParams`，`cp.ExStyle |= WS_EX_LAYERED(0x80000) | WS_EX_TRANSPARENT(0x20) | WS_EX_TOOLWINDOW(0x80) | WS_EX_NOACTIVATE(0x8000000)`。
  - `FormBorderStyle = None`、`ShowInTaskbar = false`、`StartPosition = Manual`、`TopMost = true`。
  - 重写 `OnPaintBackground` 让它什么都不做（内容全部由 `UpdateLayeredWindow` 提供）。
  - 画法：`new Bitmap(w, h, PixelFormat.Format32bppPArgb)` → `Graphics.FromImage` 画斜排文字 → `bmp.GetHbitmap(Color.FromArgb(0))` 拿 HBITMAP → `UpdateLayeredWindow(Handle, screenDc, ref ptDst, ref size, memDc, ref ptSrc, 0, ref blend, ULW_ALPHA)`，`blend = new BLENDFUNCTION { BlendOp = AC_SRC_OVER, SourceConstantAlpha = 255, AlphaFormat = AC_SRC_ALPHA }`，用完 `DeleteObject(hbmp)`。
  - 必须先 `Show()` 再用 `Handle`；改尺寸用 `SetBounds` 后重画。
- **渲染**：`Graphics.SmoothingMode = SmoothingMode.AntiAlias`，文字用 `Graphics.DrawString(text, font, brush, 0, 0)`（**不要用** `TextRenderer.DrawText`，那个走 GDI 不认 Graphics 变换矩阵），颜色 alpha = `opacity × 255`。旋转用 `g.TranslateTransform` + `g.RotateTransform(angle)`。平铺算法严格按 §6。
- **托盘**：WinForms 的 `NotifyIcon` + `ContextMenuStrip`。图标用 `Icon.ExtractAssociatedIcon(Application.ExecutablePath)`（配合 `/win32icon`），拿不到就退回 `SystemIcons.Application`。
- **快捷键**：`RegisterHotKey(handle, id, MOD_CONTROL|MOD_ALT, Keys.W/S/Q)`。需要一个收 `WM_HOTKEY` 的窗口 —— 用一个不可见的 `NativeWindow` 或者主 `OverlayForm` 的 `WndProc` 重写（推荐后者，别多开窗口）。
- **退出**：`Application.Run(new AppController())`，`AppController : ApplicationContext`。设置面板关闭时 `Hide()` 而不是退出（`OnFormClosing` 里 `e.Cancel = true`）。
- **单实例**：`new Mutex(true, "Global\\ScreenWatermark_SingleInstance", out createdNew)`，已存在就 `MessageBoxW` 提示后退出。
- **配置 JSON**：用 `System.Web.Extensions` 里的 `JavaScriptSerializer`（`/reference:System.Web.Extensions.dll`），反序列化成 `Dictionary<string, object>`，这样未知字段天然保留。
  - 读：`File.ReadAllText(path, new UTF8Encoding(false))`；写：`File.WriteAllText(path, json, new UTF8Encoding(false))` —— **UTF-8 无 BOM**，Python 版要能直接读。
  - JSON 里的数字回来是 `int`/`decimal`，取值要写容错的转换（别直接强转，会 `InvalidCastException`）。
  - 解析异常时把坏文件备份成 `config.bad.json`，用默认值继续。
- **DPI**：`app.manifest` 声明 `<dpiAwareness>PerMonitorV2</dpiAwareness>`，`Screen.AllScreens[i].Bounds` 拿到的就是物理像素。manifest 里同时声明 Common Controls v6 依赖。
- **多显示器**：`Screen.AllScreens` 每块一个 `OverlayForm`；`DisplaySettingsChanged` 事件里重建。
- **重绘策略**：配置变、屏幕变、模板变量跳变才重画；`System.Windows.Forms.Timer` 每 3 秒 `SetWindowPos(HWND_TOPMOST, SWP_NOACTIVATE|SWP_NOMOVE|SWP_NOSIZE)` 顶一下。
- **内存**：每次重画都要 `Dispose` 掉旧的 `Bitmap`/`Graphics`/`Font`/`Brush`，静置 5 分钟不能涨。

## 9. C++ 实现（`cpp/`）

- **Win32 原生，单 exe**，除系统自带的 `gdiplus.dll` 外无第三方依赖。不要 Qt / wxWidgets / nlohmann-json（自己写个够用的小 JSON 读写）。
- 工具链（本机实测可用）：
  - MinGW-w64 g++ 15.1：`D:\MinGW\bin\g++.exe` → **必须能编**；
  - `D:\MinGW\bin\windres.exe` 编资源；
  - 同时给一份 `CMakeLists.txt`，让 MSVC 也能编。
- 目录结构：

```
cpp/
├── CMakeLists.txt
├── build.bat                # 一键：windres 编 rc + g++ 编译链接（不装 CMake 也能出 exe）
├── src/
│   ├── main.cpp             # wWinMain、单实例互斥、消息循环、快捷键
│   ├── config.h/.cpp        # 与 §2 完全一致的 JSON 读写
│   ├── overlay.h/.cpp       # 每显示器一个分层窗口，GDI+ 渲染到 32bpp PARGB DIB
│   ├── tray.h/.cpp          # Shell_NotifyIcon + 右键菜单
│   ├── settings.h/.cpp      # 原生设置窗口（CreateWindowEx 控件）
│   └── util.h/.cpp          # 字符串 / DPI / 显示器 / 模板变量 / 自启
├── tools/make_icon.py       # 用 Python + Pillow 生成 res/app.ico
└── res/
    ├── app.rc               # 图标 + manifest（PerMonitorV2、Common Controls v6）
    └── app.ico
```

编译链接参数形状：

```bat
windres res\app.rc -O coff -o build\app.res
g++ -std=c++17 -O2 -municode -mwindows -static-libgcc -static-libstdc++ ^
    -o build\ScreenWatermark.exe src\*.cpp build\app.res ^
    -lgdiplus -luser32 -lgdi32 -lshell32 -ladvapi32 -lole32 -lcomctl32
```

关键实现要求：

- **分层窗口**：`WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TOPMOST` + `WS_POPUP`。
- **画法**：自己 `CreateDIBSection`（32bpp、`BI_RGB`、**负高度 top-down**），再用 `Gdiplus::Bitmap(w, h, stride, PixelFormat32bppPARGB, bits)` 包住它，`Gdiplus::Graphics` 里 `RotateTransform` + `DrawString`。画完：
  `UpdateLayeredWindow(hwnd, hdcScreen, &ptDst, &size, hdcSrc, &ptSrc, 0, &blend, ULW_ALPHA)`，
  `blend = { AC_SRC_OVER, 0, 255, AC_SRC_ALPHA }`。
  **注意**：DIB 像素必须是预乘 alpha，GDI+ 在 PARGB 上画会自动预乘。
  > 补充（C++ 版实测踩坑后补的）：如果你自己包的 DIB 调不出来，换成「GDI+ 自管
  > `Bitmap(w, h, PixelFormat32bppPARGB)` 渲染 → `GetHBITMAP` 取句柄贴图」也完全可以，C++ 版用的就是这条。
  > **两条路都行**，判定标准只有一个：贴上去的位图是预乘 alpha，且 `UpdateLayeredWindow` 返回非 0。
  > 别把「这条 DIB 路在我这儿返回 err=31 所以不通」当成通用结论 —— Rust 版走 DIB 那条路是好的，
  > 说明多数时候是自己代码里的 stride / 句柄 / alpha 写错了。
- **重绘策略**：配置变、显示器变、模板变量跳变才重画；另外 `SetTimer` 每 3 秒 `SetWindowPos(HWND_TOPMOST, SWP_NOACTIVATE|SWP_NOMOVE|SWP_NOSIZE)` 顶一下，防止被别的全屏程序压下去。
- **GDI+ 初始化**：`GdiplusStartup` 一次，退出 `GdiplusShutdown`。中文字体从配置来，失败回退 `Microsoft YaHei` / `SimSun`。
- **manifest**：`dpiAwareness = PerMonitorV2` + Common Controls v6 依赖，写在 `res/app.rc` 里。
- **设置窗口**：原生控件（EDIT / BUTTON / TRACKBAR / COMBOBOX / STATIC）。TRACKBAR 要先 `InitCommonControlsEx(ICC_BAR_CLASSES)`。`WM_HSCROLL` / `EN_CHANGE` 里立即刷新水印。
- **单实例**：`CreateMutexW`，已存在就唤起已有实例然后退出。
- **托盘**：`CreatePopupMenu` + `AppendMenuW`，菜单弹出前先 `SetForegroundWindow`；退出时 `NIM_DELETE`。
- **不可以一闪就退**：`WM_CREATE` 失败要有 `MessageBoxW` 报错。
- 全部窗口过程用 Unicode（`-municode` + `wWinMain`），字符串统一 `std::wstring`。

## 10. Rust 实现（`legacy/rust/`，已冻结）

- **零第三方 crate**。刻意不引 `windows` / `serde` / `serde_json`：FFI 声明手写，JSON 读写手写。
  好处是不用连 crates.io，编译快，exe 小，也省得被别人的版本号绑架。
- 目标三元组：`x86_64-pc-windows-gnu`（本机 MinGW-w64 g++ 15.1 已经装好，链接走 gcc）。
  MSVC 工具链没装，用 MSVC 目标会链接失败。
- `edition = "2021"`，`#![windows_subsystem = "windows"]`，`[profile.release]` 里开 `lto = true`、`strip = true`、`panic = "abort"`、`opt-level = 3`。
- 目录结构：

```
rust/
├── Cargo.toml
├── build.bat                # windres 编 rc → cargo rustc --release -- -C link-arg=<app.res>
├── tools/make_icon.py       # 用 Python + Pillow 生成 res/app.ico
├── res/
│   ├── app.rc               # 图标 + manifest（PerMonitorV2、Common Controls v6）
│   └── app.ico
└── src/
    ├── main.rs              # 入口、单实例、消息循环、快捷键
    ├── ffi.rs               # 所有 extern "system" 声明 + 常量（user32/gdi32/gdiplus/shell32/advapi32/kernel32）
    ├── config.rs            # 配置结构体 + 手写 JSON 读写 + 模板变量
    ├── render.rs            # 平铺参数计算 + GDI+ 画到 32bpp PARGB DIB
    ├── overlay.rs           # 每显示器一个分层窗口
    ├── tray.rs              # Shell_NotifyIcon + 右键菜单
    ├── settings.rs          # 原生设置窗口（CreateWindowEx 控件）
    └── util.rs              # 宽字符串、DPI、显示器枚举、模板变量、自启
```

编译形状（`build.bat` 里就是这些）：

```bat
windres res\app.rc -O coff -o build\app.res
cargo rustc --release -- -C link-arg=%CD%\build\app.res
```

关键实现要求：

- **分层窗口**：`WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TOPMOST` + `WS_POPUP`。
- **画法**：`CreateDIBSection`（32bpp、`BI_RGB`、**负高度 top-down**）拿到像素指针，用 GDI+ 的 flat API 画：
  `GdipCreateFromHDC` → `GdipSetSmoothingMode(AntiAlias)` → `GdipCreateFontFamilyFromName` / `GdipCreateFont` / `GdipCreateSolidFill`（ARGB 带 alpha）
  → 每个单元 `GdipTranslateWorldTransform` + `GdipRotateWorldTransform` + `GdipDrawString`，画完复位变换。
  最后 `UpdateLayeredWindow(hwnd, screen_dc, &pt_dst, &size, mem_dc, &pt_src, 0, &blend, ULW_ALPHA)`，
  `blend = BLENDFUNCTION { BlendOp: AC_SRC_OVER, BlendFlags: 0, SourceConstantAlpha: 255, AlphaFormat: AC_SRC_ALPHA }`。
  **DIB 像素必须是预乘 alpha**，GDI+ 在 PARGB 上画会自动预乘。
- **GDI+ flat API 的字符串**：`GdipCreateFontFamilyFromName` / `GdipDrawString` 收的是 UTF-16 宽字符指针，直接传 `*const u16`，注意长度参数用**字符数**不是字节数。
- **GDI+ 初始化**：`GdiplusStartup` 一次，退出 `GdiplusShutdown`。
- **宽字符串**：全部 `Vec<u16>` + 末尾 0，包个小工具函数 `to_wide(&str) -> Vec<u16>`，别到处手搓。
- **重绘策略**：配置变、显示器变、模板变量跳变才重画；`SetTimer` 每 3 秒 `SetWindowPos(HWND_TOPMOST, SWP_NOACTIVATE|SWP_NOMOVE|SWP_NOSIZE)` 顶一下。
- **设置窗口**：原生控件（EDIT / BUTTON / TRACKBAR / COMBOBOX / STATIC），`InitCommonControlsEx(ICC_BAR_CLASSES)`，`WM_HSCROLL` / `EN_CHANGE` 里实时刷新水印。
- **托盘**：`Shell_NotifyIconW` + `CreatePopupMenu` / `AppendMenuW`，菜单弹出前 `SetForegroundWindow`，退出 `NIM_DELETE`。
- **单实例**：`CreateMutexW`，已存在就退出。
- **JSON**：手写解析器要能处理 `\" \\ \/ \b \f \n \r \t \uXXXX` 转义、中文、数字/布尔/null；写回时**保留未知字段**（用一个有序的键值表）。文件读写 UTF-8 **无 BOM**。
- **unsafe**：FFI 免不了，但把 unsafe 收敛到 `ffi.rs` 和少量薄封装里，业务逻辑尽量写安全代码。不许用 `unwrap()` 处理用户输入。
- 中文注释，说"为什么"，不写 emoji。启动致命错误用 `MessageBoxW` 报出来。

## 11. 四个实现都要有的东西

- 中文注释可以，但注释要说人话（说"为什么"，不是把代码翻译一遍）。
- 不写死路径；配置和日志都相对 exe/脚本。
- `--version` / `-v` 打印版本号；Python 端还要支持 `--text "xxx"` 临时覆盖、`--no-tray` 只跑水印。
- 出错打印到 stderr，别用弹窗烦人（除了启动致命错误）。

## 12. 验收标准

1. 双击/`python main.py` 就能看到水印，默认参数下不难看。
2. 鼠标能点穿水印操作桌面图标。
3. 设置面板改任何参数，水印立刻变。
4. 快捷键 `Ctrl+Alt+W` 能开关。
5. 关掉面板程序还在，托盘还在。
6. 配置存下来，重启后参数还在。
7. 多显示器时每块屏都有水印。
8. 两个实现生成的 `config.json` 可以互换使用。
9. 内存占用：静置 5 分钟不涨（Python < 120MB，C++ < 40MB）。
10. CPU：静置时接近 0%（不能靠定时全屏重绘续命）。