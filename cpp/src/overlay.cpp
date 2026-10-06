// overlay.cpp —— 每显示器一个分层窗口，把水印预渲染成一张 32bpp 预乘 alpha 位图再贴上去。
//
// 结构：
//   MakeTextUnit / MakeImageUnit 只负责「一个单元里画什么、尺寸多大」
//   TileUnit 只负责「怎么铺满一屏」（平铺 / 旋转 / 行列数 / 四边夹取）
// 这样图片水印和文字水印共用同一套平铺规则（§6）。
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
// 强制模式下把单元夹进画布时留的边距，抗锯齿边缘不至于贴边
const REAL kEdgePad = 3.0f;

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

// PNG 编码器的 CLSID，写死比 CLSIDFromString 省一坨代码
const CLSID kPngEncoder = {
    0x557cf406, 0x1a04, 0x11d3, {0x9a, 0x73, 0x00, 0x00, 0xf8, 0x1e, 0xf3, 0x2e}};

// 把一张 32bppPArgb 位图写盘；SW_DUMP_DIB=1 时用，验证「渲染出来的像素到底是什么」
void DumpBitmapIfAsked(Bitmap& bmp, const wchar_t* tag) {
    wchar_t v[8] = {0};
    DWORD n = ::GetEnvironmentVariableW(L"SW_DUMP_DIB", v, 8);
    if (n == 0 || v[0] != L'1') return;
    std::wstring path = JoinPath(ModuleDir(), std::wstring(tag) + L".png");
    bmp.Save(path.c_str(), &kPngEncoder, nullptr);
    DebugLog(L"已把 %s 写到 %s", tag, path.c_str());
}

// 文件的最后修改时间；拿不到返回 0（用来判断图片要不要重读盘）
long long FileMTime(const std::wstring& path) {
    WIN32_FILE_ATTRIBUTE_DATA fad{};
    if (!::GetFileAttributesExW(path.c_str(), GetFileExInfoStandard, &fad)) return 0;
    return ((long long)fad.ftLastWriteTime.dwHighDateTime << 32) |
           (long long)fad.ftLastWriteTime.dwLowDateTime;
}

