// AppController.cs —— 控制器。把配置、水印窗口、托盘、设置面板、快捷键、定时器串起来。
//
// 为什么继承 ApplicationContext 而不是跑一个主窗体：
// 本程序没有"主窗口"，生命周期由托盘和快捷键决定。ApplicationContext 正好表达这件事，
// 而且 Application.Run(ctx) 会一直跑消息循环到 ExitThread 被调用为止。
using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Windows.Forms;
using Microsoft.Win32;

namespace ScreenWatermark
{
    /// <summary>专门用来收 WM_HOTKEY 的 overlay。快捷键注册在那个窗口句柄上，消息就回到这里。</summary>
    internal sealed class HotkeySink : OverlayForm
    {
        public Action<int> OnHotkey;

        public HotkeySink(Screen screen, int dpi) : base(screen, dpi) { }

        protected override void WndProc(ref Message m)
        {
            if (m.Msg == NativeMethods.WM_HOTKEY)
            {
                if (OnHotkey != null) OnHotkey(m.WParam.ToInt32());
                return;
            }
            base.WndProc(ref m);
        }
    }

    internal sealed class AppController : ApplicationContext
    {
        // 快捷键 id。0x5701 这种值没有特殊含义，只要在一轮进程里唯一即可。
        private const int HotkeyToggleVisible = 0x5701;
        private const int HotkeyToggleSettings = 0x5702;
        private const int HotkeyQuit = 0x5703;

        private const string RunKeyPath = @"Software\Microsoft\Windows\CurrentVersion\Run";
        private const string RunValueName = "ScreenWatermark";

        private Config _config;
        private readonly string _startupConfigPath;
        private readonly bool _forceDefaultConfig;

        private readonly List<OverlayForm> _overlays = new List<OverlayForm>();
        private HotkeySink _hotkeySink;
        private int _lastScreenSignature = int.MinValue;

        private TrayIcon _tray;
        private SettingsForm _settings;
        private Timer _refreshTimer;
        private Timer _topmostTimer;

        private string _lastRenderKey;
        private string _lastResolvedText;
        private bool _disposed;

        // 用户在当前这一轮里手动切过显示状态没有。切过就不再让磁盘配置覆盖它。
        private bool _userToggledEnabled;
        // 用户最后一次手动切显示状态的时间。用来判断"配置文件和用户的意图谁更新"。
        private DateTime _lastToggleUtc = DateTime.MinValue;

        public AppController(string configPath, bool forceDefault)
        {
            _startupConfigPath = configPath;
            _forceDefaultConfig = forceDefault;

            _config = Config.Load(configPath, forceDefault);
            if (_config.LoadError != null) WriteStderr("配置: " + _config.LoadError);

            // 首次运行 / 配置缺失：立刻落一份默认配置，这样 Python 版和用户都能看到文件长什么样。
            if (!File.Exists(_config.LoadedFrom))
            {
                string used, err;
                if (!_config.Save(out used, out err) && err != null) WriteStderr("写默认配置失败: " + err);
            }

            BuildTray();
            // 托盘菜单要反映注册表里的真实状态，不能只信配置里那个可能过期的布尔值。
            _config.Autostart = ReadAutostart();
            RebuildOverlays(true);
            RegisterHotkeys();

            // 模板刷新：只有 {time} 类变量才会真的让画面变，所以在 Tick 里比对文本再决定重画。
            _refreshTimer = new Timer();
            _refreshTimer.Interval = Math.Max(5, _config.RefreshSeconds) * 1000;
            _refreshTimer.Tick += delegate { OnRefreshTick(); };
            _refreshTimer.Start();

            // 规格 §8：每 3 秒重新顶到最前面。有些全屏程序会把自己插到最上层。
            _topmostTimer = new Timer();
            _topmostTimer.Interval = 3000;
            _topmostTimer.Tick += delegate { RefreshTopmost(); };
            _topmostTimer.Start();

            // 显示器插拔 / 分辨率变化 → 全部重建。
            Microsoft.Win32.SystemEvents.DisplaySettingsChanged += OnDisplaySettingsChanged;
            Microsoft.Win32.SystemEvents.UserPreferenceChanged += OnUserPreferenceChanged;

            WatchConfigFile();
            ApplyColorsToSettings();
        }

