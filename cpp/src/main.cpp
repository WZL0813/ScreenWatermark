// main.cpp —— wWinMain、单实例互斥、消息窗口（快捷键 + 托盘回调）、全局控制器、消息循环。
// 所有跨模块的协调都收在这里：overlay 只负责画，settings 只管控件，tray 只管图标和菜单。
#include <windows.h>

#include <commctrl.h>
#include <gdiplus.h>
#include <shellapi.h>

#include <cstdio>
#include <cstdlib>
#include <string>

#include "config.h"
#include "hotkey.h"
#include "overlay.h"
#include "settings.h"
#include "tray.h"
#include "util.h"

using namespace Gdiplus;
using namespace sw;

namespace {

// 快捷键的动作 id 由 HotkeyManager 按 1..3 分配（动作顺序 = HotkeyAction）
// 内部消息：托盘回调在 util.h 的 kMsgTrayCallback
const UINT kMsgApplyConfig = WM_APP + 10;  // lParam 是 new 出来的 Config，处理方负责 delete
const UINT kMsgToggle = WM_APP + 11;
const UINT kMsgShowSettings = WM_APP + 12;
const UINT kMsgReload = WM_APP + 13;
const UINT kMsgQuit = WM_APP + 14;
const UINT kMsgHotkeysChanged = WM_APP + 15;  // lParam 是 new 出来的 Config
const UINT kMsgDumpFrame = WM_APP + 16;       // 诊断：把当前帧写到 cfg 指定的文件

// 定时器
const UINT kTimerTopmost = 1;   // 每 3 秒把水印顶回最前（§9）
const UINT kTimerTemplate = 2;  // 模板变量刷新

struct App {
    HWND msg_hwnd = nullptr;
    Overlay overlay;
    Tray tray;
    Settings settings;
    Config cfg;
    std::wstring config_path;
    bool tray_ok = false;
    HotkeyManager hotkeys;
    std::vector<HotkeyBinding> hotkey_bindings;
    // --dump-bitmap 模式下，每次应用后自动落帧，序号递增
    std::wstring frame_dump_path;
    int frame_seq = 0;
};

// 把当前配置里的三个组合重新注册一遍，并把实际生效情况写回面板提示行。
// 面板改了快捷键、重新载入配置都要走这条路，逻辑只写一份
void ApplyHotkeys(App* app) {
    std::wstring log;
    app->hotkeys.Apply(app->msg_hwnd, app->cfg.hotkeys, &app->hotkey_bindings, &log);
    // 注册失败/降级都要让用户看得见：面板底部写一行说明，文件日志里也有（LogWarn 负责）
    app->settings.SetHotkeyFields(app->cfg.hotkeys);
    app->settings.SetHintText(HotkeyHintLine(app->hotkey_bindings));
    app->settings.SetHotkeyStatus(log);
}

}  // namespace

