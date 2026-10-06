# ScreenWatermark · Rust 实现

> **本实现已冻结在 1.0.0，不再更新。**
> 项目现在只维护 [C++ 版](../../cpp/)。这个 Rust 版还能正常编译运行，
> 但新配置项、新行为不会再同步过来。留着当参考实现。

Windows 屏幕水印工具，Rust 版。**零第三方 crate** —— 不连 crates.io，FFI 手写，
JSON 手写，所以编译快、exe 小、不会被依赖版本号绑架。

行为规格见 [`../docs/DESIGN.md`](../../docs/DESIGN.md)（§10 是 Rust 专属章节）。
本 README 只讲"怎么编、怎么跑、哪里不一样"。

## 怎么编

双击 `build.bat`，或者：

```bat
cd legacy\rust
build.bat
```

它做两件事：

```bat
windres res\app.rc -O coff -o build\app.res
cargo rustc --release -- -C link-arg=%CD%\build\app.res
```

产物：**`rust\target\release\ScreenWatermark.exe`**（约 500 KB）。

### 工具链要求

| 需要 | 本机实测 |
| --- | --- |
| Rust target | `x86_64-pc-windows-gnu`（**不是 MSVC**，本机没装 VS） |
| 链接器 | `gcc.exe`（MinGW-w64 15.1，`D:\MinGW\bin`） |
| 资源编译器 | `windres.exe`（同目录） |
| 图标生成 | Python 3 + Pillow（可选，`res/app.ico` 已在仓库里） |

`build.bat` 会自己把 `%USERPROFILE%\.cargo\bin` 和 `D:\MinGW\bin` 加进 PATH，
并用 `RUSTUP_TOOLCHAIN=stable-x86_64-pc-windows-gnu` 指定工具链。
**刻意不放 `rust-toolchain.toml`**：那个文件会让 rustup 每次都想同步整个 channel，
网不好时会卡住甚至把工具链装坏。

如果 `res/app.ico` 丢了：

```bat
python tools\make_icon.py
```

## 怎么跑

```bat
target\release\ScreenWatermark.exe
```

双击即可，第一次运行**不需要任何配置**，会直接按默认值出水印
（灰色斜排"内部资料 请勿外传"）。配置文件在执行时按需生成，不会预先污染构建产物。

### 命令行参数

| 参数 | 作用 |
| --- | --- |
| `--version` / `-v` | 打印版本号 |
| `--help` / `-h` | 打印用法 |
| `--text "xxx"` | 临时覆盖水印文字（不写回配置） |
| `--settings` | 启动时直接打开设置面板 |
| `--probe` | 挂上水印后把窗口句柄/尺寸/扩展样式打到 stdout 并退出 |
| `--save-config` | 按当前配置写一份 `config.json` 后退出 |
| `--selftest` | 全屏截图并统计灰色水印像素比例，然后退出 |
| `--log` | 往 exe 同级目录写 `rust-debug.log` |

`--probe` / `--save-config` / `--selftest` 是**一次性诊断模式**，
不会被单实例互斥体挡住，可以随时跑。

### 快捷键

| 首选 | 降级（首选被占用时自动切换） | 作用 |
| --- | --- | --- |
| `Ctrl+Alt+W` | `Ctrl+Alt+Shift+W` | 显示 / 隐藏水印 |
| `Ctrl+Alt+S` | `Ctrl+Alt+Shift+S` | 开关设置面板 |
| `Ctrl+Alt+Q` | `Ctrl+Alt+Shift+Q` | 退出程序 |

**热键会自动降级，而且实际生效的组合到处都写清楚**（日志、`--probe`、设置面板底部提示行）。
原因是 `Ctrl+Alt+W` / `Ctrl+Alt+Q` 在不少机器上已被别的常驻软件永久占用
（本机实测就是 `RegisterHotKey` 返回 `1409`，把本程序全部杀掉后依然如此）。
首选失败就试 `Ctrl+Alt+Shift+*`；两个都失败就记一条日志说"该动作只能用托盘菜单"，
程序照常运行，不因为热键抢不到就罢工。