        // ================= 托盘 =================

        private void BuildTray()
        {
            _tray = new TrayIcon();
            _tray.OnToggleVisible = ToggleVisible;
            _tray.OnOpenSettings = ToggleSettings;
            _tray.OnReloadConfig = ReloadConfig;
            _tray.OnToggleAutostart = SetAutostart;
            _tray.OnExit = Quit;
            _tray.UpdateState(_config.Enabled, _config.Autostart);
        }

        // ================= overlay 窗口 =================

        /// <summary>
        /// 按 all_monitors 决定要覆盖哪几块屏。显示器集合变了就整组重建，
        /// 因为窗口尺寸在 UpdateLayeredWindow 里是绑死的，改不如重建干净。
        /// </summary>
        private void RebuildOverlays(bool force)
        {
            Screen[] wanted = WantedScreens();
            int signature = ScreenSignature(wanted, _config.AllMonitors);
            if (!force && signature == _lastScreenSignature && _overlays.Count == wanted.Length)
            {
                // 屏幕没变：只同步穿透开关，然后按需重画。
                for (int i = 0; i < _overlays.Count; i++)
                    _overlays[i].SetClickThrough(_config.ClickThrough);
                RenderAll(false);
                return;
            }

            DestroyOverlays();

            for (int i = 0; i < wanted.Length; i++)
            {
                Screen sc = wanted[i];
                int dpi = QueryDpiForBounds(sc.Bounds);
                HotkeySink sink = new HotkeySink(sc, dpi);
                sink.OnHotkey = HandleHotkey;
                sink.SetClickThrough(_config.ClickThrough);
                if (i == 0) _hotkeySink = sink;
                _overlays.Add(sink);
                sink.Show();
                // Show() 之后再贴图：UpdateLayeredWindow 需要有效的 HWND，
                // 而且第一次贴完才让窗口出现在正确位置（构造时放在屏幕外了）。
                sink.MoveTo(sc.Bounds);
            }

            _lastScreenSignature = signature;
            _lastRenderKey = null; // 新窗口没有内容，强制重画
            RenderAll(true);
            RegisterHotkeys(); // 句柄换了，热键要挂到新窗口上
        }

        private Screen[] WantedScreens()
        {
            Screen[] all = Screen.AllScreens;
            if (_config.AllMonitors || all.Length == 0) return all;

            for (int i = 0; i < all.Length; i++)
                if (all[i].Primary) return new Screen[] { all[i] };
            return new Screen[] { all[0] };
        }

        private static int ScreenSignature(Screen[] screens, bool allMonitors)
        {
            // 简单累加哈希：只要几何或数量变了就会变，够用，不用加密级强度。
            int h = allMonitors ? 17 : 31;
            for (int i = 0; i < screens.Length; i++)
            {
                Rectangle b = screens[i].Bounds;
                h = h * 31 + b.X;
                h = h * 31 + b.Y;
                h = h * 31 + b.Width;
                h = h * 31 + b.Height;
            }
            return h;
        }

        private static int QueryDpiForBounds(Rectangle bounds)
        {
            // 用一个常驻的 1px 不可见窗口去问：把窗口挪到那块屏上，GetDpiForWindow 就返回
            // 那块屏的 DPI。比 SetProcessDpiAwarenessContext 那套老 API 简单且准确。
            IntPtr hwnd = EnsureDpiProbe();
            if (hwnd == IntPtr.Zero) return 96;

            try
            {
                // 挪之前先藏起来：PerMonitorV2 下跨屏移动会触发 WM_DPICHANGED，
                // 一个看得见的 1px 窗口在屏幕上闪一下很难看。
                NativeMethods.SetWindowPos(hwnd, IntPtr.Zero, -30000, -30000, 1, 1,
                    NativeMethods.SWP_NOACTIVATE | NativeMethods.SWP_NOOWNERZORDER);
                NativeMethods.SetWindowPos(hwnd, IntPtr.Zero, bounds.X + 1, bounds.Y + 1, 1, 1,
                    NativeMethods.SWP_NOACTIVATE | NativeMethods.SWP_NOOWNERZORDER);
                uint dpi = NativeMethods.GetDpiForWindow(hwnd);
                if (dpi >= 72 && dpi <= 480) return (int)dpi;
            }
            catch (Exception) { }
            return 96;
        }

