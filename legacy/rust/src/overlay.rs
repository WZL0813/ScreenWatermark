// 每块显示器一个逐像素透明的分层窗口。
// 关键点：内容全部由 UpdateLayeredWindow 提供，WM_PAINT 什么都不用画。

use crate::config::Config;
use crate::ffi::*;
use crate::render::{self, RenderedBitmap, TilePlan};
use crate::util::{self, Monitor};
use std::ffi::c_void;

pub const OVERLAY_CLASS: &str = "ScreenWatermarkOverlay";

/// 一个水印窗 + 它当前的位图。
pub struct Overlay {
    pub hwnd: HWND,
    /// 该窗口对应的显示器句柄。当前只作记录，留给以后按显示器 DPI 重建窗口用。
    #[allow(dead_code)]
    pub hmon: *mut c_void,
    pub rect: RECT,
    pub dpi: u32,
    /// 已经贴上去的位图；替换前必须 dispose，否则每改一次配置漏一张图。
    pub bmp: Option<RenderedBitmap>,
    pub plan: Option<TilePlan>,
    pub visible: bool,
}

impl Overlay {
    pub fn width(&self) -> i32 {
        self.rect.width()
    }
    pub fn height(&self) -> i32 {
        self.rect.height()
    }
}

/// 每次重绘都被调用的日志出口。
pub struct OverlaySet {
    pub items: Vec<Overlay>,
    hinst: HINSTANCE,
}

impl OverlaySet {
    pub fn new(hinst: HINSTANCE) -> OverlaySet {
        OverlaySet {
            items: Vec::new(),
            hinst,
        }
    }

    fn log(&self, msg: &str) {
        crate::log::line(msg);
    }

    /// 重建窗口集合：显示器数量或矩形变了才需要走这条路径。
    /// 只改配置不要调它 —— 规格要求"不要销毁重建窗口，改参数后重画"。
    pub fn rebuild(&mut self, monitors: &[Monitor], cfg: &Config) {
        self.destroy_all();
        for m in monitors {
            let hwnd = unsafe {
                CreateWindowExW(
                    overlay_ex_style(cfg),
                    crate::util::to_wide(OVERLAY_CLASS).as_ptr(),
                    crate::util::to_wide("ScreenWatermark").as_ptr(),
                    WS_POPUP,
                    m.rect.left,
                    m.rect.top,
                    m.rect.width(),
                    m.rect.height(),
                    std::ptr::null_mut(),
                    std::ptr::null_mut(),
                    self.hinst,
                    std::ptr::null_mut(),
                )
            };
            if hwnd.is_null() {
                self.log(&format!(
                    "创建水印窗口失败（显示器 {}x{}），错误码 {}",
                    m.rect.width(),
                    m.rect.height(),
                    util::last_error()
                ));
                continue;
            }
            // 顶层窗口才配 TOPMOST；用 SetWindowPos 比在 CreateWindowEx 里写更直观。
            // 刻意不带 SWP_SHOWWINDOW：窗口先建好但保持隐藏，由 render_all()
            // 在真正贴上内容那一刻显示。这样"配置里 enabled=false"的启动
            // 不会留下一个可见但全透明的窗口，状态只有一个来源。
            unsafe {
                SetWindowPos(hwnd, HWND_TOPMOST, m.rect.left, m.rect.top,
                    m.rect.width(), m.rect.height(), SWP_NOACTIVATE);
            }
            self.items.push(Overlay {
                hwnd,
                hmon: m.hmon,
                rect: m.rect,
                dpi: m.dpi,
                bmp: None,
                plan: None,
                visible: false,
            });
        }
        self.log(&format!("已创建 {} 个水印窗口", self.items.len()));
    }

    /// 显示器布局是否和当前窗口集合一致。用矩形比对，显示器拔插/换分辨率都能发现。
    pub fn matches(&self, monitors: &[Monitor]) -> bool {
        if self.items.len() != monitors.len() {
            return false;
        }
        for (a, b) in self.items.iter().zip(monitors.iter()) {
            if a.rect.left != b.rect.left
                || a.rect.top != b.rect.top
                || a.rect.width() != b.rect.width()
                || a.rect.height() != b.rect.height()
            {
                return false;
            }
        }
        true
    }