// 按 '\n' 切行；空行也保留（"AAA\n\nBBB" 是 3 行，中间那行要占一行高度）
std::vector<std::wstring> SplitLines(const std::wstring& text) {
    std::vector<std::wstring> out;
    size_t start = 0;
    for (;;) {
        size_t nl = text.find(L'\n', start);
        if (nl == std::wstring::npos) {
            out.push_back(text.substr(start));
            return out;
        }
        out.push_back(text.substr(start, nl - start));
        start = nl + 1;
    }
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

// ---------------------------------------------------------------------------
// 单元构造
// ---------------------------------------------------------------------------

// 多行文字盒：text_w 取各行里最宽的，text_h = 行数 × 行高 × line_spacing。
// line_spacing 在 §2 里的定义就是「多行文本的行距倍数」，这里才真正用上
Overlay::Unit Overlay::MakeTextUnit(Graphics& g, Font& font, const std::wstring& text) {
    Unit u;
    u.font = &font;
    u.lines = SplitLines(text);

    StringFormat fmt;
    fmt.SetAlignment(StringAlignmentNear);
    fmt.SetLineAlignment(StringAlignmentNear);  // 顶对齐：旋转原点落在文字块左上角
    fmt.SetFormatFlags(StringFormatFlagsNoWrap);
    RectF layout(0.0f, 0.0f, 4000.0f, 4000.0f);

    REAL widest = 0.0f;
    for (const auto& ln : u.lines) {
        if (ln.empty()) continue;
        RectF b;
        g.MeasureString(ln.c_str(), -1, &font, layout, &fmt, &b);
        if (b.Width > widest) widest = b.Width;
    }

    const REAL line_h = (REAL)font.GetHeight(&g);
    u.line_step = line_h * (REAL)cfg_.line_spacing;
    // 每行的画布 y 自己算：GDI+ 的 DrawString 管不了行距倍数
    REAL dy = 0.0f;
    for (size_t i = 0; i < u.lines.size(); ++i) {
        u.text_dy.push_back(dy);
        dy += u.line_step;
    }

    int a = (int)std::lround(cfg_.opacity * 255.0);
    if (a < 1) a = 1;
    if (a > 255) a = 255;
    // 关键：PARGB 像素里的颜色分量必须是「已乘过 alpha」的值，GDI+ 不会再帮我们乘一次，
    // 所以手动预乘；漏了这步画出来会发黑
    const int rgb = ParseColorHex(cfg_.color, 0x808080);
    u.color = Color((BYTE)a, Premul((BYTE)((rgb >> 16) & 0xFF), (BYTE)a),
                    Premul((BYTE)((rgb >> 8) & 0xFF), (BYTE)a),
                    Premul((BYTE)(rgb & 0xFF), (BYTE)a));

    u.w = widest;
    u.h = (REAL)u.lines.size() * u.line_step;
    u.ok = widest > 0.0f && u.h > 0.0f;
    return u;
}

// 图片单元：按「路径 + 修改时间 + 缩放倍数」缓存，不每帧读盘。
// 整体透明度用 ImageAttributes + ColorMatrix 烘焙进缩放后的位图（§9 要求的做法）
Overlay::Unit Overlay::MakeImageUnit(Graphics& g) {
    Unit u;
    (void)g;
    if (cfg_.image.empty()) return u;

    const std::wstring& path = cfg_.image;
    const REAL scale = (REAL)cfg_.image_scale;
    const long long mtime = FileMTime(path);

    const bool cache_usable = img_cache_ && img_cache_path_ == path &&
                              img_cache_mtime_ == mtime && std::fabs(img_cache_scale_ - scale) < 1e-6f;
    if (!cache_usable) {
        img_cache_.reset();
        img_cache_path_.clear();
        img_cache_mtime_ = 0;
        img_cache_scale_ = -1.0f;

        if (mtime == 0) {
            // 文件不存在：同一条路径只警告一次，别每帧刷屏
            if (img_fail_path_ != path) {
                LogWarn(L"图片水印加载失败（找不到文件）：" + path + L"，已退回文字水印");
                img_fail_path_ = path;
            }
            return u;
        }
        Bitmap* src = new Bitmap(path.c_str(), FALSE);
        if (src->GetLastStatus() != Ok) {
            delete src;
            if (img_fail_path_ != path) {
                LogWarn(L"图片水印加载失败（不是能识别的图片格式）：" + path + L"，已退回文字水印");
                img_fail_path_ = path;
            }
            return u;
        }
        const int sw = (int)src->GetWidth();
        const int sh = (int)src->GetHeight();
        int dw = (int)std::lround(sw * (double)scale);
        int dh = (int)std::lround(sh * (double)scale);
        if (dw < 1) dw = 1;
        if (dh < 1) dh = 1;
        if (dw > kMaxDim) dw = kMaxDim;
        if (dh > kMaxDim) dh = kMaxDim;

        Bitmap* scaled = new Bitmap(dw, dh, PixelFormat32bppPARGB);
        {
            Graphics sg(scaled);
            sg.SetCompositingMode(CompositingModeSourceCopy);
            sg.SetInterpolationMode(InterpolationModeHighQualityBicubic);
            sg.SetPixelOffsetMode(PixelOffsetModeHighQuality);
            int a = (int)std::lround(cfg_.opacity * 255.0);
            if (a < 1) a = 1;
            if (a > 255) a = 255;
            // 整体 alpha 用 ColorMatrix：GDI+ 的原生做法，PNG 自带的 alpha 会被一起保留
            ColorMatrix cm = {};
            cm.m[0][0] = 1.0f;
            cm.m[1][1] = 1.0f;
            cm.m[2][2] = 1.0f;
            cm.m[3][3] = (REAL)a / 255.0f;
            cm.m[4][4] = 1.0f;
            ImageAttributes ia;
            ia.SetColorMatrix(&cm, ColorMatrixFlagsDefault, ColorAdjustTypeBitmap);
            Rect dest(0, 0, dw, dh);
            sg.DrawImage(src, dest, 0, 0, sw, sh, UnitPixel, &ia);
        }
        delete src;

        img_cache_.reset(scaled);
        img_cache_path_ = path;
        img_cache_mtime_ = mtime;
        img_cache_scale_ = scale;
        img_fail_path_.clear();
        DebugLog(L"图片水印已加载: %s 原图 %dx%d 缩放 %.2f -> %dx%d", path.c_str(), sw, sh,
                 (double)scale, dw, dh);
    }

    if (!img_cache_ || img_cache_->GetLastStatus() != Ok) return u;
    u.img = img_cache_.get();
    u.w = (REAL)img_cache_->GetWidth();
    u.h = (REAL)img_cache_->GetHeight();
    u.ok = u.w >= 1.0f && u.h >= 1.0f;
    return u;
}

// ---------------------------------------------------------------------------
// 平铺
// ---------------------------------------------------------------------------

void Overlay::TileUnit(Graphics& g, const Unit& unit, int w_px, int h_px) {
    if (!unit.ok) return;

    const REAL text_w = unit.w;  // 单元内容的实测宽高
    const REAL text_h = unit.h;

    // 两种平铺模式：
    //   自动（cols/rows 为 0）：单元尺寸由内容 + gap 决定，向四周各多铺一格补旋转后的四角
    //   强制（cols/rows > 0）：单元尺寸 = 屏尺寸 / 行列数，正好画 cols 列 rows 行
    // 两个方向可以混用（比如只强制列数、行数仍自动）
    const bool force_cols = cfg_.cols > 0;
    const bool force_rows = cfg_.rows > 0;

    REAL cell_w = text_w + (REAL)cfg_.gap_x;
    REAL cell_h = text_h + (REAL)cfg_.gap_y;
    if (force_cols) cell_w = (REAL)w_px / (REAL)cfg_.cols;
    if (force_rows) cell_h = (REAL)h_px / (REAL)cfg_.rows;
    // 兜底：单元尺寸退化到不足 1 像素就没法平铺了，直接跳过这一帧（也防死循环）
    if (cell_w < 1.0f || cell_h < 1.0f) return;

    const REAL ang = (REAL)(-cfg_.angle);  // 规格说逆时针为正，GDI+ 正角度是顺时针

    // 内容是绕单元左上角旋转的，旋转后会跑出单元矩形。算出四个外延量，
    // 用来决定「整体挪多少」和「夹多少」。
    // 漏了这步，angle<0 时第一行会被甩到 y<0 直接切掉（主人用的就是 -30，必现）
    const REAL rad = ang * 3.14159265358979f / 180.0f;
    const REAL cs = (REAL)std::cos((double)rad);
    const REAL sn = (REAL)std::sin((double)rad);
    REAL x_min = 0.0f, x_max = 0.0f, y_min = 0.0f, y_max = 0.0f;
    for (int ix = 0; ix < 2; ++ix) {
        for (int iy = 0; iy < 2; ++iy) {
            const REAL cx = (ix ? text_w : 0.0f);
            const REAL cy = (iy ? text_h : 0.0f);
            const REAL tx = cx * cs - cy * sn;
            const REAL ty = cx * sn + cy * cs;
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

    // 旋转会把内容甩出单元范围，四周留一个对角线长度的余量，否则四边会出现空白带。
    // 只给「自动的那一维」加，且强制维度为 0，这样自动模式算出来和以前一模一样
    int pad;
    {
        REAL need = (REAL)std::ceil(std::sqrt((double)(text_w * text_w + text_h * text_h))) + 2.0f;
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
    DebugLog(L"网格: 模式=%s%s %s cell=%.2fx%.2f 单元=%.1fx%.1f 列=%d 行=%d 单元总数=%lld "
             L"抽稀step=%d pad=%d 外延(左%.1f 右%.1f 上%.1f 下%.1f) 起点=%.1f,%.1f",
             force_cols ? L"强制列" : L"自动列", force_rows ? L"+强制行" : L"+自动行",
             unit.img ? L"图片" : L"文字", cell_w, cell_h, text_w, text_h, nx, ny, total, step, pad,
             -x_min, x_max, -y_min, y_max, x0, y0);

    SolidBrush text_brush(unit.color);
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
            // 这一格内容盒左上角的最终位置：强制维度上把它夹进画布内。
            // 旋转会让内容盒比格子宽/高（大角度时宽很多），不做夹取就会被切掉
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
                    DebugLog(L"  越界跳过: x=%.1f y=%.1f (列%d 行%d) 内容框=[%.1f,%.1f]x[%.1f,%.1f]",
                             x, y, ix, iy, bx0, bx1, by0, by1);
                continue;
            }
            // 整块只平移 + 旋转一次，块内各行不再各自旋转
            g.TranslateTransform(tx2, ty2);
            g.RotateTransform(ang);
            if (unit.img) {
                // 图片自带 alpha（PNG 透明区不会被画成黑），整体透明度已经烘进缓存位图
                g.DrawImage(unit.img, RectF(0.0f, 0.0f, text_w, text_h));
            } else {
                for (size_t li = 0; li < unit.lines.size(); ++li) {
                    if (unit.lines[li].empty()) continue;  // 空行照样占高度，只是不画东西
                    g.DrawString(unit.lines[li].c_str(), -1, unit.font,
                                 PointF(0.0f, unit.text_dy[li]), nullptr, &text_brush);
                }
            }
            g.ResetTransform();
            ++drawn;
            // 前几个单元把坐标打出来：验证「正好 cols 列 rows 行」和间距时，
            // 数截图容易看错，坐标是硬证据
            if (drawn <= 16)
                DebugLog(L"  单元#%lld: x=%.1f y=%.1f (列%d 行%d) 画在=%.1f,%.1f", drawn, x, y, ix,
                         iy, tx2, ty2);
        }
    }
    DebugLog(L"网格: 实际绘制单元=%lld 越界跳过=%lld", drawn, clipped);
}

// 建好字体 + 决定用图片还是文字 + 平铺；两条位图路径共用
void Overlay::DrawWatermark(Graphics& g, int w_px, int h_px, UINT dpi) {
    const double d = (double)(dpi ? dpi : 96);
    REAL em = (REAL)(cfg_.font_size * d / 72.0);  // 配置用磅，GDI+ 要像素
    if (em < 1) em = 1;
    std::wstring fam = PickFontFamily(cfg_.font_family);
    INT style = FontStyleRegular;
    if (cfg_.bold) style |= FontStyleBold;
    if (cfg_.italic) style |= FontStyleItalic;

    // image 非空就先试图片；加载失败会自动退回文字（MakeImageUnit 里已经 LogWarn 过）
    if (!cfg_.image.empty()) {
        Unit img = MakeImageUnit(g);
        if (img.ok) {
            TileUnit(g, img, w_px, h_px);
            return;
        }
    }

    const std::wstring text = ExpandIfTemplate(cfg_);
    if (text.empty()) return;  // 空文本：什么都不画，也不该崩
    // Gdiplus::Font 的赋值运算符是私有的，换字体只能用指针
    Font* font = new Font(fam.c_str(), em, style, UnitPixel);
    if (font->GetLastStatus() != Ok) {
        delete font;
        font = new Font(L"Microsoft YaHei", em, style, UnitPixel);
    }
    if (font->GetLastStatus() != Ok) {
        // 连通用字体都建不出来：放弃这一帧，别拿半成品对象去画。
        // 注意必须正常走到 delete，别在半路 return（早先有个分支漏了 memdc/dib 的清理）
        LogWarn(L"字体创建失败，本帧跳过水印渲染");
        delete font;
        return;
    }
    Unit tu = MakeTextUnit(g, *font, text);
    TileUnit(g, tu, w_px, h_px);
    delete font;
}

// ---------------------------------------------------------------------------
// 渲染到分层窗口
// ---------------------------------------------------------------------------

void Overlay::RenderTo(const Win& w) {
    const int w_px = w.rc.right - w.rc.left;
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
    // 兼容 DC 以屏幕 DC 为参照：UpdateLayeredWindow 要求源 DC 与目标屏幕兼容，
    // 用 CreateCompatibleDC(nullptr) 在某些配置下会直接返回 ERROR_GEN_FAILURE(31)
    HDC memdc = ::CreateCompatibleDC(screen);
    // 诊断开关：SW_GDI_DIB=1 时走「GDI+ 画进 DIB 再贴」的老路子，
    // 默认走「GDI+ 自己出位图 → 取 HBITMAP → 贴」，两条路都留着以便对比
    wchar_t mode[8] = {0};
    bool gdi_dib_mode = ::GetEnvironmentVariableW(L"SW_GDI_DIB", mode, 8) > 0;

    HBITMAP ready = nullptr;  // 非 DIB 模式下真正拿去贴的位图
    // 用指针而不是局部对象：GDI+ 位图必须活到 UpdateLayeredWindow 之后（GetHBITMAP 的
    // 句柄与它是同一份像素），提前析构会把图像内容一起带走
    Bitmap* canvas = nullptr;
    if (gdi_dib_mode) {
        // DIB 模式：自己 CreateDIBSection 再用 Gdiplus::Bitmap 包住它（§9 的原始写法）。
        // 保留它是为了回归对比：本机实测这条路上 UpdateLayeredWindow 稳定返回
        // ERROR_GEN_FAILURE(31)，所以默认走下面那条路。想复现就把 SW_GDI_DIB=1
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
        // 已经预乘好的 HBITMAP 交给分层窗口
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
        canvas->Save(dump_path_.c_str(), &kPngEncoder, nullptr);
        DebugLog(L"已把帧写到 %s", dump_path_.c_str());
        dump_path_.clear();
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