        // 常驻探针窗口：每块屏都建/销一次窗口太浪费，进程里留一个复用。
        private static Form _dpiProbe;

        private static IntPtr EnsureDpiProbe()
        {
            if (_dpiProbe == null || _dpiProbe.IsDisposed)
            {
                _dpiProbe = new Form();
                _dpiProbe.FormBorderStyle = FormBorderStyle.None;
                _dpiProbe.ShowInTaskbar = false;
                _dpiProbe.StartPosition = FormStartPosition.Manual;
                _dpiProbe.SetBounds(-30000, -30000, 1, 1);
                _dpiProbe.Show();
            }
            return _dpiProbe.Handle;
        }

        private void DestroyOverlays()
        {
            for (int i = 0; i < _overlays.Count; i++)
            {
                try
                {
                    _overlays[i].Hide();
                    _overlays[i].Dispose();
                }
                catch (Exception) { }
            }
            _overlays.Clear();
            _hotkeySink = null;
        }

        // ================= 渲染 =================

        private void OnRefreshTick()
        {
            if (!_config.Enabled) return;
            string now = _config.ResolvedText();
            if (!string.Equals(now, _lastResolvedText, StringComparison.Ordinal))
            {
                // 只有模板变量真的跳变了才重画（规格 §8 的重绘策略）。
                RenderAll(true);
            }
        }

        private void RefreshTopmost()
        {
            for (int i = 0; i < _overlays.Count; i++) _overlays[i].RefreshTopmost();
        }

        /// <summary>
        /// 重画。force=false 时先比渲染特征串，一模一样就直接返回 ——
        /// 这是"静置时 CPU 接近 0"的关键，不能每次调用都无条件重画。
        /// </summary>
        private void RenderAll(bool force)
        {
            if (_overlays.Count == 0) return;

            string resolved = _config.ResolvedText();
            _lastResolvedText = resolved;

            if (!_config.Enabled)
            {
                // 关闭显示：给每块屏一张全透明的图，窗口还在（快捷键要活着）但什么都看不见。
                if (force || _lastRenderKey != "off")
                {
                    for (int i = 0; i < _overlays.Count; i++)
                    {
                        OverlayForm ov = _overlays[i];
                        WatermarkTile empty = WatermarkRenderer.Render(
                            ov.ScreenInfo.Bounds.Width, ov.ScreenInfo.Bounds.Height,
                            string.Empty, _config.FontFamily, _config.FontSize, _config.Bold, _config.Italic,
                            Color.Black, 0.0, 0, 0, 0, 1.0, false, 96f);
                        ov.SetTile(empty);
                    }
                    _lastRenderKey = "off";
                }
                return;
            }

            string key = RenderKey(resolved);
            if (!force && key == _lastRenderKey) return;

            for (int i = 0; i < _overlays.Count; i++)
            {
                OverlayForm ov = _overlays[i];
                Rectangle b = ov.ScreenInfo.Bounds;
                WatermarkTile tile = WatermarkRenderer.Render(
                    b.Width, b.Height,
                    resolved,
                    _config.FontFamily,
                    _config.FontSize,
                    _config.Bold,
                    _config.Italic,
                    _config.ParseColor(),
                    _config.Opacity,
                    _config.Angle,
                    _config.GapX,
                    _config.GapY,
                    _config.LineSpacing,
                    _config.PhaseOffset,
                    ov.Dpi);

                // SetTile 会把上一张位图 Dispose 掉 —— 内存不涨靠的就是这句。
                ov.SetTile(tile);
                if (!ov.LastUpdateOk) WriteStderr("UpdateLayeredWindow 失败, err=" + ov.LastUpdateError);
            }

            _lastRenderKey = key;
        }