    /// 按配置重画所有屏。cfg.enabled 为假时只是隐藏，窗口留着。
    pub fn render_all(&mut self, cfg: &Config) {
        if !cfg.enabled {
            self.hide_all();
            return;
        }
        let dpi = cfg_dpi();
        // 先把日志攒起来，循环里需要 &mut items，不能同时借用 self。
        let mut notes: Vec<String> = Vec::new();
        for i in 0..self.items.len() {
            let (w, h) = (self.items[i].width(), self.items[i].height());
            match render::render_to(w, h, cfg, dpi) {
                Ok((bmp, plan)) => {
                    let cov = render::coverage(&bmp);
                    notes.push(format!(
                        "{}（内容占比 {:.2}%）",
                        render::describe(w, h, &plan, 0.0),
                        cov * 100.0
                    ));
                    let new_dpi = unsafe { GetDpiForWindow(self.items[i].hwnd) };
                    let overlay = &mut self.items[i];
                    overlay.dpi = if new_dpi >= 48 { new_dpi } else { dpi };
                    overlay.plan = Some(plan);
                    Self::apply(overlay, bmp);
                    // 从"已隐藏"切回显示时，必须显式 Show 一次：
                    // hide_all 用的 SW_HIDE 会清掉 WS_VISIBLE，而 UpdateLayeredWindow
                    // 只更新分层内容、不会把窗口重新显示出来。少了这一步，
                    // "隐藏一次再打开"之后水印就再也回不来了。
                    if !overlay.visible {
                        unsafe {
                            ShowWindow(overlay.hwnd, SW_SHOWNOACTIVATE);
                        }
                    }
                    overlay.visible = true;
                }
                Err(e) => {
                    notes.push(format!("渲染失败：{}", e));
                }
            }
        }
        for n in notes {
            self.log(&n);
        }
    }

    /// 把位图贴到窗口上。先贴新的再换掉旧的，避免出现空窗闪一下。
    fn apply(o: &mut Overlay, bmp: RenderedBitmap) {
        unsafe {
            let screen_dc = GetDC(std::ptr::null_mut());
            if screen_dc.is_null() {
                bmp.dispose();
                return;
            }
            let pt_dst = POINT {
                x: o.rect.left,
                y: o.rect.top,
            };
            let size = SIZE {
                cx: bmp.width,
                cy: bmp.height,
            };
            let pt_src = POINT { x: 0, y: 0 };
            let blend = BLENDFUNCTION {
                BlendOp: AC_SRC_OVER,
                BlendFlags: 0,
                SourceConstantAlpha: 255,
                AlphaFormat: AC_SRC_ALPHA,
            };
            let ok = UpdateLayeredWindow(
                o.hwnd,
                screen_dc,
                &pt_dst,
                &size,
                bmp.mem_dc,
                &pt_src,
                0,
                &blend,
                ULW_ALPHA,
            );
            ReleaseDC(std::ptr::null_mut(), screen_dc);
            if ok == 0 {
                bmp.dispose();
                return;
            }
            // 换新的，旧的这时候才回收。
            if let Some(old) = o.bmp.take() {
                old.dispose();
            }
            o.bmp = Some(bmp);
        }
    }

    pub fn hide_all(&mut self) {
        for o in self.items.iter_mut() {
            if o.visible {
                unsafe {
                    ShowWindow(o.hwnd, SW_HIDE);
                }
                o.visible = false;
            }
        }
    }

    #[allow(dead_code)]
    pub fn show_all(&mut self) {
        for o in self.items.iter_mut() {
            if !o.visible {
                unsafe {
                    ShowWindow(o.hwnd, SW_SHOWNOACTIVATE);
                }
                o.visible = true;
            }
        }
    }

    /// 每 3 秒重新顶到最前面，防止被别的全屏程序压下去。
    pub fn raise_all(&self) {
        for o in self.items.iter() {
            unsafe {
                SetWindowPos(
                    o.hwnd,
                    HWND_TOPMOST,
                    0,
                    0,
                    0,
                    0,
                    SWP_FLAGS_TOP,
                );
            }
        }
    }

    /// 点击穿透开关变了要改扩展样式；改样式后必须重贴一次位图，
    /// 否则 WS_EX_LAYERED 被 Remove 掉的那一瞬间内容会消失。
    pub fn update_click_through(&self, cfg: &Config) {
        for o in self.items.iter() {
            unsafe {
                let cur = GetWindowLongPtrW(o.hwnd, GWL_EXSTYLE) as usize;
                let want = if cfg.click_through {
                    cur | (WS_EX_TRANSPARENT as usize)
                } else {
                    cur & !(WS_EX_TRANSPARENT as usize)
                };
                if want != cur {
                    SetWindowLongPtrW(o.hwnd, GWL_EXSTYLE, want as isize);
                }
            }
        }
    }

