// 原生设置面板：EDIT / BUTTON / TRACKBAR / COMBOBOX / STATIC。
// 打开面板只是 ShowWindow，关闭是 Hide，程序不退出（规格 §4）。
// 实时预览靠 EN_CHANGE / WM_HSCROLL / BN_CLICKED 直接回调主循环。

use crate::config::{self, Config};
use crate::ffi::*;
use crate::util::{self, to_wide};
use std::ffi::c_void;

pub const PANEL_CLASS: &str = "ScreenWatermarkSettingsPanel";
pub const PANEL_TITLE: &str = "ScreenWatermark 设置";

// 控件 ID。数值集中在这里，WndProc 里只做匹配。
pub const ID_TEXT: usize = 2001;
pub const ID_FONT_SIZE: usize = 2002;
pub const ID_OPACITY: usize = 2003;
pub const ID_ANGLE: usize = 2004;
pub const ID_GAP_X: usize = 2005;
pub const ID_GAP_Y: usize = 2006;
pub const ID_COLOR: usize = 2007;
pub const ID_COLOR_VALUE: usize = 2008;
pub const ID_FONT_FAMILY: usize = 2009;
pub const ID_BOLD: usize = 2010;
pub const ID_ITALIC: usize = 2011;
pub const ID_TEMPLATE: usize = 2012;
pub const ID_TIME_FORMAT: usize = 2013;
pub const ID_LIVE_PREVIEW: usize = 2014;
pub const ID_ALL_MONITORS: usize = 2015;
pub const ID_PHASE_OFFSET: usize = 2016;
pub const ID_APPLY: usize = 2017;
pub const ID_HIDE: usize = 2018;
pub const ID_SAVE: usize = 2019;
pub const ID_RESET: usize = 2020;
pub const ID_CLOSE: usize = 2021;
pub const ID_CLICK_THROUGH: usize = 2022;
pub const ID_REFRESH_SEC: usize = 2023;
pub const ID_LINE_SPACING: usize = 2030;
pub const ID_HINT: usize = 2024;
pub const ID_OPACITY_LABEL: usize = 2025;
pub const ID_ANGLE_LABEL: usize = 2026;
pub const ID_VAR_HINT: usize = 2029;

/// 角度滑块内部用 0..180 表示 -90..90（msctls_trackbar32 不支持负最小值）。
const ANGLE_OFFSET: i32 = 90;

/// 面板需要外部配合的事情：读当前配置、应用新配置、重置、切水印可见性。
pub trait PanelHost {
    fn current_config(&self) -> Config;
    /// 应用配置。persist=false 表示只重画不落盘（实时预览 / 应用按钮）。
    fn apply_config(&mut self, cfg: Config, persist: bool);
    /// 重置默认值并立即生效（是否写盘由实现决定，这里统一不写）。
    fn reset_defaults(&mut self) -> Config;
    fn watermark_visible(&self) -> bool;
    fn toggle_watermark_visible(&mut self);
    /// 面板底部提示行。实际生效的热键组合由实现方算好，面板只管显示 ——
    /// 首选组合可能被别的软件占用而降级，硬编码会骗人。
    fn hotkey_hint(&self) -> String;
}

pub struct Panel {
    pub hwnd: HWND,
    pub visible: bool,
}

impl Panel {
    pub fn new() -> Panel {
        Panel {
            hwnd: std::ptr::null_mut(),
            visible: false,
        }
    }

    pub fn is_open(&self) -> bool {
        self.visible && unsafe { IsWindow(self.hwnd) != 0 }
    }
}

/// 面板内的控件句柄表。
#[derive(Default)]
struct Controls {
    text: HWND,
    font_size: HWND,
    opacity: HWND,
    opacity_label: HWND,
    angle: HWND,
    angle_label: HWND,
    gap_x: HWND,
    gap_y: HWND,
    line_spacing: HWND,
    refresh_sec: HWND,
    color_btn: HWND,
    color_value: HWND,
    font_family: HWND,
    bold: HWND,
    italic: HWND,
    template: HWND,
    time_format: HWND,
    live_preview: HWND,
    all_monitors: HWND,
    phase_offset: HWND,
    click_through: HWND,
    apply: HWND,
    hide: HWND,
    save: HWND,
    reset: HWND,
    close: HWND,
    hint: HWND,
}

/// 挂在 GWLP_USERDATA 上的面板运行态。
struct PanelState {
    host: Box<dyn PanelHost>,
    c: Controls,
    /// 颜色用 COLORREF 存（GDI 的 0x00BBGGRR），显示时转 #RRGGBB。
    color: u32,
    /// 填充控件期间为真，用来屏蔽 EN_CHANGE 造成的重入刷新。
    populating: bool,
    /// 用户是否手动动过"实时预览"勾选框。没动过时默认勾上（规格要求默认开）。
    live_preview_touched: bool,
}

const PANEL_BG: (u8, u8, u8) = (246, 246, 248);

fn rgb_ref(c: (u8, u8, u8)) -> DWORD {
    (c.0 as DWORD) | ((c.1 as DWORD) << 8) | ((c.2 as DWORD) << 16)
}

