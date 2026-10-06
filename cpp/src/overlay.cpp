#include "overlay.h"

#include <algorithm>
#include <cmath>
#include <cstring>

using namespace Gdiplus;

namespace sw {
namespace {

// 单元数上限：角度 / 间距取极端值时单元会爆到几十万，宁可漏铺也不能卡死（§6）
const int kMaxCells = 20000;
// 位图尺寸上限，防止虚拟分辨率被搞成天文数字
const int kMaxDim = 16384;

// 字体名容错：配置里的字体可能没装，挨个回退，最后用通用 sans-serif 兜底
std::wstring PickFontFamily(const std::wstring& want) {
    if (!want.empty()) {
        FontFamily probe(want.c_str());
        if (probe.GetLastStatus() == Ok) return want;
    }
    const wchar_t* fallbacks[] = {L"Microsoft YaHei", L"SimSun", L"Segoe UI", L"Arial"};
    for (const wchar_t* f : fallbacks) {
        FontFamily ff(f);
        if (ff.GetLastStatus() == Ok) return f;
    }
    return L"sans-serif";
}

// PARGB 里颜色分量必须已经乘过 alpha，GDI+ 不会再帮我们乘一次
inline BYTE Premul(BYTE c, BYTE a) { return (BYTE)(((unsigned)c * a + 127) / 255); }

// 把一张 32bppPArgb 位图写盘；SW_DUMP_DIB=1 时用，验证「渲染出来的像素到底是什么」
void DumpBitmapIfAsked(Bitmap& bmp, const wchar_t* tag) {
    wchar_t v[8] = {0};
    DWORD n = ::GetEnvironmentVariableW(L"SW_DUMP_DIB", v, 8);
    if (n == 0 || v[0] != L'1') return;
    CLSID png{0x557cf406, 0x1a04, 0x11d3, {0x9a, 0x73, 0x00, 0x00, 0xf8, 0x1e, 0xf3, 0x2e}};
    std::wstring path = JoinPath(ModuleDir(), std::wstring(tag) + L".png");
    bmp.Save(path.c_str(), &png, nullptr);
    DebugLog(L"已把 %s 写到 %s", tag, path.c_str());
}

}  // namespace

Overlay::~Overlay() { DestroyWindows(); }

std::vector<HWND> Overlay::window_handles() const {
    std::vector<HWND> out;
    out.reserve(wins_.size());
    for (const auto& w : wins_) out.push_back(w.hwnd);
    return out;
}

LRESULT CALLBACK OverlayWndProc(HWND h, UINT m, WPARAM w, LPARAM l) {
    // 诊断开关：SW_BARE_WNDPROC=1 时退回 DefWindowProc，用来确认失败是否与窗口过程有关
    {
        static int bare = -1;
        if (bare < 0) {
            wchar_t v[8] = {0};
            bare = (::GetEnvironmentVariableW(L"SW_BARE_WNDPROC", v, 8) > 0) ? 1 : 0;
        }
        if (bare) return ::DefWindowProcW(h, m, w, l);
    }
    switch (m) {
        // 分层窗口的内容全靠 UpdateLayeredWindow 提供，这两个消息必须吃掉，
        // 否则系统会用没画过的窗口背景把水印擦掉
        case WM_ERASEBKGND: return 1;
        case WM_PAINT: {
            PAINTSTRUCT ps{};
            ::BeginPaint(h, &ps);
            ::EndPaint(h, &ps);
            return 0;
        }
        // 点击穿透时这些消息根本到不了这里；不穿透时也别让水印窗口抢焦点
        case WM_MOUSEACTIVATE: return MA_NOACTIVATE;
        case WM_NCHITTEST: return HTTRANSPARENT;
        default: break;
    }
    return ::DefWindowProcW(h, m, w, l);
}

void Overlay::InvalidateMonitors() { monitors_dirty_ = true; }

void Overlay::Shutdown() { DestroyWindows(); }

void Overlay::DestroyWindows() {
    for (auto& w : wins_)
        if (w.hwnd) ::DestroyWindow(w.hwnd);
    wins_.clear();
}

bool Overlay::MakeBackBuffer(int w, int h, HBITMAP& bmp, void** bits) const {
    BITMAPINFO bi{};
    bi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
    bi.bmiHeader.biWidth = w;
    bi.bmiHeader.biHeight = -h;  // 负高度 = top-down，和 GDI+ 的行序一致，省得上下颠倒
    bi.bmiHeader.biPlanes = 1;
    bi.bmiHeader.biBitCount = 32;
    bi.bmiHeader.biCompression = BI_RGB;
    HDC screen = ::GetDC(nullptr);
    bmp = ::CreateDIBSection(screen, &bi, DIB_RGB_COLORS, bits, nullptr, 0);
    ::ReleaseDC(nullptr, screen);
    return bmp != nullptr && *bits != nullptr;
}

void Overlay::RenderCells(Graphics& g, Font& font, int w_px, int h_px, const std::wstring& text) {
    StringFormat fmt;
    fmt.SetAlignment(StringAlignmentNear);      // 左对齐
    fmt.SetLineAlignment(StringAlignmentNear);  // 顶对齐，旋转原点才在文字左上角
    // 不折行：折了单元宽度就不等于 text_width，平铺会错位
    fmt.SetFormatFlags(StringFormatFlagsNoWrap);

    int a = (int)std::lround(cfg_.opacity * 255.0);
    if (a < 1) a = 1;
    if (a > 255) a = 255;
    // 关键：PARGB 像素里的颜色分量必须是「已乘过 alpha」的值。GDI+ 在 PARGB 表面上
    // 不会再帮我们乘，所以这里手动预乘；漏了这步画出来会发黑
    const int rgb = ParseColorHex(cfg_.color, 0x808080);
    BYTE cr = Premul((BYTE)((rgb >> 16) & 0xFF), (BYTE)a);
    BYTE cg = Premul((BYTE)((rgb >> 8) & 0xFF), (BYTE)a);
    BYTE cb = Premul((BYTE)(rgb & 0xFF), (BYTE)a);
    Color color((BYTE)a, cr, cg, cb);
    SolidBrush brush(color);

    // 布局矩形给足空间，MeasureString 才能量出真实文本宽度
    RectF layout(0.0f, 0.0f, 4000.0f, 4000.0f);
    RectF bounds;
    g.MeasureString(text.c_str(), -1, &font, layout, &fmt, &bounds);

    const REAL text_w = bounds.Width;
    const REAL font_px = (REAL)font.GetHeight(&g);

    // 两种平铺模式：
    //   自动（cols/rows 为 0）：单元尺寸由文字 + gap 决定，向四周各多铺一格补旋转后的四角
    //   强制（cols/rows > 0）：单元尺寸 = 屏尺寸 / 行列数，从原点起正好画 cols 列 rows 行，
    //                        不向外扩（用户要的就是「每行几个、每列几个」）
    // 两个方向可以混用（比如只强制列数、行数仍自动）
    const bool force_cols = cfg_.cols > 0;
    const bool force_rows = cfg_.rows > 0;

    REAL cell_w = text_w + (REAL)cfg_.gap_x;
    REAL cell_h = font_px * (REAL)cfg_.line_spacing + (REAL)cfg_.gap_y;
    if (force_cols) cell_w = (REAL)w_px / (REAL)cfg_.cols;
    if (force_rows) cell_h = (REAL)h_px / (REAL)cfg_.rows;
    // 兜底：单元尺寸退化到不足 1 像素就没法平铺了，直接跳过这一帧（也防死循环）
    if (text_w <= 0.5f || cell_w < 1.0f || cell_h < 1.0f) return;

    const REAL ang = (REAL)(-cfg_.angle);  // 规格说逆时针为正，GDI+ 正角度是顺时针

    // 文字是绕单元左上角旋转的，旋转后它会跑出单元矩形：
    //   ox = 向右最远能到多少（相对单元左上角），oy = 向下最远能到多少
    // 用它来决定「整体要挪多少」和「可用空间要扣掉多少」。
    // 漏了这一步，angle<0 时第一行会被甩到 y<0 直接切掉（主人用的就是 -30，必现）
    const REAL rad = ang * 3.14159265358979f / 180.0f;
    const REAL cs = (REAL)std::cos((double)rad);
    const REAL sn = (REAL)std::sin((double)rad);
    REAL x_min = 0.0f, x_max = 0.0f, y_min = 0.0f, y_max = 0.0f;
    for (int ix = 0; ix < 2; ++ix) {
        for (int iy = 0; iy < 2; ++iy) {
            const REAL px_ = (ix ? text_w : 0.0f);
            const REAL py_ = (iy ? font_px : 0.0f);
            const REAL tx = px_ * cs - py_ * sn;
            const REAL ty = px_ * sn + py_ * cs;
            if (ix == 0 && iy == 0) {
                x_min = x_max = tx;
                y_min = y_max = ty;
            } else {
                if (tx < x_min) x_min = tx;
                if (tx > x_max) x_max = tx;
                if (ty < y_min) y_min = ty;
                if (ty > y_max) y_max = ty;
            }
        }
    }
    const REAL left_ov = -x_min;    // >0 表示文字会往左探出单元
    const REAL right_ov = x_max;    // >0 表示文字会往右探出单元
    const REAL top_ov = -y_min;     // >0 表示文字会往上探出单元（负角度就是这种）
    const REAL bottom_ov = y_max;   // >0 表示文字会往下探出单元
    const REAL kEdgePad = 3.0f;     // 抗锯齿的边缘留一点点余量

    // 强制的那一维：平分整幅画布，格子数才严格等于 cols/rows。
    // 注意不要用「可用宽度 / cols」——那样格子变小、最后一列的起点被推到画布外，
    // 循环会提前 break，实测 4 列只剩 3 列。旋转造成的溢出留给下面的文字盒夹取处理
    if (force_cols) cell_w = (REAL)w_px / (REAL)cfg_.cols;
    if (force_rows) cell_h = (REAL)h_px / (REAL)cfg_.rows;
    if (cell_w < 1.0f || cell_h < 1.0f) return;

    // 旋转会把文字甩出单元范围，四周留一个对角线长度的余量，否则四边会出现空白带。
    // 只给「自动的那一维」加，且强制维度为 0，这样自动模式算出来和以前一模一样
    int pad;
    {
        REAL need = (REAL)std::ceil(std::sqrt((double)(text_w * text_w + font_px * font_px))) + 2.0f;
        if (!force_cols) need += (REAL)cfg_.gap_x;
        if (!force_rows) need += (REAL)cfg_.gap_y;
        pad = (int)need;
    }
    if (pad > 4000) pad = 4000;

    // 起止位置和单元数：强制模式从画布原点铺到画布末端（正好 cols/rows 个），
    // 自动模式两端各多铺一格来补旋转后的四角
    REAL x0, y0, x1, y1;
    if (force_cols) {
        x0 = 0.0f;
        x1 = (REAL)w_px;
    } else {
        x0 = -(REAL)pad - cell_w;
        x1 = (REAL)w_px + cell_w;
    }
    if (force_rows) {
        y0 = 0.0f;
        y1 = (REAL)h_px;
    } else {
        y0 = -(REAL)pad - cell_h;
        y1 = (REAL)h_px + cell_h;
    }

    const int nx = force_cols ? cfg_.cols : (int)std::ceil((x1 - x0) / cell_w) + 1;
    const int ny = force_rows ? cfg_.rows : (int)std::ceil((y1 - y0) / cell_h) + 1;
    long long total = (long long)nx * (long long)ny;
    int step = 1;
    while (total / ((long long)step * step) > kMaxCells) ++step;  // 太密就隔行隔列抽稀

    // 把这一帧的网格参数记下来：验证「正好 cols 列 rows 行」时靠它，比数截图靠谱
    DebugLog(L"网格: 模式=%s%s cell=%.2fx%.2f 列=%d 行=%d 单元总数=%lld 抽稀step=%d "
             L"文字宽=%.1f 字号像素=%.1f pad=%d 外延(左%.1f 右%.1f 上%.1f 下%.1f) 起点=%.1f,%.1f",
             force_cols ? L"强制列" : L"自动列", force_rows ? L"+强制行" : L"+自动行", cell_w,
             cell_h, nx, ny, total, step, text_w, font_px, pad, left_ov, right_ov, top_ov,
             bottom_ov, x0, y0);

    // 用整数计数 + 乘法定位，而不是浮点累加：累加在极端单元尺寸下会有舍入漂移，
    // 强制模式下就画不出「正好 cols 列 rows 行」了
    long long drawn = 0;
    long long clipped = 0;
    for (int iy = 0; iy < ny; ++iy) {
        if (step > 1 && (iy % step) != 0) continue;
        const REAL y = y0 + (REAL)iy * cell_h;
        if (y >= y1 - 0.5f) break;
        REAL rowx = x0;
        if (cfg_.phase_offset && (iy & 1)) rowx += cell_w * 0.5f;  // 奇数行错开半格
        for (int ix = 0; ix < nx; ++ix) {
            if (step > 1 && (ix % step) != 0) continue;
            const REAL x = rowx + (REAL)ix * cell_w;
            if (x >= x1 - 0.5f) break;
            // 这一格文字盒左上角的最终位置：强制维度上把它夹进画布内。
            // 旋转会让文字盒比格子宽/高（大角度时宽很多），不做夹取就会被切掉；
            // 夹取只在盒子放得下时进行，放不下就交给下面的保险跳过
            REAL tx2 = x + (pad ? 0.0f : kEdgePad);
            REAL ty2 = y + (pad ? 0.0f : kEdgePad);
            if (force_cols && x_max - x_min <= (REAL)w_px) {
                if (tx2 + x_min < kEdgePad) tx2 = kEdgePad - x_min;
                if (tx2 + x_max > (REAL)w_px - kEdgePad) tx2 = (REAL)w_px - kEdgePad - x_max;
            }
            if (force_rows && y_max - y_min <= (REAL)h_px) {
                if (ty2 + y_min < kEdgePad) ty2 = kEdgePad - y_min;
                if (ty2 + y_max > (REAL)h_px - kEdgePad) ty2 = (REAL)h_px - kEdgePad - y_max;
            }
            // 最后一道保险。只对「强制的那一维」生效：
            // 自动模式本来就会向屏幕外多铺一圈（那是补旋转四角的正常手法），
            // 对它做越界检查会把正常单元误杀（实测过：126 个单元被砍掉 87 个）
            const REAL bx0 = tx2 + x_min, bx1 = tx2 + x_max;
            const REAL by0 = ty2 + y_min, by1 = ty2 + y_max;
            bool oob = false;
            if (force_cols && (bx0 < -0.5f || bx1 > (REAL)w_px + 0.5f)) oob = true;
            if (force_rows && (by0 < -0.5f || by1 > (REAL)h_px + 0.5f)) oob = true;
            if (oob) {
                ++clipped;
                if (clipped <= 8)
                    DebugLog(L"  越界跳过: x=%.1f y=%.1f (列%d 行%d) 文字框=[%.1f,%.1f]x[%.1f,%.1f]",
                             x, y, ix, iy, bx0, bx1, by0, by1);
                continue;
            }
            // 平移量里带上 pad，绘制点就回到单元原点，等价于「先平移再绕原点旋转」
            g.TranslateTransform(tx2, ty2);
            g.RotateTransform(ang);
            g.DrawString(text.c_str(), -1, &font, PointF(0.0f, 0.0f), &fmt, &brush);
            g.ResetTransform();
            ++drawn;
            // 前几个单元把坐标打出来：验证「正好 cols 列 rows 行」和间距时，
            // 数截图容易看错，坐标是硬证据
            if (drawn <= 16)
                DebugLog(L"  单元#%lld: x=%.1f y=%.1f (列%d 行%d) 画在=%.1f,%.1f", drawn, x, y, ix, iy,
                         tx2, ty2);
        }
    }
    DebugLog(L"网格: 实际绘制单元=%lld 越界跳过=%lld", drawn, clipped);
}

// 建好字体后把整屏水印画到给定 Graphics 上；两条渲染路径共用
void Overlay::DrawWatermark(Graphics& g, int w_px, int h_px, UINT dpi) {
    const std::wstring text = ExpandIfTemplate(cfg_);
    if (text.empty()) return;
    const double d = (double)(dpi ? dpi : 96);
    REAL em = (REAL)(cfg_.font_size * d / 72.0);  // 配置用磅，GDI+ 要像素
    if (em < 1) em = 1;
    std::wstring fam = PickFontFamily(cfg_.font_family);
    INT style = FontStyleRegular;
    if (cfg_.bold) style |= FontStyleBold;
    if (cfg_.italic) style |= FontStyleItalic;
    // Gdiplus::Font 的赋值运算符是私有的，换字体只能用指针
    Font* font = new Font(fam.c_str(), em, style, UnitPixel);
    if (font->GetLastStatus() != Ok) {
        delete font;
        font = new Font(L"Microsoft YaHei", em, style, UnitPixel);
    }
    if (font->GetLastStatus() == Ok) RenderCells(g, *font, w_px, h_px, text);
    delete font;
}

void Overlay::RenderTo(const Win& w) {    const int w_px = w.rc.right - w.rc.left;
    const int h_px = w.rc.bottom - w.rc.top;
    if (w_px <= 0 || h_px <= 0 || w_px > kMaxDim || h_px > kMaxDim) return;

    HBITMAP dib = nullptr;
    void* bits = nullptr;
    if (!MakeBackBuffer(w_px, h_px, dib, &bits)) {
        // 内存不够时别把窗口留成黑的，直接不贴图
        if (dib) ::DeleteObject(dib);
        return;
    }
    const int stride = w_px * 4;

    HDC screen = ::GetDC(nullptr);
    HDC memdc = ::CreateCompatibleDC(screen);

    // 贴图用 GDI+ 自管的 32bppPArgb 位图，而不是自己 CreateDIBSection。
    // 原因（本机实测）：用 Gdiplus::Bitmap 包住 CreateDIBSection 的像素时，
    // 即使 Graphics/Bitmap 已析构，UpdateLayeredWindow 也会稳定返回
    // ERROR_GEN_FAILURE(31)；换成 GDI+ 自己分配位图再用 GetHBITMAP 取句柄就正常。
    // 走 SW_GDI_DIB=1 可以复现旧路径，方便以后换机器时对比。
    wchar_t mode[8] = {0};
    bool gdi_dib_mode = ::GetEnvironmentVariableW(L"SW_GDI_DIB", mode, 8) > 0;

    HBITMAP ready = nullptr;  // 非 DIB 模式下真正拿去贴的位图
    // 用指针而不是局部对象：GDI+ 位图必须活到 UpdateLayeredWindow 之后（GetHBITMAP 的
    // 句柄与它是同一份像素），提前析构会把图像内容一起带走
    Bitmap* canvas = nullptr;
    if (gdi_dib_mode) {
        // DIB 模式：自己 CreateDIBSection 再用 Gdiplus::Bitmap 包住它（设计规格 §9 的原始写法）。
        // 保留它是为了回归对比：本机实测这条路上 UpdateLayeredWindow 稳定返回
        // ERROR_GEN_FAILURE(31)（GDI+ 释放对 DIB 像素的锁定之后，那块内存仍不被接受），
        // 所以默认走下面那条路。想复现就把 SW_GDI_DIB=1。
        HGDIOBJ oldbmp = memdc ? ::SelectObject(memdc, dib) : nullptr;
        if (memdc && oldbmp) {
            Bitmap bmp((INT)w_px, (INT)h_px, (INT)stride, PixelFormat32bppPARGB, (BYTE*)bits);
            Graphics g(&bmp);
            g.SetCompositingMode(CompositingModeSourceCopy);
            g.Clear(Color(0, 0, 0, 0));
            g.SetCompositingMode(CompositingModeSourceOver);
            g.SetSmoothingMode(SmoothingModeAntiAlias);
            g.SetTextRenderingHint(TextRenderingHintAntiAlias);
            g.SetPixelOffsetMode(PixelOffsetModeHalf);
            DrawWatermark(g, w_px, h_px, w.dpi);
        }
        if (memdc && oldbmp) ::SelectObject(memdc, oldbmp);
    } else {
        // 默认路径：让 GDI+ 自己分配并渲染一张 32bppPArgb 位图，再用 GetHBITMAP 取出
        // 已经预乘好的 HBITMAP 交给分层窗口。渲染对象和贴图对象是同一个，不用自己
        // 管 DIB 像素的生命周期，实测在本机稳定成功
        canvas = new Bitmap((INT)w_px, (INT)h_px, PixelFormat32bppPARGB);
        Graphics g(canvas);
        g.SetCompositingMode(CompositingModeSourceCopy);
        g.Clear(Color(0, 0, 0, 0));
        g.SetCompositingMode(CompositingModeSourceOver);
        g.SetSmoothingMode(SmoothingModeAntiAlias);
        g.SetTextRenderingHint(TextRenderingHintAntiAlias);
        g.SetPixelOffsetMode(PixelOffsetModeHalf);
        DrawWatermark(g, w_px, h_px, w.dpi);
        if (g.GetLastStatus() == Ok) {
            Color key(0, 0, 0, 0);
            if (canvas->GetHBITMAP(key, &ready) != Ok) ready = nullptr;
        }
    }

    POINT src{0, 0};
    POINT dst{w.rc.left, w.rc.top};
    SIZE size{w_px, h_px};
    BLENDFUNCTION bf{};
    bf.BlendOp = AC_SRC_OVER;
    bf.SourceConstantAlpha = 255;
    bf.AlphaFormat = AC_SRC_ALPHA;
    ::SetLastError(0);
    BOOL ok = FALSE;
    HGDIOBJ keep = nullptr;
    if (memdc) {
        if (ready) keep = ::SelectObject(memdc, ready);
        ok = ::UpdateLayeredWindow(w.hwnd, screen, &dst, &size, memdc, &src, 0, &bf, ULW_ALPHA);
    }
    if (canvas) DumpBitmapIfAsked(*canvas, L"overlay-canvas.png");
    // 诊断：把这一帧写到调用方指定的路径，写完清标志（一次请求写一帧）
    if (canvas && !dump_path_.empty()) {
        CLSID png{};
        png = {0x557cf406, 0x1a04, 0x11d3, {0x9a, 0x73, 0x00, 0x00, 0xf8, 0x1e, 0xf3, 0x2e}};
        Status st = canvas->Save(dump_path_.c_str(), &png, nullptr);
        DebugLog(L"落帧 %s -> status=%d", dump_path_.c_str(), (int)st);
        dump_path_.clear();
    } else if (!canvas) {
        DebugLog(L"落帧被跳过：canvas 为空（SW_GDI_DIB 模式？）");
    }
    // UpdateLayeredWindow 失败的窗口会是一块全透明，日志里必须有痕迹
    if (!memdc || !ok)
        DebugLog(L"UpdateLayeredWindow 失败 ok=%d err=%lu（%dx%d）", ok ? 1 : 0, ::GetLastError(),
                 w_px, h_px);
    if (keep) ::SelectObject(memdc, keep);
    delete canvas;  // 贴完才能放，GetHBITMAP 的句柄和它是同一份像素
    if (ready) ::DeleteObject(ready);
    ::ReleaseDC(nullptr, screen);
    if (memdc) ::DeleteDC(memdc);
    ::DeleteObject(dib);
}

bool Overlay::EnsureWindows(const std::vector<MonitorRect>& want) {
    // 显示器集合一致且尺寸没变就复用，避免每次改配置都闪一下
    bool same = (want.size() == wins_.size());
    if (same) {
        for (size_t i = 0; i < want.size(); ++i) {
            const RECT& a = want[i].rc;
            const RECT& b = wins_[i].rc;
            if (a.left != b.left || a.top != b.top || a.right != b.right || a.bottom != b.bottom) {
                same = false;
                break;
            }
        }
    }
    if (!same || wins_.empty()) {
        DestroyWindows();
        for (const auto& m : want) {
            int w = m.rc.right - m.rc.left;
            int h = m.rc.bottom - m.rc.top;
            if (w <= 0 || h <= 0) continue;
            DWORD ex = WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TOPMOST;
            if (cfg_.click_through) ex |= WS_EX_TRANSPARENT;
            HWND hwnd = ::CreateWindowExW(ex, kOverlayWndClass, L"", WS_POPUP, m.rc.left, m.rc.top,
                                          w, h, nullptr, nullptr, ::GetModuleHandleW(nullptr),
                                          nullptr);
            if (!hwnd) continue;  // 单块屏失败不该拖垮整个程序
            // 先只定位不显示：内容没贴上去的窗口显示出来就是一块黑，等 RenderTo 完再显示
            ::SetWindowPos(hwnd, HWND_TOPMOST, m.rc.left, m.rc.top, w, h, SWP_NOACTIVATE);
            Win win;
            win.hwnd = hwnd;
            win.rc = m.rc;
            win.dpi = DpiForWindowSafe(hwnd);
            wins_.push_back(win);
        }
        return !wins_.empty();
    }
    // 复用路径：只同步 click_through（运行期唯一能改的窗口样式）
    for (auto& w : wins_) {
        LONG_PTR ex = ::GetWindowLongPtrW(w.hwnd, GWL_EXSTYLE);
        LONG_PTR nv = cfg_.click_through ? (ex | WS_EX_TRANSPARENT) : (ex & ~WS_EX_TRANSPARENT);
        if (nv != ex) ::SetWindowLongPtrW(w.hwnd, GWL_EXSTYLE, nv);
    }
    return true;
}

void Overlay::Apply(const Config& cfg) {
    cfg_ = cfg;
    ClampConfig(cfg_);

    if (!cfg_.enabled) {
        for (auto& w : wins_) ::ShowWindow(w.hwnd, SW_HIDE);
        return;
    }

    std::vector<MonitorRect> want;
    if (cfg_.all_monitors) {
        want = ListMonitors();
    } else {
        MonitorRect m;
        m.rc = PrimaryMonitorRect();
        want.push_back(m);
    }
    if (want.size() != last_monitors_.size()) monitors_dirty_ = true;
    last_monitors_ = want;

    if (!EnsureWindows(want)) return;
    monitors_dirty_ = false;

    DebugLog(L"Apply: 窗口 %zu 个", wins_.size());
    for (auto& w : wins_) {
        // 窗口挪到别的显示器后 DPI 可能变了，磅值要跟着重算
        UINT dpi = DpiForWindowSafe(w.hwnd);
        if (dpi != w.dpi) w.dpi = dpi;
        RenderTo(w);
        // 贴完内容再显示，避免闪一下黑块
        ::ShowWindow(w.hwnd, SW_SHOWNOACTIVATE);
    }
}

void Overlay::Refresh() {
    if (!cfg_.enabled) return;
    for (auto& w : wins_) RenderTo(w);
}

}  // namespace sw
