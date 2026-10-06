// tray.h —— 托盘图标与右键菜单。
// 托盘是唯一的常驻入口（关掉设置面板程序还在），所以 NIM_ADD 失败不能崩，只能降级。
#pragma once

#include <windows.h>

#include "config.h"

namespace sw {

// 菜单项 ID，主窗口的 WM_COMMAND 里直接用
enum : UINT {
    kCmdToggleWatermark = 40001,
    kCmdShowSettings = 40002,
    kCmdReloadConfig = 40003,
    kCmdAutostart = 40004,
    kCmdQuit = 40005,
};

class Tray {
public:
    ~Tray();

    // owner 收 WM_APP+1 回调消息；失败返回 false，调用方打日志继续跑
    bool Add(HWND owner);
    void Remove();
    void SetTooltip(const std::wstring& text);
    // 在鼠标位置弹菜单；弹出前必须先 SetForegroundWindow，否则菜单点了不消失
    void ShowMenu(bool enabled, bool autostart);

private:
    HWND owner_ = nullptr;
    bool added_ = false;
};

}  // namespace sw