pub fn register_panel_class(hinst: HINSTANCE) -> bool {
    unsafe {
        let mut wc: WNDCLASSEXW = std::mem::zeroed();
        wc.cbSize = core::mem::size_of::<WNDCLASSEXW>() as UINT;
        wc.style = CS_HREDRAW | CS_VREDRAW;
        wc.lpfnWndProc = Some(panel_wndproc);
        wc.hInstance = hinst;
        wc.hCursor = LoadCursorW(std::ptr::null_mut(), IDC_ARROW as *const u16);
        // 背景刷子挂到类上，面板重绘时不用自己擦背景。
        wc.hbrBackground = CreateSolidBrush(rgb_ref(PANEL_BG)) as HBRUSH;
        // 类名要先绑到局部变量，临时 Vec 在语句末尾就释放了。
        let cls_name = to_wide(PANEL_CLASS);
        wc.lpszClassName = cls_name.as_ptr();
        let atom = RegisterClassExW(&wc);
        atom != 0 || util::last_error() == ERROR_CLASS_ALREADY_EXISTS
    }
}

/// 打开（或首次创建）面板。
pub fn open_panel(panel: &mut Panel, hinst: HINSTANCE, host: Box<dyn PanelHost>) {
    unsafe {
        if !panel.hwnd.is_null() && IsWindow(panel.hwnd) != 0 {
            // 已经建过就复用，先按最新配置刷新控件再显示。
            populate(panel.hwnd);
            ShowWindow(panel.hwnd, SW_SHOWNORMAL);
            SetForegroundWindow(panel.hwnd);
            panel.visible = true;
            return;
        }
        let state = Box::new(PanelState {
            host,
            c: Controls::default(),
            color: rgb_ref((128, 128, 128)),
            populating: false,
            live_preview_touched: false,
        });
        let raw = Box::into_raw(state);
        let title = to_wide(PANEL_TITLE);
        let cls = to_wide(PANEL_CLASS);
        // 不要 WS_MAXIMIZEBOX / WS_THICKFRAME：面板尺寸固定，拉伸没意义还会露白。
        let style = WS_OVERLAPPEDWINDOW & !WS_MAXIMIZEBOX & !WS_THICKFRAME;
        // 客户区按版面需要的尺寸算，再用 AdjustWindowRectExForDpi 加上边框。
        // 直接把 570x560 当窗口尺寸交给 CreateWindowExW 是不对的：那 570 里
        // 含边框和标题栏，真正留给控件的只剩 554 宽，右侧控件会被裁掉。
        let panel_dpi = GetDpiForSystem();
        let panel_dpi = if panel_dpi >= 48 { panel_dpi } else { 96 };
        let (cx, cy) = window_size_for_client(
            scaled(CLIENT_W, panel_dpi),
            scaled(CLIENT_H, panel_dpi),
        );
        // 居中到工作区，别让面板一半在屏幕外。
        let (px, py) = centered_origin(cx, cy);
        let hwnd = CreateWindowExW(
            WS_EX_DLGMODALFRAME | WS_EX_APPWINDOW,
            cls.as_ptr(),
            title.as_ptr(),
            style,
            px,
            py,
            cx,
            cy,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            hinst,
            raw as *mut c_void,
        );
        if hwnd.is_null() {
            // 创建失败会把 lpCreateParams 的所有权还给我们，必须收回来。
            drop(Box::from_raw(raw));
            util::info_box(&format!(
                "设置面板创建失败，错误码 {}。快捷键和托盘仍然可用。",
                util::last_error()
            ));
            return;
        }
        SetWindowLongPtrW(hwnd, GWLP_USERDATA, raw as isize);
        // 有些系统会把初始尺寸夹到工作区内，这里按算好的尺寸再钉一次。
        SetWindowPos(hwnd, std::ptr::null_mut(), px, py, cx, cy, SWP_NOZORDER | SWP_NOACTIVATE);
        populate(hwnd);
        ShowWindow(hwnd, SW_SHOWNORMAL);
        SetForegroundWindow(hwnd);
        panel.hwnd = hwnd;
        panel.visible = true;
    }
}

/// 面板客户区尺寸。控件坐标就是按这个版面写死的，改这里要同步改 build_controls。
/// 宽度取 574 是为了容下最右侧的"关闭"按钮和快捷键提示（最远到 x≈556）。
/// 高度取 480 是按最下面那行提示的底边（y≈420+40）再加一点余量算的。
const CLIENT_W: i32 = 500;
const CLIENT_H: i32 = 400;

/// 客户区尺寸 -> 含边框的窗口尺寸。优先用 DPI 感知的版本，
/// 拿不到就退到 96 DPI 的 AdjustWindowRect（在 100% 缩放下结果一样）。
fn window_size_for_client(cw: i32, ch: i32) -> (i32, i32) {
    let style = WS_OVERLAPPEDWINDOW & !WS_MAXIMIZEBOX & !WS_THICKFRAME;
    unsafe {
        let mut r = RECT {
            left: 0,
            top: 0,
            right: cw,
            bottom: ch,
        };
        let dpi = GetDpiForSystem();
        let dpi = if dpi >= 48 { dpi } else { 96 };
        if AdjustWindowRectExForDpi(&mut r, style, 0, WS_EX_DLGMODALFRAME | WS_EX_APPWINDOW, dpi) != 0
        {
            return (r.width(), r.height());
        }
        let mut r2 = RECT {
            left: 0,
            top: 0,
            right: cw,
            bottom: ch,
        };
        if AdjustWindowRectEx(
            &mut r2,
            style,
            0,
            WS_EX_DLGMODALFRAME | WS_EX_APPWINDOW,
        ) != 0
        {
            return (r2.width(), r2.height());
        }
        // 都失败就按经验值加边框厚度，宁可大一点也不要裁掉控件。
        (cw + 32, ch + 60)
    }
}