        private string RenderKey(string resolved)
        {
            // 把所有会改变像素的参数都串进来。多一块屏但参数没变时，屏幕特征串会变，
            // 而屏幕变化本身就走了 RebuildOverlays 且会 force=true，所以这里不用重复算。
            return string.Format(System.Globalization.CultureInfo.InvariantCulture,
                "{0}|{1}|{2}|{3}|{4}|{5}|{6}|{7}|{8}|{9}|{10}|{11}|{12}",
                resolved, _config.FontFamily, _config.FontSize, _config.Bold, _config.Italic,
                _config.Color, _config.Opacity, _config.Angle, _config.GapX, _config.GapY,
                _config.LineSpacing, _config.PhaseOffset, _config.AllMonitors ? 1 : 0);
        }

        // ================= 快捷键 =================
        //
        // DESIGN.md §4 的热键降级：Ctrl+Alt+W / Ctrl+Alt+Q 在很多机器上早被别的常驻软件占了
        // （本机实测 RegisterHotKey 返回 1409，把本程序全杀光之后依然如此）。
        // 所以首选组合注册失败时必须退一级去试 Ctrl+Alt+Shift+X，否则用户按半天没反应还找不到原因。

        /// <summary>一个动作实际生效的按键组合。</summary>
        private sealed class HotkeyBinding
        {
            public int Id;
            public string Action;       // 给日志和面板提示用的人话
            public uint Modifiers;      // 不含 MOD_NOREPEAT
            public uint Key;            // 虚拟键码
            public string Display;      // "Ctrl+Alt+W"
        }

        private readonly List<HotkeyBinding> _hotkeyBindings = new List<HotkeyBinding>();
        private IntPtr _hotkeyHwnd = IntPtr.Zero;

        /// <summary>
        /// 试注册一个动作：先试首选组合，失败就退到带 Shift 的备用组合。
        /// 两次都失败只记日志并返回 null —— 托盘和设置面板还能用，绝不能因此影响运行。
        /// </summary>
        private HotkeyBinding TryBind(int id, string action, uint key, string primaryName, string fallbackName)
        {
            IntPtr hwnd = _hotkeyHwnd;
            uint primary = NativeMethods.MOD_CONTROL | NativeMethods.MOD_ALT | NativeMethods.MOD_NOREPEAT;

            if (NativeMethods.RegisterHotKey(hwnd, id, primary, key))
            {
                HotkeyBinding ok = new HotkeyBinding();
                ok.Id = id;
                ok.Action = action;
                ok.Modifiers = primary & ~NativeMethods.MOD_NOREPEAT;
                ok.Key = key;
                ok.Display = primaryName;
                _hotkeyBindings.Add(ok);
                return ok;
            }

            int primaryErr = System.Runtime.InteropServices.Marshal.GetLastWin32Error();

            uint fallback = primary | NativeMethods.MOD_SHIFT;
            if (NativeMethods.RegisterHotKey(hwnd, id, fallback, key))
            {
                HotkeyBinding ok = new HotkeyBinding();
                ok.Id = id;
                ok.Action = action;
                ok.Modifiers = fallback & ~NativeMethods.MOD_NOREPEAT;
                ok.Key = key;
                ok.Display = fallbackName;
                _hotkeyBindings.Add(ok);
                WriteStderr(string.Format(
                    "{0}: {1} 被占用(Win32 错误 {2})，已降级到 {3}。",
                    action, primaryName, primaryErr, fallbackName));
                return ok;
            }

            int fallbackErr = System.Runtime.InteropServices.Marshal.GetLastWin32Error();
            WriteStderr(string.Format(
                "{0}: {1} 与 {2} 都注册失败(错误 {3} / {4})，该动作只能用托盘或设置面板。",
                action, primaryName, fallbackName, primaryErr, fallbackErr));
            return null;
        }

