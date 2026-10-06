// settings.h —— 原生设置面板（§5 的 14 项控件）。
// 面板是「模型-视图」里的视图：不持有权威配置，改动通过回调交给 main 决定。
#pragma once

#include <windows.h>

#include <functional>
#include <string>

#include "config.h"

namespace sw {

class Settings {
public:
    // 用户在面板里改了东西 → 立刻回调，main 拿去刷水印 / 重画
    std::function<void(const Config&)> on_apply;
    // 「隐藏水印」按钮：切换显示状态（main 那边统一处理）
    std::function<void()> on_toggle;
    // 「保存配置」按钮
    std::function<void(const Config&)> on_save;
    // 快捷键那三个输入框改了内容 → 交给 main 重新注册（注册必须在主窗口线程做）
    std::function<void(const Config&)> on_hotkeys_changed;
    // 录制期间要整体挂起/恢复全局热键，否则用户按自己的热键会先把水印关了
    std::function<void(bool)> on_hotkeys_suspend;

    ~Settings();

    // 创建（或复用）面板窗口，不显示。
    // 必须在第一次 EnsureWindow / Show 之前调 SetOwner，否则面板会跑到任务栏上。
    void SetOwner(HWND owner) { parent_ = owner; }
    bool EnsureWindow();
    void Show(const Config& cfg);
    void Hide();
    void Toggle(const Config& cfg);
    bool IsVisible() const;
    // 退出时由 main 显式调用
    void Shutdown();
    HWND hwnd() const { return hwnd_; }
    // 快捷键组合被别的程序占用时会退级，底部的提示文字要跟着改
    void SetHintText(const std::wstring& text);
    // 把配置里的三个组合填进输入框（main 决定填什么，面板不自己猜）
    void SetHotkeyFields(const std::wstring (&keys)[3]);
    // 注册结果/降级/失败原因，显示在提示行下面
    void SetHotkeyStatus(const std::wstring& text);
    // 外部（重新载入配置）改了配置，把控件同步过来
    void SyncFrom(const Config& cfg);
    // 配置里字段被别处改动后，让面板知道自己不再脏
    void MarkClean() { dirty_ = false; }

    void NotifyConfigSaved();
    // 诊断：把面板每个控件的读数和 Collect() 读出来的 Config 逐项对照，写进文件。
    // 排查「改了某个控件点应用却没反应」时用，比盯着代码猜快得多。
    // 依赖面板已创建，所以只在面板建好之后调；返回是否写成功
    bool DumpControlAudit(const std::wstring& path, std::wstring* text_out);

private:
    // 这三步故意分开：PanelProc 里的 static 回调需要访问私有成员
    static LRESULT CALLBACK PanelProcThunk(HWND, UINT, WPARAM, LPARAM);
    LRESULT PanelProc(HWND, UINT, WPARAM, LPARAM);

    void BuildControls(HWND host);
    void Collect(Config& out) const;
    int  ReadInt(int id, int def, int lo, int hi) const;
    double ReadDouble(int id, double def, double lo, double hi) const;
    bool ReadCheck(int id) const;
    std::wstring ReadText(int id) const;
    void SetIntText(int id, int v);
    void LoadFontList();
    void ApplyDpiFont(UINT dpi);
    void UpdateColorPreview();
    // 录制快捷键：START 进入录制态，Poll 每 30ms 读一次键盘状态
    void StartRecording(int idx);
    void StopRecording(bool apply);
    void PollRecording();
    // 把三个输入框的内容提交给 main（先解析，不合法的项退回默认值）
    void CommitHotkeys();

    HWND hwnd_ = nullptr;
    HWND parent_ = nullptr;   // 面板的 owner（消息窗口）。有 owner 才不用 WS_EX_TOOLWINDOW 也不上任务栏
    HFONT font_ = nullptr;
    HBRUSH brush_ = nullptr;   // 颜色预览色块
    COLORREF swatch_ = CLR_INVALID;
    Config cfg_{};
    bool dirty_ = false;
    bool suppress_ = false;  // 程序自己改控件时不要再回调，否则会自我循环
    UINT dpi_ = 96;
    int recording_ = -1;     // 正在录制的输入框序号，-1 表示没在录
};

}  // namespace sw