/// 把窗口摆到主显示器工作区中间。
fn centered_origin(w: i32, h: i32) -> (i32, i32) {
    unsafe {
        let sw = GetSystemMetrics(0);
        let sh = GetSystemMetrics(1);
        if sw <= 0 || sh <= 0 {
            return (80, 80);
        }
        let x = ((sw - w) / 2).max(0);
        let y = ((sh - h) / 3).max(0); // 略偏上，键盘弹出物不挡
        (x, y)
    }
}

#[link(name = "user32")]
extern "system" {
    fn AdjustWindowRectEx(
        lpRect: *mut RECT,
        dwStyle: DWORD,
        bMenu: BOOL,
        dwExStyle: DWORD,
    ) -> BOOL;
    fn AdjustWindowRectExForDpi(
        lpRect: *mut RECT,
        dwStyle: DWORD,
        bMenu: BOOL,
        dwExStyle: DWORD,
        dpi: UINT,
    ) -> BOOL;
    fn GetDpiForSystem() -> UINT;
}

pub fn hide_panel(panel: &mut Panel) {
    unsafe {
        if !panel.hwnd.is_null() && IsWindow(panel.hwnd) != 0 {
            ShowWindow(panel.hwnd, SW_HIDE);
        }
    }
    panel.visible = false;
}

pub fn toggle_panel(panel: &mut Panel, hinst: HINSTANCE, host: Box<dyn PanelHost>) {
    if panel.is_open() {
        hide_panel(panel);
    } else {
        open_panel(panel, hinst, host);
    }
}

/// 把配置填进控件。populating 期间屏蔽实时预览回调，否则会自己触发自己。
fn populate(hwnd: HWND) {
    unsafe {
        let raw = GetWindowLongPtrW(hwnd, GWLP_USERDATA) as *mut PanelState;
        if raw.is_null() {
            return;
        }
        let st = &mut *raw;
        st.populating = true;
        let cfg = st.host.current_config();

        // 提示行按当前实际生效的热键重写：降级过就显示降级后的组合。
        let hint = st.host.hotkey_hint();
        set_text(st.c.hint, &hint);

        set_text(st.c.text, &cfg.text);
        set_text(st.c.font_size, &cfg.font_size.to_string());
        set_text(st.c.gap_x, &cfg.gap_x.to_string());
        set_text(st.c.gap_y, &cfg.gap_y.to_string());
        set_text(st.c.line_spacing, &cfg.line_spacing.to_string());
        set_text(st.c.time_format, &cfg.time_format);
        set_text(st.c.refresh_sec, &cfg.refresh_seconds.to_string());

        SendMessageW(st.c.opacity, TBM_SETPOS, 1, (cfg.opacity * 100.0).round() as isize);
        SendMessageW(
            st.c.angle,
            TBM_SETPOS,
            1,
            (cfg.angle + ANGLE_OFFSET) as isize,
        );
        set_text(
            st.c.opacity_label,
            &format!("{}%", (cfg.opacity * 100.0).round() as i32),
        );
        set_text(st.c.angle_label, &format!("{}°", cfg.angle));

        st.color = config::colorref(&cfg.color);
        update_color_swatch(st);

        // 面板里显示真正能用的字体名：配置写了本机没有的字体时落回系统 UI 字体，
        // 免得用户对着一个不存在的名字发懵。
        let resolved = util::resolve_font_family(&cfg.font_family);
        fill_font_combo(st, &resolved);

        set_check(st.c.bold, cfg.bold);
        set_check(st.c.italic, cfg.italic);
        set_check(st.c.template, cfg.template);
        set_check(st.c.all_monitors, cfg.all_monitors);
        set_check(st.c.phase_offset, cfg.phase_offset);
        set_check(st.c.click_through, cfg.click_through);
        // 实时预览规格要求默认开；只在第一次（还没被用户改过）时置上。
        if !st.live_preview_touched {
            set_check(st.c.live_preview, true);
        }
        // 水印被隐藏时按钮文字要反映"再点一下会怎样"。
        set_text(
            st.c.hide,
            if st.host.watermark_visible() {
                "隐藏水印"
            } else {
                "显示水印"
            },
        );

        st.populating = false;
    }
}

unsafe fn set_text(h: HWND, s: &str) {
    if h.is_null() {
        return;
    }
    let w = to_wide(s);
    SetWindowTextW(h, w.as_ptr());
}

unsafe fn get_text(h: HWND) -> String {
    if h.is_null() {
        return String::new();
    }
    // 先问长度再分配：水印文本允许很长，固定缓冲会被截断。
    let n = GetWindowTextLengthW(h).max(0) as usize;
    let cap = n + 8;
    let mut buf = vec![0u16; cap];
    let got = GetWindowTextW(h, buf.as_mut_ptr(), cap as i32);
    if got <= 0 {
        String::new()
    } else {
        util::from_wide(&buf[..got as usize])
    }
}

unsafe fn get_int(h: HWND, fallback: i32) -> i32 {
    let s = get_text(h);
    match s.trim().parse::<f64>() {
        Ok(v) if v.is_finite() => v.round() as i32,
        // 用户输入非法（空串、中文）时不炸，用原值顶上。
        _ => fallback,
    }
}

unsafe fn get_float(h: HWND, fallback: f64) -> f64 {
    let s = get_text(h);
    match s.trim().parse::<f64>() {
        Ok(v) if v.is_finite() => v,
        // 输入非法（空串、中文）时不炸，用原值顶上。
        _ => fallback,
    }
}

unsafe fn is_checked(h: HWND) -> bool {
    !h.is_null() && SendMessageW(h, BM_GETCHECK, 0, 0) == BST_CHECKED as LRESULT
}