// ---------------------------------------------------------------------------
// 消息窗口过程
// ---------------------------------------------------------------------------
static LRESULT CALLBACK MsgWndProc(HWND h, UINT m, WPARAM w, LPARAM l) {
    App* app = reinterpret_cast<App*>(::GetWindowLongPtrW(h, GWLP_USERDATA));
    if (m == WM_NCCREATE) {
        auto* cs = reinterpret_cast<CREATESTRUCTW*>(l);
        app = reinterpret_cast<App*>(cs->lpCreateParams);
        ::SetWindowLongPtrW(h, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(app));
    }
    if (!app) return ::DefWindowProcW(h, m, w, l);

    switch (m) {
        case WM_HOTKEY: {
            // 动作 id 由 HotkeyManager 分配（1..3），点不到就忽略
            const int idx = (int)w - 1;
            if (idx < 0 || idx >= (int)HotkeyAction::Count) return 0;
            switch ((HotkeyAction)idx) {
                case HotkeyAction::Toggle: ::PostMessageW(h, kMsgToggle, 0, 0); break;
                case HotkeyAction::Settings: ::PostMessageW(h, kMsgShowSettings, 0, 0); break;
                case HotkeyAction::Quit: ::PostMessageW(h, kMsgQuit, 0, 0); break;
                default: break;
            }
            return 0;
        }
        case kMsgTrayCallback: {
            // 低 16 位是鼠标消息，高 16 位是图标 ID
            switch (LOWORD(l)) {
                case WM_LBUTTONDBLCLK: ::PostMessageW(h, kMsgShowSettings, 0, 0); break;
                case WM_RBUTTONUP:
                case WM_CONTEXTMENU:
                    app->tray.ShowMenu(app->cfg.enabled, app->cfg.autostart);
                    break;
                default: break;
            }
            return 0;
        }
        case WM_COMMAND: {
            switch (LOWORD(w)) {
                case kCmdToggleWatermark: ::PostMessageW(h, kMsgToggle, 0, 0); break;
                case kCmdShowSettings: ::PostMessageW(h, kMsgShowSettings, 0, 0); break;
                case kCmdReloadConfig: ::PostMessageW(h, kMsgReload, 0, 0); break;
                case kCmdAutostart: {
                    app->cfg.autostart = !app->cfg.autostart;
                    SetAutostart(app->cfg.autostart);
                    SaveConfig(app->config_path, app->cfg);
                    break;
                }
                case kCmdQuit: ::PostMessageW(h, kMsgQuit, 0, 0); break;
                default: break;
            }
            return 0;
        }
        case kMsgToggle: {
            app->cfg.enabled = !app->cfg.enabled;
            app->overlay.Apply(app->cfg);
            app->tray.SetTooltip(app->cfg.enabled ? L"ScreenWatermark · 已启用"
                                                  : L"ScreenWatermark · 已隐藏");
            app->settings.SyncFrom(app->cfg);
            break;
        }
        case kMsgShowSettings: {
            app->settings.Toggle(app->cfg);
            break;
        }
        case kMsgReload: {
            app->cfg = LoadConfig(app->config_path);
            if (!app->cfg.load_warning.empty()) LogWarn(app->cfg.load_warning);
            if (!app->cfg.hotkey_warning.empty()) LogWarn(app->cfg.hotkey_warning);
            app->settings.SyncFrom(app->cfg);
            app->overlay.Apply(app->cfg);
            ApplyHotkeys(app);
            app->settings.NotifyConfigSaved();
            break;
        }
        case kMsgHotkeysChanged: {
            // 面板里改/录了快捷键：只更新配置里这三项，其它字段以主程序为准，
            // 免得面板一个还没落盘的改动把别的字段也带进来
            auto* incoming = reinterpret_cast<Config*>(l);
            if (incoming) {
                for (int i = 0; i < 3; ++i) app->cfg.hotkeys[i] = incoming->hotkeys[i];
                delete incoming;
            }
            ApplyHotkeys(app);
            break;
        }
        case kMsgQuit: {
            // 托盘菜单的「退出」和 Ctrl+Alt+Q 都往这儿投这个内部消息。
            // 早先 WndProc 里漏了这个 case —— 消息投出去没人接，于是"退出"点了没反应，
            // 面板能关、进程却退不掉，只能去任务管理器杀。
            // 这里只发 WM_QUIT 让消息循环收摊，真正的清理在 wWinMain 循环之后统一做。
            ::PostQuitMessage(0);
            return 0;
        }
        case kMsgApplyConfig: {
            // 面板送来的新配置：写回、重画，但不落盘（用户点了保存才落盘）
            auto* incoming = reinterpret_cast<Config*>(l);
            bool monitors_changed = false;
            bool refresh_changed = false;
            if (incoming) {
                monitors_changed = (incoming->all_monitors != app->cfg.all_monitors);
                refresh_changed = (incoming->refresh_seconds != app->cfg.refresh_seconds) ||
                                  (incoming->templ != app->cfg.templ) ||
                                  (incoming->text != app->cfg.text);
                app->cfg = *incoming;
                delete incoming;
            }
            if (monitors_changed) app->overlay.InvalidateMonitors();            // 排查「改了控件点应用没反应」：把真正参与渲染的字段记一行，
            // 和面板读数一对照就知道是没读进来还是没画出去
            DebugLog(L"Apply: text=\"%s\" font=%s/%d bold=%d italic=%d color=%s opacity=%.2f "
                     L"angle=%d gap=%d,%d spacing=%.2f allmon=%d phase=%d",
                     app->cfg.text.c_str(), app->cfg.font_family.c_str(), app->cfg.font_size,
                     app->cfg.bold ? 1 : 0, app->cfg.italic ? 1 : 0, app->cfg.color.c_str(),
                     app->cfg.opacity, app->cfg.angle, app->cfg.gap_x, app->cfg.gap_y,
                     app->cfg.line_spacing, app->cfg.all_monitors ? 1 : 0,
                     app->cfg.phase_offset ? 1 : 0);
            if (refresh_changed) {
                // {time} 是按 refresh_seconds 变的，间隔改了就得重排定时器
                ::KillTimer(app->msg_hwnd, kTimerTemplate);
                if (app->cfg.templ && TemplateHasTime(app->cfg.text))
                    ::SetTimer(app->msg_hwnd, kTimerTemplate,
                               (UINT)app->cfg.refresh_seconds * 1000, nullptr);
            }
            app->overlay.Apply(app->cfg);
            // --dump-bitmap 诊断模式：每次应用后自动落一帧，文件名带序号。
            // 这样测试脚本只要等文件出现即可，不用往窗口发消息（那条路在自动化里不可靠）
            if (!app->frame_dump_path.empty()) {
                std::wstring p = app->frame_dump_path;
                size_t dot = p.find_last_of(L'.');
                std::wstring seq = std::to_wstring(++app->frame_seq);
                p = (dot == std::wstring::npos) ? p + L"-" + seq
                                                : p.substr(0, dot) + L"-" + seq + p.substr(dot);
                DebugLog(L"应用后落帧 -> %s", p.c_str());
                app->overlay.DumpNextFrameTo(p);
                app->overlay.Refresh();
            }
            app->tray.SetTooltip(app->cfg.enabled ? L"ScreenWatermark · 已启用"
                                                  : L"ScreenWatermark · 已隐藏");
            break;
        }
        case kMsgDumpFrame: {
            // 诊断：按当前配置重画一帧并落盘。用来验证「某个控件到底有没有进渲染」
            if (app->frame_dump_path.empty()) break;
            DebugLog(L"收到落帧请求 -> %s", app->frame_dump_path.c_str());
            app->overlay.DumpNextFrameTo(app->frame_dump_path);
            app->overlay.Refresh();
            break;
        }
        case WM_TIMER: {
            if (w == kTimerTopmost) {
                // 别的全屏程序可能把我们的 TOPMOST 盖住，定期顶一下；不移动不改变尺寸
                if (app->cfg.enabled) {
                    for (HWND ow : app->overlay.window_handles())
                        ::SetWindowPos(ow, HWND_TOPMOST, 0, 0, 0, 0,
                                       SWP_NOACTIVATE | SWP_NOMOVE | SWP_NOSIZE);
                }
            } else if (w == kTimerTemplate) {
                app->overlay.Refresh();
            }
            return 0;
        }
        case WM_DISPLAYCHANGE:
        case WM_DPICHANGED: {
            // 显示器拔插 / 缩放变化：重建窗口再重画
            app->overlay.InvalidateMonitors();
            app->overlay.Apply(app->cfg);
            return 0;
        }
        case WM_QUERYENDSESSION:
        case WM_ENDSESSION: return TRUE;
        default: break;
    }
    return ::DefWindowProcW(h, m, w, l);
}

