#include "tray.h"

#include <shellapi.h>

namespace sw {

namespace {
// 低 16 位是鼠标消息，高 16 位是图标 ID
const UINT kTrayIconId = 1;
}  // namespace

Tray::~Tray() { Remove(); }

bool Tray::Add(HWND owner) {
    owner_ = owner;
    NOTIFYICONDATAW nid{};
    nid.cbSize = sizeof(nid);
    nid.hWnd = owner;
    nid.uID = kTrayIconId;
    nid.uFlags = NIF_ICON | NIF_MESSAGE | NIF_TIP;
    nid.uCallbackMessage = kMsgTrayCallback;
    // 优先用资源里的图标（app.rc 里是数字 ID 1），取不到再退回系统默认，
    // 别因为图标问题丢整个托盘
    nid.hIcon = (HICON)::LoadImageW(::GetModuleHandleW(nullptr), MAKEINTRESOURCEW(1), IMAGE_ICON,
                                    0, 0, LR_DEFAULTSIZE | LR_SHARED);
    if (!nid.hIcon) nid.hIcon = ::LoadIconW(nullptr, IDI_APPLICATION);
    wcsncpy(nid.szTip, L"ScreenWatermark · 已启用", 127);
    added_ = ::Shell_NotifyIconW(NIM_ADD, &nid) != FALSE;
    return added_;
}

void Tray::Remove() {
    if (!added_) return;
    NOTIFYICONDATAW nid{};
    nid.cbSize = sizeof(nid);
    nid.hWnd = owner_;
    nid.uID = kTrayIconId;
    ::Shell_NotifyIconW(NIM_DELETE, &nid);
    added_ = false;
}

void Tray::SetTooltip(const std::wstring& text) {
    if (!added_) return;
    NOTIFYICONDATAW nid{};
    nid.cbSize = sizeof(nid);
    nid.hWnd = owner_;
    nid.uID = kTrayIconId;
    nid.uFlags = NIF_TIP;
    wcsncpy(nid.szTip, text.c_str(), 127);
    nid.szTip[127] = L'\0';
    ::Shell_NotifyIconW(NIM_MODIFY, &nid);
}

void Tray::ShowBalloon(const std::wstring& title, const std::wstring& text) {
    if (!added_) return;
    NOTIFYICONDATAW nid{};
    nid.cbSize = sizeof(nid);
    nid.hWnd = owner_;
    nid.uID = kTrayIconId;
    nid.uFlags = NIF_INFO;
    nid.dwInfoFlags = NIIF_WARNING;
    nid.uTimeout = 10000;
    // szInfoTitle 是 64 个字符、szInfo 是 256 个，超了会截断，这里按上限拷
    wcsncpy(nid.szInfoTitle, title.c_str(), 63);
    nid.szInfoTitle[63] = L'\0';
    wcsncpy(nid.szInfo, text.c_str(), 255);
    nid.szInfo[255] = L'\0';
    ::Shell_NotifyIconW(NIM_MODIFY, &nid);
}

void Tray::ShowMenu(bool enabled, bool autostart) {
    HMENU menu = ::CreatePopupMenu();
    if (!menu) return;
    ::AppendMenuW(menu, MF_STRING, kCmdToggleWatermark, enabled ? L"隐藏水印" : L"显示水印");
    ::AppendMenuW(menu, MF_STRING, kCmdShowSettings, L"设置…");
    ::AppendMenuW(menu, MF_STRING, kCmdReloadConfig, L"重新载入配置");
    ::AppendMenuW(menu, MF_SEPARATOR, 0, nullptr);
    ::AppendMenuW(menu, MF_STRING | (autostart ? MF_CHECKED : MF_UNCHECKED), kCmdAutostart,
                  L"开机自启");
    ::AppendMenuW(menu, MF_SEPARATOR, 0, nullptr);
    ::AppendMenuW(menu, MF_STRING, kCmdQuit, L"退出");
    // 「关于」放最后：点了用默认浏览器打开项目仓库
    ::AppendMenuW(menu, MF_SEPARATOR, 0, nullptr);
    ::AppendMenuW(menu, MF_STRING, kCmdAbout, L"关于 ScreenWatermark");

    POINT pt{};
    ::GetCursorPos(&pt);
    // 不先抢前台，菜单会一直挂着不消失（Win32 托盘的老毛病）
    ::SetForegroundWindow(owner_);
    ::TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_BOTTOMALIGN, pt.x, pt.y, 0, owner_, nullptr);
    ::PostMessageW(owner_, WM_NULL, 0, 0);  // 官方推荐的收尾动作
    ::DestroyMenu(menu);
}

}  // namespace sw