unsafe fn set_check(h: HWND, v: bool) {
    if h.is_null() {
        return;
    }
    SendMessageW(h, BM_SETCHECK, if v { BST_CHECKED } else { BST_UNCHECKED }, 0);
}

/// 颜色按钮文案 = 当前色值，用户一眼能看到。
unsafe fn update_color_swatch(st: &PanelState) {
    let hex = config::colorref_to_hex(st.color);
    set_text(st.c.color_btn, &format!("选择… {}", hex));
    set_text(st.c.color_value, &hex);
}

unsafe fn fill_font_combo(st: &mut PanelState, current: &str) {
    let combo = st.c.font_family;
    if combo.is_null() {
        return;
    }
    SendMessageW(combo, CB_RESETCONTENT, 0, 0);
    for f in util::FONT_CANDIDATES.iter() {
        let w = to_wide(f);
        SendMessageW(combo, CB_ADDSTRING, 0, w.as_ptr() as LPARAM);
    }
    // 配置里的字体名如果不在候选表里也加进去，免得下拉框把它吃掉。
    let w = to_wide(current);
    let found = SendMessageW(combo, CB_FINDSTRINGEXACT, usize::MAX, w.as_ptr() as LPARAM);
    if found < 0 {
        SendMessageW(combo, CB_ADDSTRING, 0, w.as_ptr() as LPARAM);
    }
    set_text(combo, current);
    let idx = SendMessageW(combo, CB_FINDSTRINGEXACT, usize::MAX, w.as_ptr() as LPARAM);
    if idx >= 0 {
        SendMessageW(combo, CB_SETCURSEL, idx as WPARAM, 0);
    }
}

pub const CB_RESETCONTENT: UINT = 0x014B;

/// 从控件读出完整配置。以 host 的当前配置作底稿，保留面板管不到的字段。
fn read_form(hwnd: HWND) -> Option<Config> {
    unsafe {
        let raw = GetWindowLongPtrW(hwnd, GWLP_USERDATA) as *mut PanelState;
        if raw.is_null() {
            return None;
        }
        let st = &mut *raw;
        let mut cfg = st.host.current_config();
        cfg.text = get_text(st.c.text);
        cfg.font_size = get_int(st.c.font_size, cfg.font_size);
        cfg.gap_x = get_int(st.c.gap_x, cfg.gap_x);
        cfg.gap_y = get_int(st.c.gap_y, cfg.gap_y);
        cfg.line_spacing = get_float(st.c.line_spacing, cfg.line_spacing);
        cfg.time_format = get_text(st.c.time_format);
        if cfg.time_format.trim().is_empty() {
            cfg.time_format = "%Y-%m-%d %H:%M".to_string();
        }
        cfg.refresh_seconds = get_int(st.c.refresh_sec, cfg.refresh_seconds);
        let op = SendMessageW(st.c.opacity, TBM_GETPOS, 0, 0);
        cfg.opacity = ((op as f64) / 100.0).clamp(0.01, 1.0);
        let ang = SendMessageW(st.c.angle, TBM_GETPOS, 0, 0) as i32;
        cfg.angle = ang - ANGLE_OFFSET;
        cfg.color = config::colorref_to_hex(st.color);
        let fam = get_text(st.c.font_family);
        if !fam.trim().is_empty() {
            cfg.font_family = fam.trim().to_string();
        }
        cfg.bold = is_checked(st.c.bold);
        cfg.italic = is_checked(st.c.italic);
        cfg.template = is_checked(st.c.template);
        cfg.all_monitors = is_checked(st.c.all_monitors);
        cfg.phase_offset = is_checked(st.c.phase_offset);
        cfg.click_through = is_checked(st.c.click_through);
        Some(cfg.normalized())
    }
}

/// 实时预览 / 控件联动：更新数字标签，勾了实时预览就立刻重画水印。
unsafe fn live_preview(hwnd: HWND) {
    let raw = GetWindowLongPtrW(hwnd, GWLP_USERDATA) as *mut PanelState;
    if raw.is_null() {
        return;
    }
    let st = &mut *raw;
    if st.populating {
        return;
    }
    let op = SendMessageW(st.c.opacity, TBM_GETPOS, 0, 0);
    set_text(st.c.opacity_label, &format!("{}%", op));
    let ang = SendMessageW(st.c.angle, TBM_GETPOS, 0, 0) as i32 - ANGLE_OFFSET;
    set_text(st.c.angle_label, &format!("{}°", ang));

    if !is_checked(st.c.live_preview) {
        return;
    }
    if let Some(cfg) = read_form(hwnd) {
        // persist=false：预览不写 config.json，免得用户乱拖滑块就把配置改了。
        st.host.apply_config(cfg, false);
    }
}

/// 用系统颜色选择对话框改颜色。ComDlg32 是系统自带，不需要额外依赖。
unsafe fn choose_color(hwnd: HWND) -> Option<u32> {
    let raw = GetWindowLongPtrW(hwnd, GWLP_USERDATA) as *mut PanelState;
    if raw.is_null() {
        return None;
    }
    let mut custom = [0x00FF_FFFFu32; 16];
    let mut cc: CHOOSECOLORW = std::mem::zeroed();
    cc.lStructSize = core::mem::size_of::<CHOOSECOLORW>() as DWORD;
    cc.hwndOwner = hwnd;
    cc.rgbResult = (*raw).color;
    cc.lpCustColors = custom.as_mut_ptr();
    cc.Flags = CC_FULLOPEN | CC_RGBINIT;
    if ChooseColorW(&mut cc) != 0 {
        Some(cc.rgbResult)
    } else {
        None
    }
}