// 把已有实例的设置面板叫出来
static void ActivateExistingInstance() {
    // 先找已有实例的消息窗口，让它自己把面板弹出来。
    // 为什么不再去枚举"设置面板窗口"：面板是懒创建的，用户从没开过面板时
    // 那个窗口根本不存在，于是第二次双击 exe 会"闪一下什么都没发生"，
    // 看起来就像程序坏了。
    if (HWND msg = ::FindWindowW(kMsgWndClass, nullptr)) {
        ::PostMessageW(msg, kMsgShowSettings, 0, 0);
        return;
    }
    // 兜底：消息窗口都没找到，但面板碰巧开着，就直接抬到最前面
    if (HWND panel = ::FindWindowW(L"ScreenWatermarkSettingsWnd", nullptr)) {
        ::ShowWindow(panel, SW_SHOWNORMAL);
        ::SetForegroundWindow(panel);
    }
}

// 极简命令行：--version / -v / --config <path> / --dump-controls <path> / --help
struct CmdLine {
    std::wstring config_override;
    std::wstring dump_controls_path;  // 非空 = 只做一次控件审计然后退出
    std::wstring dump_bitmap_path;    // 非空 = 每帧渲染完写到这里（诊断用）
    bool done = false;                // 打完版本号/帮助就退出
};

