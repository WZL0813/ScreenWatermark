// overlay.h —— 每显示器一个分层窗口，GDI+ 把水印预渲染进 32bpp 预乘 alpha 的 DIB。
// 设计要点：位图只在配置 / 显示器 / 时间变量变化时重画，平时一个像素都不动（§6、§11.10）。
#pragma once

#include <windows.h>

#include <gdiplus.h>

#include <vector>

#include "config.h"
#include "util.h"

namespace sw {

class Overlay {
public:
    Overlay() = default;
    ~Overlay();

    // 按当前配置建 / 毁窗口并重画；enabled=false 时全部隐藏
    void Apply(const Config& cfg);
    // 只按现有配置重画（时间刷新用）
    void Refresh();
    // 强制下次 Apply 重建窗口，显示器数量 / 分辨率变化时调
    void InvalidateMonitors();
    // 退出时显式销毁所有水印窗
    void Shutdown();

    const Config& config() const { return cfg_; }
    // main 每 3 秒要拿这些句柄去顶 TOPMOST
    std::vector<HWND> window_handles() const;

private:
    struct Win {
        HWND hwnd = nullptr;
        RECT rc{};
        UINT dpi = 96;
    };

    bool EnsureWindows(const std::vector<MonitorRect>& want);
    void DestroyWindows();
    void RenderTo(const Win& w);
    // §6 的平铺算法：算单元 + 逐格旋转绘制
    void RenderCells(Gdiplus::Graphics& g, Gdiplus::Font& font, int w_px, int h_px,
                     const std::wstring& text);
    // 建字体 + 调 RenderCells，两条位图路径共用
    void DrawWatermark(Gdiplus::Graphics& g, int w_px, int h_px, UINT dpi);
    // 生成 w×h 的 32bpp top-down DIB，返回位图与像素指针（调用方负责 DeleteObject）
    bool MakeBackBuffer(int w, int h, HBITMAP& bmp, void** bits) const;

    Config cfg_;
    std::vector<Win> wins_;
    bool monitors_dirty_ = true;
    std::vector<MonitorRect> last_monitors_;
};

// overlay 窗口的窗口过程，main.cpp 注册窗口类时用
LRESULT CALLBACK OverlayWndProc(HWND, UINT, WPARAM, LPARAM);

}  // namespace sw