#[repr(C)]
#[allow(non_snake_case)] // 字段名照抄 Win32 的 CHOOSECOLORW
struct CHOOSECOLORW {
    lStructSize: DWORD,
    hwndOwner: HWND,
    hInstance: HINSTANCE,
    rgbResult: DWORD,
    lpCustColors: *mut DWORD,
    Flags: DWORD,
    lCustData: LPARAM,
    lpfnHook: *mut c_void,
    lpTemplateName: *const u16,
}

pub const CC_RGBINIT: DWORD = 0x0000_0001;
pub const CC_FULLOPEN: DWORD = 0x0000_0002;

#[link(name = "comdlg32")]
extern "system" {
    fn ChooseColorW(p: *mut CHOOSECOLORW) -> BOOL;
}

/// 控件创建小帮手，减少重复的 to_wide 样板。
struct Builder {
    hwnd: HWND,
    hinst: HINSTANCE,
    font: HFONT,
}

impl Builder {
    unsafe fn make(
        &self,
        class: &str,
        text: &str,
        style: DWORD,
        ex_style: DWORD,
        id: usize,
        x: i32,
        y: i32,
        w: i32,
        h: i32,
    ) -> HWND {
        let cls = to_wide(class);
        let txt = to_wide(text);
        let child = CreateWindowExW(
            ex_style,
            cls.as_ptr(),
            txt.as_ptr(),
            WS_CHILD | WS_VISIBLE | style,
            x,
            y,
            w,
            h,
            self.hwnd,
            id as HMENU,
            self.hinst,
            std::ptr::null_mut(),
        );
        if !child.is_null() && !self.font.is_null() {
            SendMessageW(child, WM_SETFONT, self.font as WPARAM, 1);
        }
        child
    }
}

pub const CBS_DROPDOWN: DWORD = 0x0003;
pub const CBS_AUTOHSCROLL: DWORD = 0x0040;

#[repr(C)]
#[allow(non_snake_case)] // 字段名照抄 Win32 的 CREATESTRUCTW
struct CREATESTRUCTW {
    lpCreateParams: *mut c_void,
    hInstance: HINSTANCE,
    hMenu: HMENU,
    hwndParent: HWND,
    cy: i32,
    cx: i32,
    y: i32,
    x: i32,
    style: LONG,
    lpszName: *const u16,
    lpszClass: *const u16,
    dwExStyle: DWORD,
}

unsafe extern "system" fn panel_wndproc(
    hwnd: HWND,
    msg: UINT,
    wparam: WPARAM,
    lparam: LPARAM,
) -> LRESULT {
    match msg {
        WM_CREATE => {
            let cs = lparam as *const CREATESTRUCTW;
            let raw = (*cs).lpCreateParams as *mut PanelState;
            SetWindowLongPtrW(hwnd, GWLP_USERDATA, raw as isize);
            let hinst = GetModuleHandleW(std::ptr::null());
            match build_controls(hwnd, hinst) {
                Ok(c) => {
                    (*raw).c = c;
                    0
                }
                Err(e) => {
                    util::info_box(&format!("设置面板控件创建失败：{}", e));
                    // 返回 -1 让 CreateWindowEx 失败，避免出现半个空窗口。
                    -1
                }
            }
        }
        WM_COMMAND => {
            let id = (wparam & 0xFFFF) as usize;
            let code = ((wparam >> 16) & 0xFFFF) as u16;
            let raw = GetWindowLongPtrW(hwnd, GWLP_USERDATA) as *mut PanelState;
            if raw.is_null() {
                return 0;
            }
            let st = &mut *raw;
            match id {
                ID_TEXT | ID_FONT_SIZE | ID_GAP_X | ID_GAP_Y | ID_TIME_FORMAT
                | ID_REFRESH_SEC => {
                    if code == EN_CHANGE {
                        live_preview(hwnd);
                    }
                }
                ID_FONT_FAMILY => {
                    // 可编辑下拉框：选择(CBN_SELCHANGE)和手输(EN_CHANGE)都算改动。
                    if code == CBN_SELCHANGE || code == EN_CHANGE {
                        live_preview(hwnd);
                    }
                }
                ID_BOLD | ID_ITALIC | ID_TEMPLATE | ID_ALL_MONITORS | ID_PHASE_OFFSET
                | ID_CLICK_THROUGH => {
                    if code == BN_CLICKED {
                        live_preview(hwnd);
                    }
                }
                ID_LIVE_PREVIEW => {
                    if code == BN_CLICKED {
                        st.live_preview_touched = true;
                        if is_checked(st.c.live_preview) {
                            // 刚打开实时预览，立刻按当前控件值重画一次。
                            if let Some(cfg) = read_form(hwnd) {
                                st.host.apply_config(cfg, false);
                            }
                        }
                    }
                }
                ID_COLOR => {
                    if code == BN_CLICKED {
                        if let Some(c) = choose_color(hwnd) {
                            st.color = c;
                            update_color_swatch(st);
                            live_preview(hwnd);
                        }
                    }
                }
                ID_APPLY | ID_SAVE => {
                    if code == BN_CLICKED {
                        if let Some(cfg) = read_form(hwnd) {
                            // 应用和保存都改内存 + 重画；保存多一步落盘。
                            let persist = id == ID_SAVE;
                            st.host.apply_config(cfg, persist);
                            populate(hwnd);
                        }
                    }
                }
                ID_HIDE => {
                    if code == BN_CLICKED {
                        st.host.toggle_watermark_visible();
                        live_preview(hwnd);
                        populate(hwnd);
                    }
                }
                ID_RESET => {
                    if code == BN_CLICKED {
                        // 重置只改内存和控件，是否落盘由用户再点保存决定。
                        let d = st.host.reset_defaults();
                        st.populating = true;
                        st.live_preview_touched = true;
                        st.populating = false;
                        populate(hwnd);
                        if let Some(cfg) = read_form(hwnd) {
                            st.host.apply_config(cfg, false);
                        }
                        let _ = d;
                    }
                }
                ID_CLOSE => {
                    if code == BN_CLICKED {
                        ShowWindow(hwnd, SW_HIDE);
                    }
                }
                _ => {}
            }
            0
        }
        WM_HSCROLL => {
            live_preview(hwnd);
            0
        }
        WM_CLOSE => {
            // 关面板不退程序（规格 §4）：只隐藏，水印继续挂着。
            ShowWindow(hwnd, SW_HIDE);
            0
        }
        WM_SYSCOMMAND => {
            // 屏蔽 Alt+空格菜单，防止面板被键盘移出屏幕外找不回来。
            let cmd = wparam & 0xFFF0;
            if cmd == SC_KEYMENU {
                return 0;
            }
            DefWindowProcW(hwnd, msg, wparam, lparam)
        }
        WM_CTLCOLORSTATIC | WM_CTLCOLORBTN => {
            // 静态文字透明底，才不会被系统刷成白底。
            let hdc = wparam as HDC;
            SetBkMode(hdc, 1);
            SetTextColor(hdc, 0x0020_2020);
            GetSysColorBrush(COLOR_BTNFACE) as LRESULT
        }
        WM_CTLCOLOREDIT | WM_CTLCOLORLISTBOX => {
            let hdc = wparam as HDC;
            SetBkColor(hdc, 0x00FF_FFFF);
            GetSysColorBrush(COLOR_WINDOW) as LRESULT
        }
        WM_DESTROY => {
            let raw = GetWindowLongPtrW(hwnd, GWLP_USERDATA) as *mut PanelState;
            if !raw.is_null() {
                SetWindowLongPtrW(hwnd, GWLP_USERDATA, 0);
                drop(Box::from_raw(raw));
            }
            0
        }
        _ => DefWindowProcW(hwnd, msg, wparam, lparam),
    }
}

