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
#include "overlay.h"
#include "settings.h"
#include "tray.h"
#include "util.h"

using namespace Gdiplus;
using namespace sw;

namespace {

// 快捷键 ID
const int kHotkeyToggle = 1;
const int kHotkeySettings = 2;
const int kHotkeyQuit = 3;

// 内部消息：托盘回调在 util.h 的 kMsgTrayCallback
const UINT kMsgApplyConfig = WM_APP + 10;  // lParam 是 new 出来的 Config，处理方负责 delete
const UINT kMsgToggle = WM_APP + 11;
const UINT kMsgShowSettings = WM_APP + 12;
const UINT kMsgReload = WM_APP + 13;
const UINT kMsgQuit = WM_APP + 14;

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
};

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
            switch (w) {
                case kHotkeyToggle: ::PostMessageW(h, kMsgToggle, 0, 0); break;
                case kHotkeySettings: ::PostMessageW(h, kMsgShowSettings, 0, 0); break;
                case kHotkeyQuit: ::PostMessageW(h, kMsgQuit, 0, 0); break;
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
            app->settings.SyncFrom(app->cfg);
            app->overlay.Apply(app->cfg);
            app->settings.NotifyConfigSaved();
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
            if (monitors_changed) app->overlay.InvalidateMonitors();
            if (refresh_changed) {
                // {time} 是按 refresh_seconds 变的，间隔改了就得重排定时器
                ::KillTimer(app->msg_hwnd, kTimerTemplate);
                if (app->cfg.templ && TemplateHasTime(app->cfg.text))
                    ::SetTimer(app->msg_hwnd, kTimerTemplate,
                               (UINT)app->cfg.refresh_seconds * 1000, nullptr);
            }
            app->overlay.Apply(app->cfg);
            app->tray.SetTooltip(app->cfg.enabled ? L"ScreenWatermark · 已启用"
                                                  : L"ScreenWatermark · 已隐藏");
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

// 极简命令行：--version / -v / --config <path> / --help
static void ParseArgs(std::wstring& config_override, bool& done) {
    done = false;
    int argc = 0;
    LPWSTR* argv = ::CommandLineToArgvW(::GetCommandLineW(), &argc);
    if (!argv) return;
    for (int i = 1; i < argc; ++i) {
        std::wstring a = argv[i];
        if (a == L"--version" || a == L"-v") {
            wchar_t buf[128];
            swprintf(buf, 128, L"%s %s\n", kAppName, kAppVersion);
            fputws(buf, stdout);
            done = true;
        } else if (a == L"--help" || a == L"-h") {
            fputws(L"用法: ScreenWatermark.exe [--config <路径>] [--version]\n", stdout);
            done = true;
        } else if (a == L"--config" && i + 1 < argc) {
            config_override = argv[++i];
        }
    }
    ::LocalFree(argv);
}

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE, LPWSTR, int) {
    // 越早越好：任何窗口/显示器查询之前先把 DPI 感知定下来，否则枚举到的显示器尺寸可能
    // 是被缩放过的虚拟值，水印会被贴到屏幕外面
    EnsureDpiAwareness();

    std::wstring config_override;
    bool done = false;
    ParseArgs(config_override, done);
    if (done) return 0;

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
    app.config_path = config_override.empty() ? ConfigPath() : config_override;
    app.cfg = LoadConfig(app.config_path);
    if (!app.cfg.load_warning.empty()) fputws((app.cfg.load_warning + L"\n").c_str(), stderr);

    app.msg_hwnd = ::CreateWindowExW(0, kMsgWndClass, kAppName, 0, 0, 0, 0, 0, nullptr, nullptr,
                                     inst, &app);
    if (!app.msg_hwnd) {
        ::MessageBoxW(nullptr, L"主消息窗口创建失败，程序无法继续。", kAppName, MB_ICONERROR | MB_OK);
        GdiplusShutdown(gdi_token);
        return 1;
    }

    // 开机自启以注册表为准：用户可能在别处删过，配置里的值只是缓存
    app.cfg.autostart = IsAutostartEnabled();

    app.overlay.Apply(app.cfg);

    app.tray_ok = app.tray.Add(app.msg_hwnd);
    if (!app.tray_ok) fputws(L"托盘图标添加失败，只能用快捷键和设置面板控制。\n", stderr);
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
    app.settings.EnsureWindow();

    // 热键：契约里的 Ctrl+Alt+W/S/Q 是首选，但本机实测 W 和 Q 被别的程序占着（error 1409）。
    // 被占用时退一级注册 Ctrl+Alt+Shift+同键，保证功能可用，并把实际组合记进日志。
    std::wstring hotkeyToggle = L"Ctrl+Alt+W";
    std::wstring hotkeyQuit = L"Ctrl+Alt+Q";
    BOOL okToggle = ::RegisterHotKey(app.msg_hwnd, kHotkeyToggle, MOD_CONTROL | MOD_ALT, 'W');
    if (!okToggle) {
        okToggle = ::RegisterHotKey(app.msg_hwnd, kHotkeyToggle, MOD_CONTROL | MOD_ALT | MOD_SHIFT,
                                    'W');
        if (okToggle) hotkeyToggle = L"Ctrl+Alt+Shift+W";
    }
    BOOL okSettings = ::RegisterHotKey(app.msg_hwnd, kHotkeySettings, MOD_CONTROL | MOD_ALT, 'S');
    BOOL okQuit = ::RegisterHotKey(app.msg_hwnd, kHotkeyQuit, MOD_CONTROL | MOD_ALT, 'Q');
    if (!okQuit) {
        okQuit = ::RegisterHotKey(app.msg_hwnd, kHotkeyQuit, MOD_CONTROL | MOD_ALT | MOD_SHIFT, 'Q');
        if (okQuit) hotkeyQuit = L"Ctrl+Alt+Shift+Q";
    }
    if (!okToggle) fputws(L"注册 Ctrl+Alt+W 失败（已被别的程序占用），该功能只能走托盘菜单。\n", stderr);
    if (!okSettings) fputws(L"注册 Ctrl+Alt+S 失败（已被别的程序占用），该功能只能走托盘菜单。\n", stderr);
    if (!okQuit) fputws(L"注册 Ctrl+Alt+Q 失败（已被别的程序占用），该功能只能走托盘菜单。\n", stderr);

    // 面板底部的提示按实际生效的组合来写（契约组合被占用时会换成 Shift 版）
    app.settings.SetHintText(L"快捷键：" + hotkeyToggle + L" 开关水印 · Ctrl+Alt+S 设置 · " +
                             hotkeyQuit + L" 退出");

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
    ::UnregisterHotKey(app.msg_hwnd, kHotkeyToggle);
    ::UnregisterHotKey(app.msg_hwnd, kHotkeySettings);
    ::UnregisterHotKey(app.msg_hwnd, kHotkeyQuit);
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