        private void RegisterHotkeys()
        {
            IntPtr hwnd = _hotkeySink != null ? _hotkeySink.Handle : IntPtr.Zero;
            if (hwnd == IntPtr.Zero && _settings != null && _settings.IsHandleCreated)
            {
                // 一块屏都没有 overlay 的极端情况：退回设置面板的句柄，至少快捷键还能用。
                hwnd = _settings.Handle;
            }
            if (hwnd == IntPtr.Zero) return;

            // 句柄换了（overlay 重建）必须重新注册：RegisterHotKey 是绑在具体窗口上的。
            if (hwnd == _hotkeyHwnd && _hotkeyBindings.Count > 0) return;

            UnregisterHotkeys();
            _hotkeyHwnd = hwnd;

            uint vkW = (uint)Keys.W;
            uint vkS = (uint)Keys.S;
            uint vkQ = (uint)Keys.Q;

            TryBind(HotkeyToggleVisible, "开关水印", vkW, "Ctrl+Alt+W", "Ctrl+Alt+Shift+W");
            TryBind(HotkeyToggleSettings, "设置面板", vkS, "Ctrl+Alt+S", "Ctrl+Alt+Shift+S");
            TryBind(HotkeyQuit, "退出程序", vkQ, "Ctrl+Alt+Q", "Ctrl+Alt+Shift+Q");

            if (_hotkeyBindings.Count == 0)
            {
                WriteStderr("RegisterHotKey：三组快捷键全部注册失败，请改用托盘图标。");
                if (_tray != null)
                    _tray.ShowBalloon("快捷键不可用", "Ctrl+Alt+W/S/Q 都被别的程序占用了，请改用托盘图标。");
            }
            else
            {
                WriteStderr("生效的快捷键：" + HotkeySummary());
            }

            // 面板底部那行提示要显示"实际生效"的组合。
            if (_settings != null) _settings.SetHotkeyInfo(HotkeySummary());
        }

        /// <summary>把实际生效的组合拼成一行，给日志和设置面板用。</summary>
        public string HotkeySummary()
        {
            if (_hotkeyBindings.Count == 0) return "快捷键未生效（被占用），请用托盘图标";

            List<string> parts = new List<string>();
            for (int i = 0; i < _hotkeyBindings.Count; i++)
            {
                HotkeyBinding b = _hotkeyBindings[i];
                parts.Add(b.Display + " " + b.Action);
            }
            return string.Join(" · ", parts.ToArray());
        }

        private void UnregisterHotkeys()
        {
            if (_hotkeyHwnd == IntPtr.Zero) return;

            for (int i = 0; i < _hotkeyBindings.Count; i++)
                NativeMethods.UnregisterHotKey(_hotkeyHwnd, _hotkeyBindings[i].Id);

            _hotkeyBindings.Clear();
            _hotkeyHwnd = IntPtr.Zero;
        }

        private void HandleHotkey(int id)
        {
            // 收到没收到要能在日志里看见：热键"按了没反应"是最难查的一类问题 ——
            // 可能是没注册上，可能是被别的程序截走了，也可能是动作自己抛异常。
            // 打一行日志就能把这三者区分开。
            WriteStderr("收到快捷键 id=" + id + " -> " + HotkeyActionName(id));

            switch (id)
            {
                case HotkeyToggleVisible: ToggleVisible(); break;
                case HotkeyToggleSettings: ToggleSettings(); break;
                case HotkeyQuit: Quit(); break;
            }
        }

        private static string HotkeyActionName(int id)
        {
            if (id == HotkeyToggleVisible) return "开关水印";
            if (id == HotkeyToggleSettings) return "设置面板";
            if (id == HotkeyQuit) return "退出程序";
            return "未知动作";
        }

        // ================= 用户操作 =================

        private void ToggleVisible()
        {
            SetEnabled(!_config.Enabled);
        }