> 别拿 `RegisterHotKey(hWnd=NULL, id, mods, vk)` 的返回值当"这个组合没人用"的证据：
> 实测在别的进程已经用**真实窗口**注册了同一组合时，NULL 窗口的探测仍然会返回成功。
> 想判断"我到底抢到了什么"，直接看 `RegisterHotKey` 的返回值 + `GetLastError`
> —— 也就是 `--probe` 和日志里报的那些，而不是另起一个探测。

托盘图标：左键双击开面板，右键出菜单（显示/隐藏、设置、重新载入配置、开机自启、退出）。
**关掉设置面板不会退出程序**，只是把面板窗口 `ShowWindow(SW_HIDE)`，
下次再按面板热键复用同一个窗口句柄。

### 水印窗口的显示状态只有一个来源

窗口创建时保持隐藏，由 `render_all()` 在真正贴上内容那一刻 `ShowWindow` 显示。
隐藏走 `SW_HIDE`（会清掉 `WS_VISIBLE`），所以从隐藏切回显示时必须**显式再 `ShowWindow` 一次**
—— `UpdateLayeredWindow` 只更新分层内容，不会把窗口重新显示出来。
少了这一步，"隐藏一次再打开"之后水印就再也回不来了。

## 目录结构

```
rust/
├── Cargo.toml          # [dependencies] 是空的，这是刻意的
├── build.rs            # 补 -mwindows 和 -static-libgcc/-static-libstdc++
├── build.bat           # 一键构建（windres + cargo rustc）
├── tools/
│   ├── make_icon.py    # 生成 res/app.ico（Pillow）
│   ├── analyze_shot.py # 统计截图里的灰色水印像素比例
│   ├── hotkey_test.py  # 合成按键验证全局热键 + 枚举水印窗口扩展样式（支持 --start 自己拉起 exe）
│   ├── probe.py        # 独立进程探测全局热键占用（严格 use_last_error）
│   └── dump_controls.py# 列出设置面板所有子控件及其矩形
├── res/
│   ├── app.rc          # 图标 + manifest（PerMonitorV2、Common Controls v6）
│   ├── app.manifest
│   └── app.ico
└── src/
    ├── main.rs         # 入口、单实例、消息循环、控制器、一次性诊断模式
    ├── ffi.rs          # 全部 extern "system"/"C" 声明 + 常量 + 结构体
    ├── config.rs       # 配置结构体 + 手写 JSON 解析/序列化
    ├── render.rs       # 平铺参数计算 + GDI+ flat API 画 32bpp PARGB DIB
    ├── overlay.rs      # 每显示器一个分层窗口 + UpdateLayeredWindow
    ├── tray.rs         # Shell_NotifyIconW + CreatePopupMenu
    ├── settings.rs     # 原生设置面板（EDIT/BUTTON/TRACKBAR/COMBOBOX/STATIC）
    ├── dispatch.rs     # 隐藏消息窗口、全局热键注册、消息循环
    ├── util.rs         # 宽字符串、显示器枚举、模板变量、自启、strftime
    └── log.rs          # 极简日志（默认不写文件）
```

## 实现要点（和别的版本不一样的地方）

### 逐像素透明，不是 TransparencyKey

`WS_EX_LAYERED` + `UpdateLayeredWindow` + 32bpp 预乘 alpha 的 top-down DIB。
画法是 `CreateDIBSection` 拿到像素指针 → `GdipCreateBitmapFromScan0` 用
`PixelFormat32bppPARGB` 包住同一块内存 → GDI+ flat API 画 → `UpdateLayeredWindow`。

用 GDI+ flat API 而不是 C++ 包装类，是为了不引入任何 C++ 运行时依赖。
调用约定上 GDI+ 是 cdecl（`extern "C"`），Win32 是 stdcall（`extern "system"`）。

### 旋转方向的坑