static void ParseArgs(CmdLine& cl) {
    int argc = 0;
    LPWSTR* argv = ::CommandLineToArgvW(::GetCommandLineW(), &argc);
    if (!argv) return;
    for (int i = 1; i < argc; ++i) {
        std::wstring a = argv[i];
        if (a == L"--version" || a == L"-v") {
            wchar_t buf[128];
            swprintf(buf, 128, L"%s %s\n", kAppName, kAppVersion);
            fputws(buf, stdout);
            cl.done = true;
        } else if (a == L"--help" || a == L"-h") {
            fputws(L"用法: ScreenWatermark.exe [--config <路径>] [--dump-controls <文件>]\n",
                   stdout);
            fputws(L"                          [--dump-bitmap <文件>] [--version]\n", stdout);
            fputws(L"  --dump-controls  把设置面板每个控件的读数和收集结果写成对照表后退出\n", stdout);
            fputws(L"  --dump-bitmap    每帧把渲染出来的位图写到该文件（排查控件不生效）\n", stdout);
            cl.done = true;
        } else if (a == L"--config" && i + 1 < argc) {
            cl.config_override = argv[++i];
        } else if (a == L"--dump-controls" && i + 1 < argc) {
            cl.dump_controls_path = argv[++i];
        } else if (a == L"--dump-bitmap" && i + 1 < argc) {
            cl.dump_bitmap_path = argv[++i];
        }
    }
    ::LocalFree(argv);
}

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE, LPWSTR, int) {
    // 越早越好：任何窗口/显示器查询之前先把 DPI 感知定下来，否则枚举到的显示器尺寸可能
    // 是被缩放过的虚拟值，水印会被贴到屏幕外面
    EnsureDpiAwareness();

    CmdLine cl;
    ParseArgs(cl);
    if (cl.done) return 0;

    // 单实例：已经有一个在跑就把它的面板叫出来，自己退出
    HANDLE mutex = ::CreateMutexW(nullptr, TRUE, kMutexName);
    if (mutex && ::GetLastError() == ERROR_ALREADY_EXISTS) {
        ActivateExistingInstance();
        ::CloseHandle(mutex);
        return 0;
    }

    // TRACKBAR 属于公共控件，必须显式初始化，否则 CreateWindowEx 会失败
    INITCOMMONCONTROLSEX icc{};
    icc.dwSize = sizeof(icc);
    icc.dwICC = ICC_BAR_CLASSES | ICC_STANDARD_CLASSES;
    ::InitCommonControlsEx(&icc);

    GdiplusStartupInput gdi_in{};
    ULONG_PTR gdi_token = 0;
    if (GdiplusStartup(&gdi_token, &gdi_in, nullptr) != Ok) {
        ::MessageBoxW(nullptr, L"GDI+ 初始化失败，程序无法继续。", kAppName, MB_ICONERROR | MB_OK);
        return 1;
    }

    WNDCLASSEXW wc{};
    wc.cbSize = sizeof(wc);
    wc.lpfnWndProc = MsgWndProc;
    wc.hInstance = inst;
    wc.lpszClassName = kMsgWndClass;
    if (!::RegisterClassExW(&wc)) {
        ::MessageBoxW(nullptr, L"窗口类注册失败，程序无法继续。", kAppName, MB_ICONERROR | MB_OK);
        GdiplusShutdown(gdi_token);
        return 1;
    }

    WNDCLASSEXW oc{};
    oc.cbSize = sizeof(oc);
    oc.lpfnWndProc = OverlayWndProc;
    oc.hInstance = inst;
    oc.hCursor = ::LoadCursorW(nullptr, IDC_ARROW);
    oc.lpszClassName = kOverlayWndClass;
    if (!::RegisterClassExW(&oc) && ::GetLastError() != ERROR_CLASS_ALREADY_EXISTS) {
        ::MessageBoxW(nullptr, L"水印窗口类注册失败，程序无法继续。", kAppName, MB_ICONERROR | MB_OK);
        GdiplusShutdown(gdi_token);
        return 1;
    }

    static App app;
    App* const self = &app;  // 闭包捕获这个局部指针，别直接捕获 static 变量（会被 -Wextra 唠叨）
    app.config_path = cl.config_override.empty() ? ConfigPath() : cl.config_override;
    app.cfg = LoadConfig(app.config_path);
    // 坏文件、字段写歪都走 LogWarn：GUI 子系统下 stderr 可能是空的，必须同时落文件
    if (!app.cfg.load_warning.empty()) LogWarn(app.cfg.load_warning);
    // 某一项快捷键写法不合法时，日志要指明是哪一项、原文是什么（其它项照常工作）
    if (!app.cfg.hotkey_warning.empty()) LogWarn(app.cfg.hotkey_warning);
    DebugLog(L"启动: config=%s text=\"%s\" allmon=%d opacity=%.2f angle=%d gap=%d,%d", 
             app.config_path.c_str(), app.cfg.text.c_str(), app.cfg.all_monitors ? 1 : 0,
             app.cfg.opacity, app.cfg.angle, app.cfg.gap_x, app.cfg.gap_y);

    app.msg_hwnd = ::CreateWindowExW(0, kMsgWndClass, kAppName, 0, 0, 0, 0, 0, nullptr, nullptr,
                                     inst, &app);
    if (!app.msg_hwnd) {
        ::MessageBoxW(nullptr, L"主消息窗口创建失败，程序无法继续。", kAppName, MB_ICONERROR | MB_OK);
        GdiplusShutdown(gdi_token);
        return 1;
    }

    // 开机自启以注册表为准：用户可能在别处删过，配置里的值只是缓存
    app.cfg.autostart = IsAutostartEnabled();

    // --dump-bitmap：每次渲染都落盘。必须在第一次 Apply 之前设好，否则那一帧就错过了。
    // 测试脚本靠它拿到「渲染链的最终产物」，比截屏干净（截屏会被别的窗口和 z 序干扰）
    app.frame_dump_path = cl.dump_bitmap_path;
    DebugLog(L"落帧路径=\"%s\"", app.frame_dump_path.c_str());
    if (!app.frame_dump_path.empty()) app.overlay.DumpNextFrameTo(app.frame_dump_path);

    app.overlay.Apply(app.cfg);

    app.tray_ok = app.tray.Add(app.msg_hwnd);
    if (!app.tray_ok) LogWarn(L"托盘图标添加失败，只能用快捷键和设置面板控制。");
    else app.tray.SetTooltip(app.cfg.enabled ? L"ScreenWatermark · 已启用"
                                             : L"ScreenWatermark · 已隐藏");

    // 面板的改动通过 PostMessage 回主线程，别在控件回调里直接重画
    app.settings.on_apply = [self](const Config& c) {
        auto* copy = new Config(c);
        ::PostMessageW(self->msg_hwnd, kMsgApplyConfig, 0, reinterpret_cast<LPARAM>(copy));
    };
    app.settings.on_toggle = [self]() { ::PostMessageW(self->msg_hwnd, kMsgToggle, 0, 0); };
    app.settings.on_save = [self](const Config& c) {
        self->cfg = c;
        SaveConfig(self->config_path, c);
        self->overlay.Apply(c);
    };
    // 面板改/录了快捷键 → 回主线程重新注册（RegisterHotKey 必须在消息窗口线程上做）
    app.settings.on_hotkeys_changed = [self](const Config& c) {
        auto* copy = new Config(c);
        ::PostMessageW(self->msg_hwnd, kMsgHotkeysChanged, 0, reinterpret_cast<LPARAM>(copy));
    };
    // 录制期间要把全局热键整体关掉，否则用户按自己的热键会先把水印关了
    app.settings.on_hotkeys_suspend = [self](bool suspend) {
        self->hotkeys.Enable(self->msg_hwnd, !suspend);
    };
    // 面板的 owner 设成消息窗口：这样面板既能不进任务栏 / Alt+Tab，
    // 又不需要 WS_EX_TOOLWINDOW —— 那个样式会让 Win11 把关闭按钮一直画成红色悬停态
    app.settings.SetOwner(app.msg_hwnd);
    app.settings.EnsureWindow();

    // --dump-controls：把面板每个控件的读数和 Collect() 的结果写成对照表就退出。
    // 这种「改了控件点应用没反应」的问题，靠肉眼读代码很容易漏，直接打印读数最快
    if (!cl.dump_controls_path.empty()) {
        app.settings.Show(app.cfg);          // 建面板并同步控件；WM_TIMER 会跑一次 Collect
        ::Sleep(400);                        // 让面板的 16ms 定时器至少跑一轮
        std::wstring table;
        bool ok = app.settings.DumpControlAudit(cl.dump_controls_path, &table);
        fputws(table.c_str(), stdout);
        DebugLog(L"--dump-controls 写入 %s -> %s", cl.dump_controls_path.c_str(),
                 ok ? L"成功" : L"失败");
        app.settings.Shutdown();
        app.tray.Remove();
        app.overlay.Shutdown();
        ::DestroyWindow(app.msg_hwnd);
        GdiplusShutdown(gdi_token);
        if (mutex) ::CloseHandle(mutex);
        return ok ? 0 : 1;
    }

    // 快捷键：全部从配置来（§2 的 hotkeys）。首选被占用会自动退到加 Shift 的版本，
    // 实际生效的组合写进日志和面板底部的提示行
    ApplyHotkeys(&app);

    // 提醒多实例。单实例互斥体只挡得住同一个版本，另外三个实现的锁名不同、能同时跑，
    // 于是屏幕上会叠出多层水印（本机实测复现过），用户很容易误以为是渲染坏了。
    {
        int others = CountOtherInstances();
        if (others > 0) {
            std::wstring msg = L"检测到还有 " + std::to_wstring(others) +
                               L" 个 ScreenWatermark 在运行，屏幕上会叠出多层水印。"
                               L"单实例锁只挡同一个版本，不同实现之间挡不住。";
            LogWarn(msg);
            if (app.tray_ok) app.tray.ShowBalloon(L"ScreenWatermark 有多个实例在跑", msg);
        }
    }

    ::SetTimer(app.msg_hwnd, kTimerTopmost, 3000, nullptr);
    // 只有模板里真的含 {time} 才需要定时重绘，否则静置时一个像素都不重画
    if (app.cfg.templ && TemplateHasTime(app.cfg.text))
        ::SetTimer(app.msg_hwnd, kTimerTemplate, (UINT)app.cfg.refresh_seconds * 1000, nullptr);

    MSG msg;
    while (::GetMessageW(&msg, nullptr, 0, 0) > 0) {
        ::TranslateMessage(&msg);
        ::DispatchMessageW(&msg);
    }

    ::KillTimer(app.msg_hwnd, kTimerTopmost);
    ::KillTimer(app.msg_hwnd, kTimerTemplate);
    app.hotkeys.UnregisterAll(app.msg_hwnd);
    // 按依赖顺序自己收摊：App 是 static，析构顺序不可控，交给析构函数会出现
    // 「面板还活着但字体已经被删掉」这种悬空状态（实测确认过）
    app.settings.Shutdown();
    app.tray.Remove();
    app.overlay.Shutdown();
    ::DestroyWindow(app.msg_hwnd);
    GdiplusShutdown(gdi_token);
    if (mutex) ::CloseHandle(mutex);
    return 0;
}