        private void SetEnabled(bool on)
        {
            WriteStderr("SetEnabled(" + (on ? "true" : "false") + ") 当前=" + (_config.Enabled ? "true" : "false"));
            if (_config.Enabled == on)
            {
                SyncUiState();
                return;
            }
            _config.Enabled = on;
            _userToggledEnabled = true;
            _lastToggleUtc = DateTime.UtcNow;
            _lastRenderKey = null; // 强制翻转
            RenderAll(true);
            SyncUiState();
            WriteStderr("SetEnabled 完成，现在=" + (_config.Enabled ? "true" : "false"));
        }

        private void ToggleSettings()
        {
            if (_settings == null)
            {
                _settings = new SettingsForm(_config);
                _settings.OnPreview = delegate
                {
                    _settings.WriteToConfig(_config);
                    _lastRenderKey = null;
                    ApplyLiveChanges();
                };
                _settings.OnApply = delegate
                {
                    _settings.WriteToConfig(_config);
                    ApplyLiveChanges();
                };
                _settings.OnSave = SaveConfig;
                _settings.OnToggleVisible = ToggleVisible;
                _settings.OnSetEnabled = SetEnabled;
                // 面板句柄也参与热键注册，面板先于 overlay 存在时才不会漏注册。
                _settings.HandleCreated += delegate { RegisterHotkeys(); };
            }
            _settings.SyncAll();
            _settings.SyncEnabledCheckbox();
            // 面板底部那行要写"实际生效"的组合。启动时 RegisterHotkeys() 跑在面板创建之前，
            // 而 RegisterHotkeys() 里那句 SetHotkeyInfo 又会被"句柄没变就直接 return"挡掉，
            // 所以这里必须再同步一次，否则面板一直显示首选组合，用户按 Ctrl+Alt+W 没反应会懵。
            _settings.SetHotkeyInfo(HotkeySummary());

            if (_settings.Visible)
            {
                _settings.Hide();
            }
            else
            {
                _settings.Show();
                // Show 之后窗口不一定在前台（我们全程不抢焦点），手动提到前面。
                _settings.Activate();
            }
        }

        /// <summary>实时预览 / 应用都走这里：参数变了要重画，必要时还要重建 overlay。</summary>
        private void ApplyLiveChanges()
        {
            // all_monitors 开关会改变需要覆盖的屏幕数量。
            RebuildOverlays(false);

            // 刷新间隔可能被改了，定时器跟着走。
            int ms = Math.Max(5, _config.RefreshSeconds) * 1000;
            if (_refreshTimer.Interval != ms) _refreshTimer.Interval = ms;

            // click_through 变了要同步到每块屏。
            for (int i = 0; i < _overlays.Count; i++)
                _overlays[i].SetClickThrough(_config.ClickThrough);

            if (!_config.ClickThrough)
            {
                // 不穿透意味着水印会挡住桌面。这是个调试开关，必须提醒，否则用户以为电脑坏了。
                if (_tray != null)
                    _tray.ShowBalloon("鼠标被水印挡住了",
                        "已关闭鼠标穿透，桌面点不动。取消勾选「鼠标穿透」或按 Ctrl+Alt+S 打开面板改回来。");
            }

            SyncUiState();
        }

        private void SyncUiState()
        {
            if (_tray != null) _tray.UpdateState(_config.Enabled, _config.Autostart);
            if (_settings != null && _settings.Visible) _settings.SyncEnabledCheckbox();
        }

        private void SaveConfig()
        {
            string used, err;
            bool ok = _config.Save(out used, out err);
            if (!ok)
            {
                WriteStderr("保存配置失败: " + err);
                if (_tray != null) _tray.ShowBalloon("配置保存失败", err);
                return;
            }
            if (!string.Equals(used, _startupConfigPath, StringComparison.OrdinalIgnoreCase)
                && _startupConfigPath != null)
            {
                // 回落到了 APPDATA，得让用户知道文件到底写哪去了。
                if (_tray != null) _tray.ShowBalloon("配置已存到用户目录", used);
            }
        }

        private void ReloadConfig()
        {
            ReloadConfig(true);
        }