DESIGN §2 规定 `angle` **逆时针为正**，而 GDI+ 的 `GdipRotateWorldTransform`
是顺时针为正，所以代码里传的是 `-angle`。变换顺序是
"先平移、再旋转"（`MatrixOrderPrepend` 两次），和 §6 的"先平移再绕单元原点旋转"一致。

### 重绘策略

- 配置变、显示器变、模板时间跳变才重画；
- 连续拖动滑块时靠主循环的空闲回调节流，只画最后一帧；
- `SetTimer` 每 3 秒 `SetWindowPos(HWND_TOPMOST, SWP_NOACTIVATE|SWP_NOMOVE|SWP_NOSIZE)`
  顶一下，防止被别的全屏程序压下去；
- 重画时**不销毁重建窗口**，只换位图（换之前先 `dispose` 旧的，否则每次都漏一张图）。

### 单元数上限

极端角度/间距下网格会爆炸，`MAX_CELLS = 20000` 兜底，到了就停手，
不让一次重绘把界面卡死。实际绘制数量会如实报在 `--log` 的输出里。

### 设置面板的 DPI 缩放

面板控件坐标全部按 **96 DPI 的逻辑像素**写，再经 `scaled()` 换算成物理像素。
控件字体也自己用 `CreateFontW` 按 DPI 造一个 —— `GetStockObject(DEFAULT_GUI_FONT)`
在 per-monitor DPI 下不缩放，175% 屏幕上只有 12 物理像素高，
TRACKBAR 还会把自身高度夹到字体高度，滑轨会细成一条线看不清。

### 配置写回保留未知字段

手写 JSON 解析器覆盖 `\" \\ \/ \b \f \n \r \t \uXXXX`（含代理对）、中文、
嵌套对象/数组。反序列化时不认识的键按"原始 JSON 片段"存进 `BTreeMap`，
写回时原样拼在已知字段后面，所以 C#/Python 版加的新字段不会被我们吃掉。
文件是 UTF-8 **无 BOM**，先写 `.tmp` 再改名，避免写一半断电弄出半个 JSON。

解析失败时坏文件会被改名成 `config.bad.json`，然后按默认值继续跑，不崩。

### 已知取舍

- **配置不预先写盘**：`config.json` 只在用户真的改了参数（应用/保存、切水印、
  切自启、重载）时才生成。这样干净解压不会凭空多一个文件，代价是"从未动过配置"
  的那次运行不会留下文件。
- **单屏 DPI**：多显示器不同缩放时，渲染 DPI 取的是主屏 DPI，
  没有按每块屏各自的 DPI 分别计算字体大小。
- **托盘提示文字**只在显示/隐藏切换时更新，不做气泡通知。
- **热键可能全部抢不到**：四个实现同时在跑时会互相抢同一组组合，抢输的一方
  在日志里会写"注册失败（错误码 1409），该动作只能用托盘菜单"。
  这是如实上报，不是故障 —— 独占热键本来就只有一个进程能拿到。

## 验收怎么复现

```bat
cd legacy\rust
build.bat

rem 1) 窗口和扩展样式（不用外部工具，进程内直接报）
target\release\ScreenWatermark.exe --probe

rem 2) 配置格式
target\release\ScreenWatermark.exe --save-config
type target\release\config.json

rem 3) 全局热键：先看本程序实际抢到了哪些组合
target\release\ScreenWatermark.exe --probe

rem    再启动它，用真实按键验证（会真的合成按键）
python tools\hotkey_test.py --start target\release\ScreenWatermark.exe

rem    想看这台机器上哪些组合被别的软件占了（先杀掉所有水印进程再跑）：
python tools\probe.py

rem 4) 设置面板控件清单
target\release\ScreenWatermark.exe --settings
python tools\dump_controls.py <pid>

rem 5) 水印可见性 + 灰色像素比例
rem    先手动截一张全屏 PNG，然后：
python tools\analyze_shot.py <shot.png>
```

`docs/shots/rust-verify.png` 是实测截图，2520×1680 物理像素下
统计到 22465 个灰色水印像素（0.5306%）。

## 许可

AGPL-3.0-or-later，与仓库根目录一致。
