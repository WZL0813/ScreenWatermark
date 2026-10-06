#include "settings.h"

#include <commctrl.h>
#include <commdlg.h>

#include <algorithm>
#include <cmath>
#include <cstdarg>
#include <cstdio>
#include <cwchar>
#include <vector>

#include "util.h"

namespace sw {
namespace {

// 控件 ID（IDC_LINESPACING 排在最后，避免打乱已有编号）
enum : int {
    IDC_TEXT = 1001,
    IDC_FONTSIZE,
    IDC_FONTFAMILY,
    IDC_BOLD,
    IDC_ITALIC,
    IDC_OPACITY,
    IDC_OPACITY_LABEL,
    IDC_ANGLE,
    IDC_ANGLE_LABEL,
    IDC_GAPX,
    IDC_GAPY,
    IDC_COLOR,
    IDC_COLOR_PREVIEW,
    IDC_TEMPLATE,
    IDC_TIMEFMT,
    IDC_LIVEPREVIEW,
    IDC_ALLMON,
    IDC_PHASE,
    IDC_CLICKTHROUGH,
    IDC_APPLY,
    IDC_HIDE,
    IDC_SAVE,
    IDC_RESET,
    IDC_HINT,
    IDC_STATUS,
    IDC_LINESPACING,
    IDC_TIMER_TICK = 2001,
};

// 面板固定尺寸，坐标按 96 DPI 设计，运行时按 dpi/96 缩放
const int kClientW = 520;
const int kClientH = 520;
const int kMarginX = 14;
const int kEditH = 24;
const int kRowH = 30;

std::wstring Fmt(const wchar_t* f, ...) {
    wchar_t buf[256];
    va_list ap;
    va_start(ap, f);
    _vsnwprintf(buf, 255, f, ap);
    va_end(ap);
    buf[255] = L'\0';
    return std::wstring(buf);
}

// 只比较会影响渲染的字段：面板靠它判断用户有没有真的改东西
bool SameRenderConfig(const Config& a, const Config& b) {
    return a.text == b.text && a.font_family == b.font_family && a.font_size == b.font_size &&
           a.bold == b.bold && a.italic == b.italic && a.color == b.color &&
           std::fabs(a.opacity - b.opacity) < 1e-6 && a.angle == b.angle &&
           a.gap_x == b.gap_x && a.gap_y == b.gap_y &&
           std::fabs(a.line_spacing - b.line_spacing) < 1e-6 && a.enabled == b.enabled &&
           a.click_through == b.click_through && a.templ == b.templ &&
           a.time_format == b.time_format && a.refresh_seconds == b.refresh_seconds &&
           a.all_monitors == b.all_monitors && a.phase_offset == b.phase_offset;
}

// EnumFontFamiliesExW 的回调没有闭包参数，只能靠文件级指针把结果带回来
std::vector<std::wstring>* g_fontNames = nullptr;

int CALLBACK CollectFontProc(const LOGFONTW* lf, const TEXTMETRICW*, DWORD, LPARAM) {
    // 以 '@' 开头的是竖排变体，放进列表只会让人困惑
    if (g_fontNames && lf && lf->lfFaceName[0] != L'@') g_fontNames->push_back(lf->lfFaceName);
    return 1;
}

}  // namespace

Settings::~Settings() {
    if (font_) ::DeleteObject(font_);
    if (brush_) ::DeleteObject(brush_);
    if (hwnd_) ::DestroyWindow(hwnd_);
}

LRESULT CALLBACK Settings::PanelProcThunk(HWND h, UINT m, WPARAM w, LPARAM l) {
    Settings* self = reinterpret_cast<Settings*>(::GetWindowLongPtrW(h, GWLP_USERDATA));
    if (m == WM_NCCREATE) {
        // lpCreateParams 只在 WM_NCCREATE 有效，先存进 GWLP_USERDATA
        auto* cs = reinterpret_cast<CREATESTRUCTW*>(l);
        self = reinterpret_cast<Settings*>(cs->lpCreateParams);
        ::SetWindowLongPtrW(h, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(self));
    }
    if (self) return self->PanelProc(h, m, w, l);
    return ::DefWindowProcW(h, m, w, l);
}

bool Settings::EnsureWindow() {
    if (hwnd_) return true;
    HINSTANCE inst = ::GetModuleHandleW(nullptr);
    WNDCLASSEXW wc{};
    wc.cbSize = sizeof(wc);
    wc.lpfnWndProc = PanelProcThunk;
    wc.hInstance = inst;
    wc.hCursor = ::LoadCursorW(nullptr, IDC_ARROW);
    wc.hbrBackground = (HBRUSH)(COLOR_BTNFACE + 1);
    wc.lpszClassName = L"ScreenWatermarkSettingsWnd";
    SetLastError(0);
    if (!::RegisterClassExW(&wc) && ::GetLastError() != ERROR_CLASS_ALREADY_EXISTS) return false;

    dpi_ = DpiForWindowSafe(parent_);
    RECT want{0, 0, (LONG)(kClientW * dpi_ / 96), (LONG)(kClientH * dpi_ / 96)};
    ::AdjustWindowRectEx(&want, WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX, FALSE, 0);
    int win_w = want.right - want.left;
    int win_h = want.bottom - want.top;
    // 放在鼠标所在显示器的中间：CW_USEDEFAULT 会把面板丢到左上角，甚至掉到屏幕外
    POINT cur{};
    ::GetCursorPos(&cur);
    HMONITOR mon = ::MonitorFromPoint(cur, MONITOR_DEFAULTTONEAREST);
    MONITORINFO mi{};
    mi.cbSize = sizeof(mi);
    int x = CW_USEDEFAULT, y = CW_USEDEFAULT;
    if (mon && ::GetMonitorInfoW(mon, &mi)) {
        x = mi.rcWork.left + (mi.rcWork.right - mi.rcWork.left - win_w) / 2;
        y = mi.rcWork.top + (mi.rcWork.bottom - mi.rcWork.top - win_h) / 2;
        if (x < mi.rcWork.left) x = mi.rcWork.left;
        if (y < mi.rcWork.top) y = mi.rcWork.top;
    }
    hwnd_ = ::CreateWindowExW(WS_EX_TOOLWINDOW, wc.lpszClassName, L"ScreenWatermark 设置",
                              WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX, x, y,
                              win_w, win_h, nullptr, nullptr, inst, this);
    if (!hwnd_) {
        MessageBoxW(nullptr, L"设置窗口创建失败。", kAppName, MB_ICONERROR | MB_OK);
        return false;
    }
    return true;
}

void Settings::BuildControls(HWND host) {
    // host 必须是 WM_CREATE 传进来的句柄：那时候 hwnd_ 还可能是空的（构造函数刚跑完，
    // 成员指针还没来得及更新），拿空句柄当父窗口建子控件会直接 ERROR_INVALID_WINDOW_HANDLE
    HINSTANCE inst = ::GetModuleHandleW(nullptr);
    auto px = [this](int v) { return (int)std::lround(v * dpi_ / 96.0); };
    // 控件创建都是同一套参数，包一层省得每行重复八个
    auto S = [&](int id, const wchar_t* cls, const wchar_t* txt, DWORD style, int x, int y, int w,
                 int h) {
        HWND c = ::CreateWindowExW(0, cls, txt, WS_CHILD | WS_VISIBLE | style, x, y, w, h, host,
                                   (HMENU)(INT_PTR)id, inst, nullptr);
        if (c && font_) ::SendMessageW(c, WM_SETFONT, (WPARAM)font_, TRUE);
        return c;
    };

    // 标签列宽按实测字体算：硬编码过 92px，在高 DPI 下「字体大小」被裁掉了半截
    int label_w = px(96);
    {
        HDC ref = ::GetDC(host);
        HGDIOBJ old = ::SelectObject(ref, font_);
        const wchar_t* widest[] = {L"水印文本", L"字体大小", L"不透明度", L"旋转角度",
                                   L"水平间距", L"垂直间距", L"文字颜色"};
        for (const wchar_t* t : widest) {
            SIZE sz{};
            if (::GetTextExtentPoint32W(ref, t, (int)wcslen(t), &sz) && sz.cx + px(4) > label_w)
                label_w = sz.cx + px(4);
        }
        ::SelectObject(ref, old);
        ::ReleaseDC(host, ref);
    }
    auto text_w = [&](const wchar_t* t) {
        HDC ref = ::GetDC(host);
        HGDIOBJ old = ::SelectObject(ref, font_);
        SIZE sz{};
        ::GetTextExtentPoint32W(ref, t, (int)wcslen(t), &sz);
        ::SelectObject(ref, old);
        ::ReleaseDC(host, ref);
        return sz.cx;
    };

    const int col2 = px(kMarginX) + label_w;
    const int right = px(kClientW) - px(kMarginX);  // 内容右边界
    const int step = px(kRowH);
    const int eh = px(kEditH);
    int y = px(14);

    // 1. 水印文本（占满剩余宽度）
    S(0, L"STATIC", L"水印文本", SS_LEFT, px(kMarginX), y + px(5), label_w, px(18));
    S(IDC_TEXT, L"EDIT", L"", ES_AUTOHSCROLL | WS_BORDER, col2, y, right - col2, eh);
    y += step;

    // 7. 字体名（下拉可输入）+ 2. 字体大小
    S(0, L"STATIC", L"字体名", SS_LEFT, px(kMarginX), y + px(5), label_w, px(18));
    int combo_w = px(230);
    S(IDC_FONTFAMILY, L"COMBOBOX", L"", CBS_DROPDOWN | WS_VSCROLL | CBS_AUTOHSCROLL, col2, y,
      combo_w, eh + px(160));
    int size_label_x = col2 + combo_w + px(16);
    int size_label_w = px(72);
    S(0, L"STATIC", L"字体大小", SS_LEFT, size_label_x, y + px(5), size_label_w, px(18));
    S(IDC_FONTSIZE, L"EDIT", L"30", ES_NUMBER | ES_RIGHT | WS_BORDER, size_label_x + size_label_w,
      y, right - (size_label_x + size_label_w), eh);
    y += step;

    // 8. 粗体 / 斜体 + 10. 实时预览（默认开）
    int cb_w = text_w(L"粗体") + px(30);
    S(IDC_BOLD, L"BUTTON", L"粗体", BS_AUTOCHECKBOX, col2, y, cb_w, eh);
    S(IDC_ITALIC, L"BUTTON", L"斜体", BS_AUTOCHECKBOX, col2 + cb_w + px(10), y, cb_w, eh);
    S(IDC_LIVEPREVIEW, L"BUTTON", L"实时预览", BS_AUTOCHECKBOX, col2 + 2 * (cb_w + px(10)), y,
      text_w(L"实时预览") + px(30), eh);
    y += step;

    // 3. 不透明度
    S(0, L"STATIC", L"不透明度", SS_LEFT, px(kMarginX), y + px(5), label_w, px(18));
    int slider_w = right - col2 - px(70);
    S(IDC_OPACITY, TRACKBAR_CLASSW, L"", TBS_HORZ | TBS_NOTICKS, col2, y, slider_w, px(24));
    S(IDC_OPACITY_LABEL, L"STATIC", L"15%", SS_LEFT, col2 + slider_w + px(8), y + px(5), px(62),
      px(18));
    y += step;

    // 4. 旋转角度
    S(0, L"STATIC", L"旋转角度", SS_LEFT, px(kMarginX), y + px(5), label_w, px(18));
    S(IDC_ANGLE, TRACKBAR_CLASSW, L"", TBS_HORZ | TBS_NOTICKS, col2, y, slider_w, px(24));
    S(IDC_ANGLE_LABEL, L"STATIC", L"-30", SS_LEFT, col2 + slider_w + px(8), y + px(5), px(62),
      px(18));
    y += step;

    // 5. 水平间距 / 垂直间距 / 行距：三个数值框均分
    {
        int num_w = px(64);
        S(0, L"STATIC", L"水平间距", SS_LEFT, px(kMarginX), y + px(5), label_w, px(18));
        S(IDC_GAPX, L"EDIT", L"150", ES_NUMBER | ES_RIGHT | WS_BORDER, col2, y, num_w, eh);
        int l2 = col2 + num_w + px(14);
        S(0, L"STATIC", L"垂直间距", SS_LEFT, l2, y + px(5), label_w, px(18));
        S(IDC_GAPY, L"EDIT", L"120", ES_NUMBER | ES_RIGHT | WS_BORDER, l2 + label_w, y, num_w, eh);
        int l3 = l2 + label_w + num_w + px(14);
        S(0, L"STATIC", L"行距", SS_LEFT, l3, y + px(5), px(34), px(18));
        S(IDC_LINESPACING, L"EDIT", L"1.20", ES_RIGHT | WS_BORDER, l3 + px(34), y, num_w, eh);
    }
    y += step;

    // 6. 文字颜色
    S(0, L"STATIC", L"文字颜色", SS_LEFT, px(kMarginX), y + px(5), label_w, px(18));
    S(IDC_COLOR_PREVIEW, L"STATIC", L"", SS_LEFT | SS_SUNKEN, col2, y + px(3), px(40), px(18));
    S(IDC_COLOR, L"BUTTON", L"选择颜色…", BS_PUSHBUTTON, col2 + px(50), y,
      text_w(L"选择颜色…") + px(24), eh);
    y += step;

    // 9. 启用模板变量 + 时间格式
    {
        int tw = text_w(L"启用模板变量") + px(30);
        S(IDC_TEMPLATE, L"BUTTON", L"启用模板变量", BS_AUTOCHECKBOX, col2, y, tw, eh);
        S(IDC_TIMEFMT, L"EDIT", L"%Y-%m-%d %H:%M", ES_AUTOHSCROLL | WS_BORDER, col2 + tw + px(10),
          y, right - (col2 + tw + px(10)), eh);
    }
    y += step;

    // 11. 全部显示器 + 12. 行错位 + 鼠标穿透（穿透关掉是给人调试点击的）
    {
        int w1 = text_w(L"全部显示器") + px(30);
        int w2 = text_w(L"行错位") + px(30);
        int w3 = text_w(L"鼠标穿透") + px(30);
        S(IDC_ALLMON, L"BUTTON", L"全部显示器", BS_AUTOCHECKBOX, col2, y, w1, eh);
        S(IDC_PHASE, L"BUTTON", L"行错位", BS_AUTOCHECKBOX, col2 + w1 + px(10), y, w2, eh);
        S(IDC_CLICKTHROUGH, L"BUTTON", L"鼠标穿透", BS_AUTOCHECKBOX, col2 + w1 + w2 + px(20), y, w3,
          eh);
    }
    y += step + px(10);

    // 13. 四个按钮：等分剩余宽度
    {
        const wchar_t* names[] = {L"应用", L"隐藏水印", L"保存配置", L"重置默认"};
        int gap = px(8);
        int bw = (right - px(kMarginX) - 3 * gap) / 4;
        for (int i = 0; i < 4; ++i) {
            // 按钮文字比等分宽度还宽就把按钮撑开，宁可整体超一点也别截字
            int need = text_w(names[i]) + px(24);
            if (need > bw) bw = need;
        }
        int x = px(kMarginX);
        S(IDC_APPLY, L"BUTTON", names[0], BS_PUSHBUTTON, x, y, bw, px(28));
        S(IDC_HIDE, L"BUTTON", names[1], BS_PUSHBUTTON, x + bw + gap, y, bw, px(28));
        S(IDC_SAVE, L"BUTTON", names[2], BS_PUSHBUTTON, x + 2 * (bw + gap), y, bw, px(28));
        S(IDC_RESET, L"BUTTON", names[3], BS_PUSHBUTTON, x + 3 * (bw + gap), y, bw, px(28));
        y += px(28) + px(12);
    }

    // 14. 快捷键提示 + 状态行
    S(IDC_HINT, L"STATIC", L"快捷键：Ctrl+Alt+W 开关水印 · Ctrl+Alt+S 设置 · Ctrl+Alt+Q 退出",
      SS_LEFT, px(kMarginX), y, right - px(kMarginX), px(18));
    y += px(22);
    S(IDC_STATUS, L"STATIC", L"", SS_LEFT, px(kMarginX), y, right - px(kMarginX), px(18));

    LoadFontList();
}

void Settings::LoadFontList() {
    HWND combo = ::GetDlgItem(hwnd_, IDC_FONTFAMILY);
    if (!combo) return;
    std::vector<std::wstring> names;
    g_fontNames = &names;
    LOGFONTW lf{};
    lf.lfCharSet = DEFAULT_CHARSET;
    HDC dc = ::GetDC(hwnd_);
    ::EnumFontFamiliesExW(dc, &lf, CollectFontProc, 0, 0);
    ::ReleaseDC(hwnd_, dc);
    g_fontNames = nullptr;
    std::sort(names.begin(), names.end());
    names.erase(std::unique(names.begin(), names.end()), names.end());
    for (const auto& n : names) ::SendMessageW(combo, CB_ADDSTRING, 0, (LPARAM)n.c_str());
}

int Settings::ReadInt(int id, int def, int lo, int hi) const {
    std::wstring s = ReadText(id);
    int v = s.empty() ? def : (int)wcstol(s.c_str(), nullptr, 10);
    if (v < lo) v = lo;
    if (v > hi) v = hi;
    return v;
}

double Settings::ReadDouble(int id, double def, double lo, double hi) const {
    std::wstring s = ReadText(id);
    double v = s.empty() ? def : wcstod(s.c_str(), nullptr);
    if (!(v == v)) v = def;  // NaN 防护
    if (v < lo) v = lo;
    if (v > hi) v = hi;
    return v;
}

bool Settings::ReadCheck(int id) const {
    return ::SendDlgItemMessageW(hwnd_, id, BM_GETCHECK, 0, 0) == BST_CHECKED;
}

std::wstring Settings::ReadText(int id) const {
    HWND c = ::GetDlgItem(hwnd_, id);
    if (!c) return std::wstring();
    int n = ::GetWindowTextLengthW(c);
    std::wstring s((size_t)n + 1, L'\0');
    ::GetWindowTextW(c, &s[0], n + 1);
    s.resize((size_t)n);
    return TrimW(s);
}

void Settings::SetIntText(int id, int v) {
    ::SetDlgItemTextW(hwnd_, id, std::to_wstring(v).c_str());
}

void Settings::Collect(Config& out) const {
    out = cfg_;
    out.text = ReadText(IDC_TEXT);
    out.font_size = ReadInt(IDC_FONTSIZE, cfg_.font_size, 8, 400);
    out.gap_x = ReadInt(IDC_GAPX, cfg_.gap_x, 0, 2000);
    out.gap_y = ReadInt(IDC_GAPY, cfg_.gap_y, 0, 2000);
    out.line_spacing = ReadDouble(IDC_LINESPACING, cfg_.line_spacing, 0.5, 3.0);
    out.bold = ReadCheck(IDC_BOLD);
    out.italic = ReadCheck(IDC_ITALIC);
    out.templ = ReadCheck(IDC_TEMPLATE);
    out.time_format = ReadText(IDC_TIMEFMT);
    if (out.time_format.empty()) out.time_format = L"%Y-%m-%d %H:%M";
    out.all_monitors = ReadCheck(IDC_ALLMON);
    out.phase_offset = ReadCheck(IDC_PHASE);
    out.click_through = ReadCheck(IDC_CLICKTHROUGH);
    // 滑块给的是整数百分比，落回配置时要还原成 0.01..1 的浮点
    out.opacity = (double)::SendDlgItemMessageW(hwnd_, IDC_OPACITY, TBM_GETPOS, 0, 0) / 100.0;
    out.angle = (int)::SendDlgItemMessageW(hwnd_, IDC_ANGLE, TBM_GETPOS, 0, 0);
    std::wstring fam = ReadText(IDC_FONTFAMILY);
    if (!fam.empty()) out.font_family = fam;
    ClampConfig(out);
}

void Settings::UpdateColorPreview() {
    // 色块就是个 STATIC，颜色靠 WM_CTLCOLORSTATIC 返回的刷子；这里只重造刷子并让它重画
    int rgb = ParseColorHex(cfg_.color, 0x808080);
    COLORREF want = RGB((rgb >> 16) & 0xFF, (rgb >> 8) & 0xFF, rgb & 0xFF);
    if (brush_ && swatch_ == want) return;
    if (brush_) ::DeleteObject(brush_);
    swatch_ = want;
    brush_ = ::CreateSolidBrush(want);
    HWND box = ::GetDlgItem(hwnd_, IDC_COLOR_PREVIEW);
    if (box) {
        ::InvalidateRect(box, nullptr, TRUE);
        ::UpdateWindow(box);
    }
}

void Settings::ApplyDpiFont(UINT dpi) {
    if (font_) ::DeleteObject(font_);
    // 用系统 UI 字体而不是 DEFAULT_GUI_FONT，后者在新系统上又老又小
    NONCLIENTMETRICSW ncm{};
    ncm.cbSize = sizeof(ncm);
    LOGFONTW lf{};
    if (::SystemParametersInfoW(SPI_GETNONCLIENTMETRICS, sizeof(ncm), &ncm, 0))
        lf = ncm.lfMessageFont;
    else
        wcscpy(lf.lfFaceName, L"Microsoft YaHei");
    lf.lfHeight = -MulDiv(9, (int)dpi, 72);
    font_ = ::CreateFontIndirectW(&lf);
}

void Settings::SyncFrom(const Config& cfg) {
    if (!hwnd_) return;
    suppress_ = true;  // 程序自己填控件时不要触发回调，否则会自我循环
    cfg_ = cfg;
    ::SetDlgItemTextW(hwnd_, IDC_TEXT, cfg.text.c_str());
    SetIntText(IDC_FONTSIZE, cfg.font_size);
    SetIntText(IDC_GAPX, cfg.gap_x);
    SetIntText(IDC_GAPY, cfg.gap_y);
    ::SetDlgItemTextW(hwnd_, IDC_TIMEFMT, cfg.time_format.c_str());
    ::SendDlgItemMessageW(hwnd_, IDC_BOLD, BM_SETCHECK, cfg.bold ? BST_CHECKED : BST_UNCHECKED, 0);
    ::SendDlgItemMessageW(hwnd_, IDC_ITALIC, BM_SETCHECK, cfg.italic ? BST_CHECKED : BST_UNCHECKED,
                          0);
    ::SendDlgItemMessageW(hwnd_, IDC_TEMPLATE, BM_SETCHECK,
                          cfg.templ ? BST_CHECKED : BST_UNCHECKED, 0);
    ::SendDlgItemMessageW(hwnd_, IDC_ALLMON, BM_SETCHECK,
                          cfg.all_monitors ? BST_CHECKED : BST_UNCHECKED, 0);
    ::SendDlgItemMessageW(hwnd_, IDC_PHASE, BM_SETCHECK,
                          cfg.phase_offset ? BST_CHECKED : BST_UNCHECKED, 0);
    ::SendDlgItemMessageW(hwnd_, IDC_CLICKTHROUGH, BM_SETCHECK,
                          cfg.click_through ? BST_CHECKED : BST_UNCHECKED, 0);
    ::SendDlgItemMessageW(hwnd_, IDC_LIVEPREVIEW, BM_SETCHECK, BST_CHECKED, 0);
    int pct = (int)std::lround(cfg.opacity * 100.0);
    ::SendDlgItemMessageW(hwnd_, IDC_OPACITY, TBM_SETPOS, TRUE, pct);
    ::SendDlgItemMessageW(hwnd_, IDC_ANGLE, TBM_SETPOS, TRUE, cfg.angle);
    ::SetDlgItemTextW(hwnd_, IDC_OPACITY_LABEL, Fmt(L"%d%%", pct).c_str());
    ::SetDlgItemTextW(hwnd_, IDC_ANGLE_LABEL, std::to_wstring(cfg.angle).c_str());
    wchar_t sp[32];
    swprintf(sp, 32, L"%.2f", cfg.line_spacing);
    ::SetDlgItemTextW(hwnd_, IDC_LINESPACING, sp);
    HWND combo = ::GetDlgItem(hwnd_, IDC_FONTFAMILY);
    if (combo) ::SetWindowTextW(combo, cfg.font_family.c_str());
    UpdateColorPreview();
    suppress_ = false;
    dirty_ = false;
}

void Settings::Show(const Config& cfg) {
    if (!EnsureWindow()) return;
    UINT dpi = DpiForWindowSafe(hwnd_);
    if (dpi != dpi_ || !font_) {
        dpi_ = dpi;
        ApplyDpiFont(dpi_);
    }
    SyncFrom(cfg);
    ::ShowWindow(hwnd_, SW_SHOWNORMAL);
    ::SetForegroundWindow(hwnd_);
    ::SetTimer(hwnd_, IDC_TIMER_TICK, 16, nullptr);  // 改控件后靠它把新参数推给渲染
}

void Settings::Hide() {
    if (!hwnd_) return;
    ::KillTimer(hwnd_, IDC_TIMER_TICK);
    ::ShowWindow(hwnd_, SW_HIDE);
}

bool Settings::IsVisible() const { return hwnd_ && ::IsWindowVisible(hwnd_) != FALSE; }

void Settings::Toggle(const Config& cfg) {
    if (IsVisible())
        Hide();
    else
        Show(cfg);
}

void Settings::Shutdown() {
    // 显式收摊：面板窗口、字体、色块刷子都在这里放掉，别指望 static App 的析构顺序
    if (hwnd_) {
        ::KillTimer(hwnd_, IDC_TIMER_TICK);
        if (g_fontNames) g_fontNames = nullptr;  // 回调正在跑的极端情况，清掉指针更安全
        ::DestroyWindow(hwnd_);
        hwnd_ = nullptr;
    }
    if (font_) {
        ::DeleteObject(font_);
        font_ = nullptr;
    }
    if (brush_) {
        ::DeleteObject(brush_);
        brush_ = nullptr;
    }
    swatch_ = CLR_INVALID;
}

void Settings::SetHintText(const std::wstring& text) {
    if (hwnd_) ::SetDlgItemTextW(hwnd_, IDC_HINT, text.c_str());
}

void Settings::NotifyConfigSaved() {
    if (hwnd_) ::SetDlgItemTextW(hwnd_, IDC_STATUS, L"配置已保存");
}

LRESULT Settings::PanelProc(HWND h, UINT m, WPARAM w, LPARAM l) {
    switch (m) {
        case WM_CREATE: {
            // 先记下句柄：BuildControls 里创建子控件要用它当父窗口
            hwnd_ = h;
            dpi_ = DpiForWindowSafe(h);
            ApplyDpiFont(dpi_);
            BuildControls(h);
            // 滑块范围一次性设好；TRACKBAR 需要 main 里先 InitCommonControlsEx
            HWND op = ::GetDlgItem(h, IDC_OPACITY);
            HWND an = ::GetDlgItem(h, IDC_ANGLE);
            ::SendMessageW(op, TBM_SETRANGE, TRUE, MAKELPARAM(1, 100));
            ::SendMessageW(an, TBM_SETRANGE, TRUE, MAKELPARAM(-90, 90));
            ::SendMessageW(op, TBM_SETPAGESIZE, 0, 5);
            ::SendMessageW(an, TBM_SETPAGESIZE, 0, 5);
            return 0;
        }
        case WM_CTLCOLORSTATIC: {
            // 颜色预览的色块靠这里上色
            HWND c = (HWND)l;
            if (c && ::GetDlgCtrlID(c) == IDC_COLOR_PREVIEW && brush_) {
                ::SetBkColor((HDC)w, swatch_);
                return (LRESULT)brush_;
            }
            break;
        }
        case WM_SETFOCUS:
            ::SetFocus(::GetDlgItem(h, IDC_TEXT));
            return 0;
        case WM_TIMER: {
            if (w != IDC_TIMER_TICK) break;
            if (suppress_) return 0;
            Config now;
            Collect(now);
            if (!SameRenderConfig(now, cfg_) && ReadCheck(IDC_LIVEPREVIEW)) {
                cfg_ = now;
                dirty_ = true;
                ::SetDlgItemTextW(h, IDC_STATUS, L"已实时预览（未保存）");
                if (on_apply) on_apply(cfg_);
            } else {
                cfg_ = now;  // 没开实时预览也要记下来，点「应用」时直接用
            }
            return 0;
        }
        case WM_HSCROLL: {
            if (suppress_) return 0;
            HWND src = (HWND)l;
            int id = src ? ::GetDlgCtrlID(src) : 0;
            if (id == IDC_OPACITY) {
                int pct = (int)::SendMessageW(src, TBM_GETPOS, 0, 0);
                ::SetDlgItemTextW(h, IDC_OPACITY_LABEL, Fmt(L"%d%%", pct).c_str());
            } else if (id == IDC_ANGLE) {
                int a = (int)::SendMessageW(src, TBM_GETPOS, 0, 0);
                ::SetDlgItemTextW(h, IDC_ANGLE_LABEL, std::to_wstring(a).c_str());
            }
            // 拖动过程中就刷新，不等松手
            Config now;
            Collect(now);
            cfg_ = now;
            if (ReadCheck(IDC_LIVEPREVIEW) && on_apply) {
                dirty_ = true;
                ::SetDlgItemTextW(h, IDC_STATUS, L"已实时预览（未保存）");
                on_apply(cfg_);
            }
            return 0;
        }
        case WM_COMMAND: {
            const int id = LOWORD(w);
            const int code = HIWORD(w);
            if (id == IDC_COLOR && code == BN_CLICKED) {
                static COLORREF custom[16] = {0};
                int rgb = ParseColorHex(cfg_.color, 0x808080);
                CHOOSECOLORW cc{};
                cc.lStructSize = sizeof(cc);
                cc.hwndOwner = h;
                cc.lpCustColors = custom;
                // COLORREF 是 0x00BBGGRR，和配置里的 #RRGGBB 顺序正好相反
                cc.rgbResult = RGB((rgb >> 16) & 0xFF, (rgb >> 8) & 0xFF, rgb & 0xFF);
                cc.Flags = CC_FULLOPEN | CC_RGBINIT;
                if (::ChooseColorW(&cc)) {
                    wchar_t buf[16];
                    swprintf(buf, 16, L"#%02X%02X%02X", GetRValue(cc.rgbResult),
                             GetGValue(cc.rgbResult), GetBValue(cc.rgbResult));
                    cfg_.color = buf;
                    UpdateColorPreview();
                    if (on_apply) {
                        dirty_ = true;
                        on_apply(cfg_);
                    }
                }
                return 0;
            }
            if (id == IDC_APPLY && code == BN_CLICKED) {
                Collect(cfg_);
                dirty_ = true;
                ::SetDlgItemTextW(h, IDC_STATUS, L"已应用（未保存）");
                if (on_apply) on_apply(cfg_);
                return 0;
            }
            if (id == IDC_HIDE && code == BN_CLICKED) {
                if (on_toggle) on_toggle();
                return 0;
            }
            if (id == IDC_SAVE && code == BN_CLICKED) {
                Collect(cfg_);
                if (on_save) on_save(cfg_);
                dirty_ = false;
                ::SetDlgItemTextW(h, IDC_STATUS, L"配置已保存到 config.json");
                return 0;
            }
            if (id == IDC_RESET && code == BN_CLICKED) {
                if (MessageBoxW(h, L"恢复所有参数为默认值？", kAppName,
                                MB_ICONQUESTION | MB_YESNO) == IDYES) {
                    Config def;
                    SyncFrom(def);
                    cfg_ = def;
                    dirty_ = true;
                    if (on_apply) on_apply(cfg_);
                }
                return 0;
            }
            if (id == IDC_TEXT && code == EN_CHANGE) {
                if (!suppress_) ::SetDlgItemTextW(h, IDC_STATUS, L"未保存");
                return 0;
            }
            return 0;
        }
        case WM_CLOSE:
            // 关面板 ≠ 退出程序：只藏起来，水印继续挂着（§4）
            Hide();
            return 0;
        case WM_DESTROY:
            ::KillTimer(h, IDC_TIMER_TICK);
            hwnd_ = nullptr;
            return 0;
        default: break;
    }
    return ::DefWindowProcW(h, m, w, l);
}

}  // namespace sw