        /// <summary>
        /// 从磁盘重读配置。notify=false 是给文件监听器用的 —— 外部编辑器一保存就弹气泡太吵。
        /// </summary>
        private void ReloadConfig(bool notify)
        {
            // enabled 归"显示状态"管，正常情况下不该被磁盘上那份旧配置覆盖回去，
            // 否则按 Ctrl+Alt+W 之后只要配置一重载就白按了。
            //
            // 但不能一刀切：用户直接改 config.json 把 enabled 写成 false 时，
            // 那份文件比"上次按快捷键"更新，应该生效。所以按时间戳比新旧：
            //   文件比最后一次手动切换更新  -> 听文件的
            //   否则                        -> 保住用户手动切出来的状态
            bool keepEnabled = false;
            if (_userToggledEnabled)
            {
                DateTime fileTimeUtc;
                try { fileTimeUtc = File.GetLastWriteTimeUtc(_config.LoadedFrom); }
                catch (Exception) { fileTimeUtc = DateTime.MinValue; }
                keepEnabled = fileTimeUtc <= _lastToggleUtc;
            }
            bool enabledBefore = _config.Enabled;

            Config fresh = Config.Load(_startupConfigPath, _forceDefaultConfig);
            _config = fresh;
            if (keepEnabled) _config.Enabled = enabledBefore;
            if (_config.LoadError != null) WriteStderr("配置: " + _config.LoadError);

            _lastRenderKey = null;
            _refreshTimer.Interval = Math.Max(5, _config.RefreshSeconds) * 1000;
            RebuildOverlays(true);
            ApplyLiveChanges();
            if (_settings != null) _settings.SyncAll();
            if (notify && _tray != null) _tray.ShowBalloon("配置已重新载入", _config.LoadedFrom);
        }

        private void SetAutostart(bool want)
        {
            bool ok = WriteAutostart(want);
            if (!ok)
            {
                if (_tray != null) _tray.ShowBalloon("开机自启设置失败", "写注册表 HKCU\\...\\Run 被拒绝。");
                SyncUiState();
                return;
            }
            _config.Autostart = want;
            SaveConfig();
            SyncUiState();
        }

        private static bool WriteAutostart(bool enable)
        {
            try
            {
                using (RegistryKey key = Registry.CurrentUser.OpenSubKey(RunKeyPath, true))
                {
                    if (key == null) return false;
                    if (enable)
                    {
                        // 命令要带引号：装在带空格的路径下（"Program Files"）不加引号会被拆成两条。
                        key.SetValue(RunValueName, "\"" + Application.ExecutablePath + "\"",
                            RegistryValueKind.String);
                    }
                    else
                    {
                        if (key.GetValue(RunValueName) != null) key.DeleteValue(RunValueName, false);
                    }
                    return true;
                }
            }
            catch (Exception)
            {
                return false;
            }
        }

        /// <summary>读注册表里真实的注册状态，比配置里的 autostart 字段可信。</summary>
        public static bool ReadAutostart()
        {
            try
            {
                using (RegistryKey key = Registry.CurrentUser.OpenSubKey(RunKeyPath, false))
                {
                    if (key == null) return false;
                    return key.GetValue(RunValueName) != null;
                }
            }
            catch (Exception)
            {
                return false;
            }
        }

        private void ApplyColorsToSettings()
        {
            // 留给将来的主题定制；目前没有要做的事，保留钩子避免以后到处找地方。
        }

        // ================= 外部改配置也要跟上 =================

        private FileSystemWatcher _configWatcher;
        private Timer _configReloadDebounce;

