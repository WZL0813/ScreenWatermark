// overlay.h —— 每显示器一个分层窗口，GDI+ 把水印预渲染进 32bpp 预乘 alpha 的 DIB。
// 设计要点：位图只在配置 / 显示器 / 时间变量变化时重画，平时一个像素都不动（§6、§11.10）。
#pragma once

#include <windows.h>

#include <gdiplus.h>

#include <functional>
#include <memory>
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
    // 诊断：把下一帧渲染出来的位图写到指定路径（PNG）。
    // 给「改了某个控件屏幕却没变」这类问题用：位图是渲染链的最终产物，
    // 比截屏干净得多（截屏还会被别的窗口和 z 序干扰）
    void DumpNextFrameTo(const std::wstring& path) { dump_path_ = path; }

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
    // 一个「平铺单元」里画什么：多行文字，或者一张图片。
    // 平铺 / 旋转 / 透明度 / gap / cols·rows / 夹取全都共用同一套逻辑，只有这里不同
    struct Unit {
        Gdiplus::REAL w = 0.0f;  // 实测单元尺寸（不含 gap）
        Gdiplus::REAL h = 0.0f;
        bool ok = false;
        // 文字单元：逐行画。每行的画布 y 已经在 text_dy 里算好
        std::vector<std::wstring> lines;
        std::vector<Gdiplus::REAL> text_dy;
        Gdiplus::Font* font = nullptr;  // 借用，由 DrawWatermark 持有
        Gdiplus::REAL line_step = 0.0f;
        Gdiplus::Color color;
        // 图片单元：已经缩放好、并且烘进整体透明度的位图
        Gdiplus::Bitmap* img = nullptr;
    };
    // 测多行文字盒（最宽行 + 行数 × 行高 × line_spacing）并建好逐行绘制回调
    Unit MakeTextUnit(Gdiplus::Graphics& g, Gdiplus::Font& font, const std::wstring& text);
    // 按 cfg_.image / cfg_.image_scale 加载并缩放图片；失败返回 ok=false 并写日志
    Unit MakeImageUnit(Gdiplus::Graphics& g);
    // 通用平铺循环：给定单元和绘制回调，按 §6 的规则铺满整屏
    void TileUnit(Gdiplus::Graphics& g, const Unit& unit, int w_px, int h_px);
    // 建字体 + 决定用图片还是文字 + 平铺；两条位图路径共用
    void DrawWatermark(Gdiplus::Graphics& g, int w_px, int h_px, UINT dpi);
    // 生成 w×h 的 32bpp top-down DIB，返回位图与像素指针（调用方负责 DeleteObject）
    bool MakeBackBuffer(int w, int h, HBITMAP& bmp, void** bits) const;

    Config cfg_;
    std::vector<Win> wins_;
    bool monitors_dirty_ = true;
    std::vector<MonitorRect> last_monitors_;
    // 非空 = 下一帧渲染完就写到这个路径（诊断用，正常运行时是空的）
    std::wstring dump_path_;
    // 图片水印缓存：按「路径 + 修改时间 + 缩放倍数」判断要不要重读盘。
    // 每帧都读盘太蠢（一次重绘可能铺几百个单元）
    std::unique_ptr<Gdiplus::Bitmap> img_cache_;
    std::wstring img_cache_path_;
    long long img_cache_mtime_ = 0;
    Gdiplus::REAL img_cache_scale_ = -1.0f;
    // 上一次加载失败的路径，避免每帧刷同一条警告
    std::wstring img_fail_path_;
};

// overlay 窗口的窗口过程，main.cpp 注册窗口类时用
LRESULT CALLBACK OverlayWndProc(HWND, UINT, WPARAM, LPARAM);

}  // namespace sw