/// 把 96 DPI 下的逻辑尺寸换算成当前 DPI 的物理像素。
/// 面板的控件坐标全部按 96 DPI 写，缩放交给这一个函数 ——
/// 175% 屏幕上直接用逻辑像素会让文字和输入框挤在一起。
fn scaled(logical: i32, dpi: u32) -> i32 {
    let d = if dpi >= 48 { dpi } else { 96 };
    ((logical as f64) * (d as f64) / 96.0).round() as i32
}

/// 按 §5 的 14 项排布控件。坐标按 96 DPI 的逻辑像素写死：
/// 原生控件没有布局器，常量表比一堆相对偏移好读，配合 lh() 缩放也不会错位。
unsafe fn build_controls(hwnd: HWND, hinst: HINSTANCE) -> Result<Controls, String> {
    let dpi = GetDpiForWindow(hwnd);
    let dpi = if dpi >= 48 { dpi } else { 96 };

    // 控件字体自己按 DPI 造：GetStockObject(DEFAULT_GUI_FONT) 在 per-monitor
    // DPI 下不跟着缩放，175% 屏幕上 9pt 只有 12 物理像素高，TRACKBAR 还会
    // 把自身高度夹到字体高度，滑轨细成一条线看不清。
    // 9pt @96DPI = 12px，按 DPI 等比放大。
    let font_px = scaled(12, dpi).max(12);
    let face = to_wide("Microsoft YaHei");
    let ui_font = CreateFontW(
        -font_px,
        0,
        0,
        0,
        FW_NORMAL as i32,
        0,
        0,
        0,
        DEFAULT_CHARSET,
        OUT_DEFAULT_PRECIS,
        CLIP_DEFAULT_PRECIS,
        CLEARTYPE_QUALITY,
        0,
        face.as_ptr(),
    );
    let ui_font = if ui_font.is_null() {
        GetStockObject(DEFAULT_GUI_FONT) as HFONT
    } else {
        ui_font
    };

    let b = Builder {
        hwnd,
        hinst,
        font: ui_font,
    };
    let lh = |v: i32| -> i32 { scaled(v, dpi) };
    let mut c = Controls::default();

    // 版式全部按 96 DPI 的逻辑像素写，最后经 lh() 换算成当前 DPI 的物理像素。
    // 左列标签宽 100、控件起始 x=132、整行宽 460，这几条决定了面板客户区宽度。
    let lx = lh(10);
    let cx = lh(132);
    let mut y = lh(8);
    let row = lh(32); // 一行占的高度（含控件本身和间距）

    let rowh = lh(24); // 常规控件高度
    let labh = lh(20); // 标签高度

    let label = |text: &str, x: i32, y: i32, w: i32| -> HWND {
        b.make("STATIC", text, SS_LEFT, 0, 0, x, y + lh(4), w, labh)
    };

    // 1. 水印文本
    label("水印文本", lx, y, lh(100));
    c.text = b.make(
        "EDIT",
        "",
        ES_LEFT | ES_AUTOHSCROLL | WS_TABSTOP | WS_BORDER,
        WS_EX_CLIENTEDGE,
        ID_TEXT,
        cx,
        y,
        lh(320),
        rowh,
    );
    y += row;

    // 2. 字体大小 + 7. 字体名
    label("字体大小", lx, y, lh(100));
    c.font_size = b.make(
        "EDIT",
        "30",
        ES_LEFT | ES_NUMBER | WS_TABSTOP | WS_BORDER,
        WS_EX_CLIENTEDGE,
        ID_FONT_SIZE,
        cx,
        y,
        lh(52),
        rowh,
    );
    label("字体名", cx + lh(62), y, lh(48));
    c.font_family = b.make(
        "COMBOBOX",
        "",
        CBS_DROPDOWN | CBS_AUTOHSCROLL | WS_TABSTOP | WS_VSCROLL,
        0,
        ID_FONT_FAMILY,
        cx + lh(112),
        y,
        lh(208),
        // 下拉列表高度要够，否则展开只看得见一两项。
        lh(240),
    );
    y += row;

    // 3. 不透明度（滑块 1..100）
    label("不透明度", lx, y, lh(100));
    c.opacity = b.make(
        "msctls_trackbar32",
        "",
        WS_TABSTOP | TBS_AUTOTICKS,
        0,
        ID_OPACITY,
        cx,
        y,
        lh(230),
        lh(26),
    );
    c.opacity_label = b.make(
        "STATIC",
        "15%",
        SS_LEFT,
        0,
        ID_OPACITY_LABEL,
        cx + lh(240),
        y + lh(4),
        lh(50),
        labh,
    );
    y += row;

    // 4. 旋转角度（滑块 -90..90，内部用 0..180）
    label("旋转角度", lx, y, lh(100));
    c.angle = b.make(
        "msctls_trackbar32",
        "",
        WS_TABSTOP | TBS_AUTOTICKS,
        0,
        ID_ANGLE,
        cx,
        y,
        lh(230),
        lh(26),
    );
    c.angle_label = b.make(
        "STATIC",
        "0°",
        SS_LEFT,
        0,
        ID_ANGLE_LABEL,
        cx + lh(240),
        y + lh(4),
        lh(50),
        labh,
    );
    y += row;

    // 5. 水平/垂直间距 + 自动刷新秒数
    label("水平间距", lx, y, lh(100));
    let edit_w = lh(62);
    c.gap_x = b.make(
        "EDIT",
        "150",
        ES_LEFT | ES_NUMBER | WS_TABSTOP | WS_BORDER,
        WS_EX_CLIENTEDGE,
        ID_GAP_X,
        cx,
        y,
        edit_w,
        rowh,
    );
    let x2 = cx + edit_w + lh(8);
    label("垂直", x2, y, lh(30));
    let x3 = x2 + lh(34);
    c.gap_y = b.make(
        "EDIT",
        "120",
        ES_LEFT | ES_NUMBER | WS_TABSTOP | WS_BORDER,
        WS_EX_CLIENTEDGE,
        ID_GAP_Y,
        x3,
        y,
        edit_w,
        rowh,
    );
    let x4 = x3 + edit_w + lh(8);
    label("行距", x4, y, lh(30));
    let x5 = x4 + lh(34);
    c.line_spacing = b.make(
        "EDIT",
        "1.2",
        ES_LEFT | WS_TABSTOP | WS_BORDER,
        WS_EX_CLIENTEDGE,
        ID_LINE_SPACING,
        x5,
        y,
        edit_w,
        rowh,
    );
    y += row;

    // 间距第二行：刷新秒数独占，免得第一行挤到面板外面
    label("刷新秒", lx, y, lh(100));
    c.refresh_sec = b.make(
        "EDIT",
        "30",
        ES_LEFT | ES_NUMBER | WS_TABSTOP | WS_BORDER,
        WS_EX_CLIENTEDGE,
        ID_REFRESH_SEC,
        cx,
        y,
        edit_w,
        rowh,
    );
    let _ = x5;
    y += row;

    // 6. 文字颜色
    label("文字颜色", lx, y, lh(100));
    c.color_btn = b.make(
        "BUTTON",
        "选择…",
        BS_PUSHBUTTON | WS_TABSTOP,
        0,
        ID_COLOR,
        cx,
        y,
        lh(150),
        lh(26),
    );
    c.color_value = b.make(
        "STATIC",
        "#808080",
        SS_LEFT,
        0,
        ID_COLOR_VALUE,
        cx + lh(158),
        y + lh(5),
        lh(90),
        labh,
    );
    y += row;

    // 8. 粗体 / 斜体，9. 启用模板变量
    let chk_w = lh(64);
    c.bold = b.make(
        "BUTTON",
        "粗体",
        BS_AUTOCHECKBOX | WS_TABSTOP,
        0,
        ID_BOLD,
        lx,
        y,
        chk_w,
        lh(24),
    );
    c.italic = b.make(
        "BUTTON",
        "斜体",
        BS_AUTOCHECKBOX | WS_TABSTOP,
        0,
        ID_ITALIC,
        lx + chk_w + lh(6),
        y,
        chk_w,
        lh(24),
    );
    c.template = b.make(
        "BUTTON",
        "启用模板变量",
        BS_AUTOCHECKBOX | WS_TABSTOP,
        0,
        ID_TEMPLATE,
        lx + 2 * (chk_w + lh(6)),
        y,
        lh(120),
        lh(24),
    );
    y += lh(30);

    // 9b. 时间格式 + 变量提示
    label("时间格式", lx, y, lh(100));
    c.time_format = b.make(
        "EDIT",
        "%Y-%m-%d %H:%M",
        ES_LEFT | ES_AUTOHSCROLL | WS_TABSTOP | WS_BORDER,
        WS_EX_CLIENTEDGE,
        ID_TIME_FORMAT,
        cx,
        y,
        lh(200),
        rowh,
    );
    b.make(
        "STATIC",
        "变量：{time} {date} {user} {host} {ip}",
        SS_LEFT,
        0,
        ID_VAR_HINT,
        cx + lh(208),
        y + lh(4),
        lh(260),
        labh,
    );
    y += row;

    // 10. 实时预览 11. 全部显示器 12. 行错位 + 鼠标穿透（调试用）
    c.live_preview = b.make(
        "BUTTON",
        "实时预览",
        BS_AUTOCHECKBOX | WS_TABSTOP,
        0,
        ID_LIVE_PREVIEW,
        lx,
        y,
        lh(100),
        lh(24),
    );
    c.all_monitors = b.make(
        "BUTTON",
        "全部显示器",
        BS_AUTOCHECKBOX | WS_TABSTOP,
        0,
        ID_ALL_MONITORS,
        lx + lh(104),
        y,
        lh(112),
        lh(24),
    );
    c.phase_offset = b.make(
        "BUTTON",
        "行错位",
        BS_AUTOCHECKBOX | WS_TABSTOP,
        0,
        ID_PHASE_OFFSET,
        lx + lh(220),
        y,
        lh(88),
        lh(24),
    );
    c.click_through = b.make(
        "BUTTON",
        "鼠标穿透",
        BS_AUTOCHECKBOX | WS_TABSTOP,
        0,
        ID_CLICK_THROUGH,
        lx + lh(312),
        y,
        lh(112),
        lh(24),
    );
    y += lh(32);

    // 13. 按钮排
    let bw = lh(86);
    let bgap = lh(6);
    let by = y;
    c.apply = b.make(
        "BUTTON",
        "应用",
        BS_DEFPUSHBUTTON | WS_TABSTOP,
        0,
        ID_APPLY,
        lx,
        by,
        bw,
        lh(30),
    );
    c.hide = b.make(
        "BUTTON",
        "隐藏水印",
        BS_PUSHBUTTON | WS_TABSTOP,
        0,
        ID_HIDE,
        lx + (bw + bgap),
        by,
        bw,
        lh(30),
    );
    c.save = b.make(
        "BUTTON",
        "保存配置",
        BS_PUSHBUTTON | WS_TABSTOP,
        0,
        ID_SAVE,
        lx + 2 * (bw + bgap),
        by,
        bw,
        lh(30),
    );
    c.reset = b.make(
        "BUTTON",
        "重置默认",
        BS_PUSHBUTTON | WS_TABSTOP,
        0,
        ID_RESET,
        lx + 3 * (bw + bgap),
        by,
        bw,
        lh(30),
    );
    c.close = b.make(
        "BUTTON",
        "关闭",
        BS_PUSHBUTTON | WS_TABSTOP,
        0,
        ID_CLOSE,
        lx + 4 * (bw + bgap),
        by,
        bw,
        lh(30),
    );
    y += lh(40);

    // 14. 快捷键提示。文字在 populate() 里按实际注册结果填，
    // 这里只给个占位，免得降级后还显示按不响的组合。
    c.hint = b.make("STATIC", "", SS_LEFT, 0, ID_HINT, lx, y, lh(470), lh(36));

    // 滑块范围在这里设，顺便把刻度定下来。
    SendMessageW(
        c.opacity,
        TBM_SETRANGE,
        1,
        ((1u32 & 0xFFFF) | (100u32 << 16)) as LPARAM,
    );
    SendMessageW(c.opacity, TBM_SETTICFREQ, 10, 0);
    SendMessageW(
        c.angle,
        TBM_SETRANGE,
        1,
        ((0u32 & 0xFFFF) | (180u32 << 16)) as LPARAM,
    );
    SendMessageW(c.angle, TBM_SETTICFREQ, 30, 0);

    let must = [
        c.text,
        c.font_size,
        c.opacity,
        c.angle,
        c.gap_x,
        c.gap_y,
        c.line_spacing,
        c.refresh_sec,
        c.color_btn,
        c.font_family,
        c.bold,
        c.italic,
        c.template,
        c.time_format,
        c.live_preview,
        c.all_monitors,
        c.phase_offset,
        c.click_through,
        c.apply,
        c.hide,
        c.save,
        c.reset,
        c.close,
        c.hint,
    ];
    for (i, h) in must.iter().enumerate() {
        if h.is_null() {
            return Err(format!(
                "第 {} 个控件创建失败（错误码 {}）",
                i + 1,
                util::last_error()
            ));
        }
    }
    Ok(c)
}
// 面板需要的 GDI 帮手
#[link(name = "gdi32")]
extern "system" {
    fn CreateFontW(
        cHeight: i32,
        cWidth: i32,
        cEscapement: i32,
        cOrientation: i32,
        cWeight: i32,
        bItalic: DWORD,
        bUnderline: DWORD,
        bStrikeOut: DWORD,
        iCharSet: DWORD,
        iOutPrecision: DWORD,
        iClipPrecision: DWORD,
        iQuality: DWORD,
        iPitchAndFamily: DWORD,
        pszFaceName: *const u16,
    ) -> HFONT;
    fn SetBkMode(hdc: HDC, mode: i32) -> i32;
    fn SetTextColor(hdc: HDC, color: DWORD) -> DWORD;
    fn SetBkColor(hdc: HDC, color: DWORD) -> DWORD;
    fn GetStockObject(index: i32) -> HGDIOBJ;
}