        /// <summary>
        /// 盯着 config.json。用户会拿记事本直接改文件（也可能由另一个实现写），
        /// 不监听的话程序就永远停在旧参数上，看起来像"改了没用"。
        /// 编辑器保存会连发好几个事件，所以 400ms 合并一次再重载。
        /// </summary>
        private void WatchConfigFile()
        {
            try
            {
                string path = _config.LoadedFrom;
                string dir = Path.GetDirectoryName(path);
                if (string.IsNullOrEmpty(dir) || !Directory.Exists(dir)) return;

                _configReloadDebounce = new Timer();
                _configReloadDebounce.Interval = 400;
                _configReloadDebounce.Tick += delegate
                {
                    _configReloadDebounce.Stop();
                    ReloadConfig();
                };

                _configWatcher = new FileSystemWatcher(dir, Path.GetFileName(path));
                _configWatcher.NotifyFilter = NotifyFilters.LastWrite | NotifyFilters.Size | NotifyFilters.FileName;
                _configWatcher.Changed += delegate { PostToUi(delegate { _configReloadDebounce.Stop(); _configReloadDebounce.Start(); }); };
                _configWatcher.Created += delegate { PostToUi(delegate { _configReloadDebounce.Stop(); _configReloadDebounce.Start(); }); };
                _configWatcher.EnableRaisingEvents = true;
            }
            catch (Exception ex)
            {
                // 监听失败不影响使用，用户还能用托盘里的"重新载入配置"。
                WriteStderr("配置文件监听未启用: " + ex.Message);
            }
        }

        // ================= 系统事件 =================

        private void OnDisplaySettingsChanged(object sender, EventArgs e)
        {
            // 系统事件不一定在 UI 线程回来，统一丢回主线程处理。
            PostToUi(delegate
            {
                WriteStderr("显示器配置变化，重建水印窗口。");
                _lastRenderKey = null;
                RebuildOverlays(true);
            });
        }

        private void OnUserPreferenceChanged(object sender, UserPreferenceChangedEventArgs e)
        {
            if (e.Category == UserPreferenceCategory.Desktop ||
                e.Category == UserPreferenceCategory.General ||
                e.Category == UserPreferenceCategory.VisualStyle)
            {
                PostToUi(delegate
                {
                    // 主题/DPI 变化后字体度量可能变，强制重画一次。
                    _lastRenderKey = null;
                    RenderAll(true);
                });
            }
        }

        private void PostToUi(MethodInvoker action)
        {
            // 控制器本身没有窗口，借设置面板或 overlay 的句柄做 BeginInvoke 目标。
            Control target = null;
            if (_settings != null && _settings.IsHandleCreated) target = _settings;
            else if (_overlays.Count > 0 && _overlays[0].IsHandleCreated) target = _overlays[0];

            if (target == null)
            {
                action();
                return;
            }
            try
            {
                if (target.InvokeRequired) target.BeginInvoke(action);
                else action();
            }
            catch (Exception)
            {
                try { action(); } catch (Exception) { }
            }
        }

        // ================= 退出 =================

        private void Quit()
        {
            ExitThread();
        }

        protected override void ExitThreadCore()
        {
            DisposeAll();
            base.ExitThreadCore();
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing) DisposeAll();
            base.Dispose(disposing);
        }

        private void DisposeAll()
        {
            if (_disposed) return;
            _disposed = true;

            try { Microsoft.Win32.SystemEvents.DisplaySettingsChanged -= OnDisplaySettingsChanged; }
            catch (Exception) { }
            try { Microsoft.Win32.SystemEvents.UserPreferenceChanged -= OnUserPreferenceChanged; }
            catch (Exception) { }

            if (_configWatcher != null)
            {
                try { _configWatcher.EnableRaisingEvents = false; _configWatcher.Dispose(); }
                catch (Exception) { }
                _configWatcher = null;
            }
            if (_configReloadDebounce != null)
            {
                _configReloadDebounce.Stop();
                _configReloadDebounce.Dispose();
                _configReloadDebounce = null;
            }

            UnregisterHotkeys();

            if (_refreshTimer != null) { _refreshTimer.Stop(); _refreshTimer.Dispose(); _refreshTimer = null; }
            if (_topmostTimer != null) { _topmostTimer.Stop(); _topmostTimer.Dispose(); _topmostTimer = null; }

            DestroyOverlays();

            if (_settings != null) { _settings.Dispose(); _settings = null; }
            if (_tray != null) { _tray.Dispose(); _tray = null; }
        }

        private static void WriteStderr(string line)
        {
            // 实现在 Log 里（UTF-8 直写 stderr，绕开 Console.Error 的 GBK 编码）。
            Log.Warn(line);
        }
    }
}