    #[allow(dead_code)]
    pub fn any_window(&self) -> HWND {
        self.items
            .first()
            .map(|o| o.hwnd)
            .unwrap_or(std::ptr::null_mut())
    }

    pub fn destroy_all(&mut self) {
        for o in self.items.drain(..) {
            if let Some(b) = o.bmp {
                b.dispose();
            }
            unsafe {
                if !o.hwnd.is_null() {
                    DestroyWindow(o.hwnd);
                }
            }
        }
    }
}

/// 按配置算出扩展样式。规格要求的四件套 + TOPMOST；调试模式下拿掉
/// WS_EX_TRANSPARENT 和 WS_EX_NOACTIVATE，水印才能真的挡住鼠标。
pub fn overlay_ex_style(cfg: &Config) -> DWORD {
    let mut ex = WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_TOPMOST;
    if cfg.click_through {
        ex |= WS_EX_TRANSPARENT | WS_EX_NOACTIVATE;
    }
    ex
}

fn cfg_dpi() -> u32 {
    // 进程已声明 PerMonitorV2，主屏 DPI 用系统 DPI 兜底，单屏渲染时够用。
    unsafe {
        let h = GetDC(std::ptr::null_mut());
        if h.is_null() {
            return 96;
        }
        let dpi = GetDeviceCaps(h, LOGPIXELSX);
        ReleaseDC(std::ptr::null_mut(), h);
        if dpi >= 48 {
            dpi as u32
        } else {
            96
        }
    }
}

pub const LOGPIXELSX: i32 = 88;

/// overlay 窗口的窗口过程：分层窗口没有自绘需求，
/// 只需要处理"顶置定时器"和把 WM_ERASEBKGND 吃掉避免闪。
pub unsafe extern "system" fn overlay_wndproc(
    hwnd: HWND,
    msg: UINT,
    wparam: WPARAM,
    lparam: LPARAM,
) -> LRESULT {
    match msg {
        WM_ERASEBKGND => 1, // 背景由 UpdateLayeredWindow 全权负责
        WM_NCHITTEST => {
            // 兜底：即使样式没生效也别让水印抢走鼠标（穿透模式下）。
            HTTRANSPARENT
        }
        WM_TIMER => {
            if wparam == TIMER_TOPMOST {
                SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_FLAGS_TOP);
                return 0;
            }
            DefWindowProcW(hwnd, msg, wparam, lparam)
        }
        WM_DISPLAYCHANGE | WM_DPICHANGED => {
            // 屏幕变了交给主循环的定时器处理，这里不自己重建窗口。
            DefWindowProcW(hwnd, msg, wparam, lparam)
        }
        WM_PAINT => {
            // 什么都不画，但要验证一下窗口还在，避免 DefWindowProc 做多余的事。
            let mut ps = std::mem::zeroed::<PAINTSTRUCT>();
            let hdc = BeginPaint(hwnd, &mut ps);
            EndPaint(hwnd, &ps);
            let _ = hdc;
            0
        }
        _ => DefWindowProcW(hwnd, msg, wparam, lparam),
    }
}

// c_void 在这个模块里只用于 MONITOR 句柄，显式引用一下避免 clippy 未用告警。
const _: Option<*mut c_void> = None;

/// 窗口类注册。重复注册返回 0，调用方按"是否已存在"处理。
pub fn register_overlay_class(hinst: HINSTANCE) -> bool {
    unsafe {
        let mut wc: WNDCLASSEXW = std::mem::zeroed();
        wc.cbSize = core::mem::size_of::<WNDCLASSEXW>() as UINT;
        wc.style = CS_HREDRAW | CS_VREDRAW;
        wc.lpfnWndProc = Some(overlay_wndproc);
        wc.hInstance = hinst;
        wc.hCursor = LoadCursorW(std::ptr::null_mut(), IDC_ARROW as *const u16);
        // 背景刷子留空：分层窗口自己管像素，给了刷子反而会闪。
        wc.hbrBackground = std::ptr::null_mut();
        // 类名先落到局部变量，临时 Vec 会在语句末尾释放。
        let cls_name = util::to_wide(OVERLAY_CLASS);
        wc.lpszClassName = cls_name.as_ptr();
        let atom = RegisterClassExW(&wc);
        if atom == 0 {
            // 1410 = ERROR_CLASS_ALREADY_EXISTS，属于正常情况（比如重建窗口集合）。
            return util::last_error() == ERROR_CLASS_ALREADY_EXISTS;
        }
        true
    }
}

