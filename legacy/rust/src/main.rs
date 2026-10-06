// 入口：DPI、单实例、GDI+、托盘、快捷键、消息循环、控制器。
// 业务全在 App 里；这里只做"把零件装起来"。

#![windows_subsystem = "windows"]

mod config;
mod dispatch;
mod ffi;
mod log;
mod overlay;
mod render;
mod settings;
mod tray;
mod util;

use config::Config;
use dispatch::{Loop, Signal};
use ffi::*;
use overlay::OverlaySet;
use settings::{Panel, PanelHost};
use std::collections::BTreeMap;
use std::ffi::c_void;
use std::path::PathBuf;

pub const APP_NAME: &str = "ScreenWatermark";
pub const APP_VERSION: &str = env!("CARGO_PKG_VERSION");
/// 单实例互斥体名字。四个实现各用各的名字，免得互相挡住。
const MUTEX_NAME: &str = "Global\\ScreenWatermark_Rust_SingleInstance";

/// 命令行开关。
#[derive(Default, Clone, Copy)]
struct Args {
    show_version: bool,
    show_help: bool,
    show_settings: bool,
    log: bool,
}

fn parse_args() -> (Args, Option<String>) {
    let mut a = Args::default();
    let mut text: Option<String> = None;
    let mut it = std::env::args().skip(1);
    while let Some(arg) = it.next() {
        match arg.as_str() {
            "-v" | "--version" => a.show_version = true,
            "-h" | "--help" => a.show_help = true,
            "--settings" => a.show_settings = true,
            "--log" => a.log = true,
            "--text" => {
                if let Some(t) = it.next() {
                    text = Some(t);
                }
            }
            other => {
                // 不认识就无视，别因为一个多余参数拒绝启动。
                if let Some(v) = other.strip_prefix("--text=") {
                    text = Some(v.to_string());
                }
            }
        }
    }
    (a, text)
}

/// 控制器：所有可变状态都挂在这里，窗口过程只通过信号回调进来。
struct App {
    cfg: Config,
    /// 未知字段：别的实现写进 config.json 的，写回时要带上。
    extras: BTreeMap<String, String>,
    cfg_path: PathBuf,
    overlays: OverlaySet,
    panel: Panel,
    tray: Option<tray::Tray>,
    /// 配置改了但还没重画（节流用）。
    pending_render: bool,
    /// 上一次模板时间的取值，跳变了才重画。
    last_template: String,
    /// 实际生效的全局热键。设置面板提示行和探针都读它，避免各写一份结论。
    hotkeys: dispatch::Hotkeys,
    hinst: HINSTANCE,
    msg_hwnd: HWND,
    quitting: bool,
}

impl App {
    fn new(
        cfg: Config,
        extras: BTreeMap<String, String>,
        cfg_path: PathBuf,
        hinst: HINSTANCE,
    ) -> App {
        App {
            cfg,
            extras,
            cfg_path,
            overlays: OverlaySet::new(hinst),
            panel: Panel::new(),
            tray: None,
            pending_render: false,
            last_template: String::new(),
            hotkeys: dispatch::Hotkeys::default(),
            hinst,
            msg_hwnd: std::ptr::null_mut(),
            quitting: false,
        }
    }

    /// 按当前配置重建/重画水印窗口。显示器布局变了才重建窗口。
    fn refresh_overlays(&mut self, force_rebuild: bool) {
        let mons = util::pick_monitors(self.cfg.all_monitors);
        if force_rebuild || !self.overlays.matches(&mons) {
            self.overlays.rebuild(&mons, &self.cfg);
        }
        self.overlays.update_click_through(&self.cfg);
        let t0 = std::time::Instant::now();
        self.overlays.render_all(&self.cfg);
        let ms = t0.elapsed().as_secs_f64() * 1000.0;
        log::line(&format!(
            "重画完成：{} 个窗口，耗时 {:.1}ms",
            self.overlays.items.len(),
            ms
        ));
        self.pending_render = false;
        self.last_template = util::template_time_value(&self.cfg);
        if let Some(t) = self.tray.as_ref() {
            t.update_tip(self.cfg.enabled);
        }
    }

    /// 配置改了：先按需落盘，再决定是立刻重画还是排队重画。
    fn apply_config(&mut self, new_cfg: Config, persist: bool) {
        let click_changed = new_cfg.click_through != self.cfg.click_through;
        let monitors_changed = new_cfg.all_monitors != self.cfg.all_monitors;
        let enabled_changed = new_cfg.enabled != self.cfg.enabled;
        let had_windows = !self.overlays.items.is_empty();
        self.cfg = new_cfg;
        if persist {
            self.save_config();
        }
        // 需要换扩展样式（穿透）或重建窗口集合时才走重路径。
        if click_changed || monitors_changed || enabled_changed || !had_windows {
            self.refresh_overlays(true);
        } else {
            // 节流：连拖滑块时不要每动一下就全屏重画一次。
            self.pending_render = true;
        }
    }

    fn save_config(&mut self) {
        let path = self.cfg_path.clone();
        if let Err(e) = self.cfg.save(&self.extras, &path) {
            log::line(&format!("保存配置失败：{}", e));
        } else {
            log::line(&format!("配置已保存到 {}", path.display()));
        }
    }

    /// 重新载入磁盘上的配置（托盘菜单用）。
    fn reload_config(&mut self) {
        let (cfg, extras, path) = util::load_or_default();
        self.cfg = cfg;
        self.extras = extras;
        self.cfg_path = path;
        log::line("已重新载入配置");
        self.refresh_overlays(true);
    }

    fn toggle_watermark(&mut self) {
        self.cfg.enabled = !self.cfg.enabled;
        let path = self.cfg_path.clone();
        let _ = self.cfg.save(&self.extras, &path);
        self.refresh_overlays(false);
        log::line(if self.cfg.enabled {
            "水印已显示"
        } else {
            "水印已隐藏"
        });
    }

    fn open_settings(&mut self) {
        // 先拆开借用：self as *mut App 需要 &mut self，不能和 &mut self.panel 挤在一个表达式里。
        let this: *mut App = self;
        let hinst = self.hinst;
        let panel = &mut self.panel;
        settings::open_panel(panel, hinst, Box::new(AppHost { app: this }));
    }

    fn toggle_settings(&mut self) {
        let this: *mut App = self;
        let hinst = self.hinst;
        let panel = &mut self.panel;
        settings::toggle_panel(panel, hinst, Box::new(AppHost { app: this }));
    }

    /// 退出：给消息循环发 WM_QUIT。quit 只能生效一次。
    fn quit(&mut self) {
        if !self.quitting {
            self.quitting = true;
            log::line("收到退出请求");
            unsafe { PostQuitMessage(0) };
        }
    }
}

/// 面板回调的桥。用裸指针是因为 PanelHost 要求 'static，
/// 而 App 里带着窗口句柄之类的整数。窗口过程和主循环在同一线程上交替执行，
/// 不会并发访问，所以这个指针在本程序里是安全的。
struct AppHost {
    app: *mut App,
}

impl AppHost {
    fn app(&mut self) -> &mut App {
        unsafe { &mut *self.app }
    }
}

impl PanelHost for AppHost {
    fn current_config(&self) -> Config {
        unsafe { (*self.app).cfg.clone() }
    }

    fn apply_config(&mut self, cfg: Config, persist: bool) {
        self.app().apply_config(cfg, persist);
    }

    fn reset_defaults(&mut self) -> Config {
        // 重置只改内存和控件，是否落盘留给用户点"保存配置"。
        let app = self.app();
        let d = Config::default();
        app.cfg = d.clone();
        app.pending_render = true;
        d
    }

    fn watermark_visible(&self) -> bool {
        unsafe { (*self.app).cfg.enabled }
    }

    fn toggle_watermark_visible(&mut self) {
        self.app().toggle_watermark();
    }

    /// 面板底部的提示行直接用实际注册结果，不硬编码 ——
    /// Ctrl+Alt+W/Q 在很多机器上已被别的常驻软件占用，会降级到 Ctrl+Alt+Shift。
    fn hotkey_hint(&self) -> String {
        unsafe { (*self.app).hotkeys.hint_line() }
    }
}

// ---------------- 一次性命令模式：--probe / --save-config / --selftest ----------------
//
// 这三种模式都不进消息循环，各自把结果打到 stdout 后返回退出码。
// 它们刻意绕过单实例互斥体：诊断和落盘配置不该因为"另一个实例在跑"被挡住。

fn run_oneshot(args: &Args, text_override: Option<String>, hinst: HINSTANCE) -> i32 {
    let _ = args;
    let gp_token = match render::gdiplus_startup() {
        Ok(t) => t,
        Err(e) => {
            println!("ONESHOT fail GdiplusStartup: {}", e);
            return 2;
        }
    };
    if !overlay::register_overlay_class(hinst) {
        println!("ONESHOT fail RegisterClassExW 错误码 {}", util::last_error());
        render::gdiplus_shutdown(gp_token);
        return 2;
    }

    let (cfg, extras, cfg_path) = util::load_or_default();
    let mut cfg = cfg;
    if let Some(t) = text_override {
        cfg.text = t;
    }
    // 探针要真的把水印画出来，所以这里建 App 并挂上窗口。
    // cfg 交给 App，selftest 需要颜色信息，所以先留一份。
    let color_probe = cfg.clone();
    let app_box = Box::new(App::new(cfg, extras, cfg_path, hinst));
    let app_ptr: *mut App = Box::into_raw(app_box);
    let app = unsafe { &mut *app_ptr };
    app.refresh_overlays(true);

    // 探针模式下真的去注册一次热键（挂在线程上，hwnd 传 NULL），
    // 这样报出来的就是"这台机器此刻的真实占用情况"，而不是猜的。
    // 结束时统一注销，别影响后面正常启动的实例。
    if std::env::args().any(|a| a == "--probe") {
        app.hotkeys = dispatch::register_hotkeys(std::ptr::null_mut());
    }

    let mut code = 0;
    if std::env::args().any(|a| a == "--probe") {
        code = probe_report(app);
        dispatch::unregister_hotkeys(std::ptr::null_mut());
    }
    if std::env::args().any(|a| a == "--save-config") {
        app.save_config();
        println!("SAVECONFIG path={}", app.cfg_path.display());
        match std::fs::read(&app.cfg_path) {
            Ok(bytes) => println!(
                "SAVECONFIG bytes={} has_bom={}",
                bytes.len(),
                bytes.len() >= 3 && bytes[0] == 0xEF && bytes[1] == 0xBB && bytes[2] == 0xBF
            ),
            Err(e) => {
                println!("SAVECONFIG read-back failed: {}", e);
                code = 3;
            }
        }
    }
    if std::env::args().any(|a| a == "--selftest") {
        if let Err(e) = selftest_screenshot(&color_probe) {
            println!("SELFTEST fail {}", e);
            code = 4;
        }
    }
    app.overlays.destroy_all();
    unsafe {
        render::gdiplus_shutdown(gp_token);
        drop(Box::from_raw(app_ptr));
    }
    code
}

/// 报出 overlay 窗口的句柄、尺寸、扩展样式。
/// 用进程内数据而不是 EnumWindows：水印窗口带 WS_EX_TOOLWINDOW，
/// 外部脚本按标题/类名去筛很容易把别的程序的窗口也算进来。
/// 这里直接报自己持有的句柄，再用 GetWindowRect / GetWindowLongPtrW 反查一次。
fn probe_report(app: &App) -> i32 {
    println!("PROBE app={} version={}", APP_NAME, APP_VERSION);
    println!(
        "PROBE config enabled={} all_monitors={} click_through={} text={:?}",
        app.cfg.enabled, app.cfg.all_monitors, app.cfg.click_through, app.cfg.text
    );
    println!("PROBE overlay_count={}", app.overlays.items.len());
    // 热键部分只报"真的注册结果"：
    // 之前这里用 RegisterHotKey 传了 vk=0（等于探一个不存在的组合），
    // 于是永远返回成功，把 Ctrl+Alt+W/Q 已被别的软件占用这件事盖住了。
    // 现在直接读 Hotkeys 的注册返回值 + GetLastError，不再自己猜。
    for b in &app.hotkeys.bindings {
        // 三个值都来自 RegisterHotKey 的返回值和紧随其后的 GetLastError，
        // 没有推测成分。preferred_ok=false + preferred_err=1409 就说明
        // 首选组合被这台机器上的别的程序占了，已降级到 effective 那一个。
        println!(
            "PROBE hotkey {:?} preferred={} preferred_ok={} preferred_err={} effective={}",
            b.action,
            b.preferred_label(),
            !b.fallback && b.ok,
            b.preferred_err,
            if b.ok { b.label() } else { "NONE".to_string() }
        );
    }
    println!("PROBE hotkey hint={}", app.hotkeys.hint_line());
    let mut bad = 0;
    for (i, o) in app.overlays.items.iter().enumerate() {
        let mut wr = RECT::default();
        let ok = unsafe { GetWindowRect(o.hwnd, &mut wr) };
        let ex = unsafe { GetWindowLongPtrW(o.hwnd, GWL_EXSTYLE) } as usize;
        let style = unsafe { GetWindowLongPtrW(o.hwnd, GWL_STYLE) } as usize;
        let alive = unsafe { IsWindow(o.hwnd) } != 0;
        let visible = unsafe { IsWindowVisible(o.hwnd) } != 0;
        println!(
            "PROBE overlay[{}] hwnd=0x{:X} monitor_rect=({},{},{}x{}) window_rect=({},{},{}x{}) GetWindowRect_ok={} cfg_size={}x{} exstyle=0x{:X} style=0x{:X} layered={} transparent={} toolwindow={} noactivate={} topmost={} is_window={} visible={} has_bitmap={}",
            i,
            o.hwnd as usize,
            o.rect.left,
            o.rect.top,
            o.rect.width(),
            o.rect.height(),
            wr.left,
            wr.top,
            wr.width(),
            wr.height(),
            ok,
            o.width(),
            o.height(),
            ex,
            style,
            (ex & WS_EX_LAYERED as usize) != 0,
            (ex & WS_EX_TRANSPARENT as usize) != 0,
            (ex & WS_EX_TOOLWINDOW as usize) != 0,
            (ex & WS_EX_NOACTIVATE as usize) != 0,
            (ex & WS_EX_TOPMOST as usize) != 0,
            alive,
            visible,
            o.bmp.is_some(),
        );
        if let Some(p) = o.plan.as_ref() {
            println!(
                "PROBE overlay[{}] plan cell={}x{} text_w={} line_h={} cells={}{}",
                i,
                p.cell_w,
                p.cell_h,
                p.text_w,
                p.line_h,
                p.cells,
                if p.clamped { " (clamped)" } else { "" }
            );
        }
        // 关键项对不上就记一笔，让脚本能靠退出码判断。
        if !alive || !visible || o.bmp.is_none() {
            bad += 1;
        }
        if (ex & WS_EX_LAYERED as usize) == 0
            || (ex & WS_EX_TOOLWINDOW as usize) == 0
            || (ex & WS_EX_TOPMOST as usize) == 0
        {
            bad += 1;
        }
        if wr.width() != o.width() || wr.height() != o.height() {
            bad += 1;
        }
    }
    println!("PROBE problems={}", bad);
    if bad == 0 {
        0
    } else {
        1
    }
}



/// 全屏 BitBlt 抓一张，数"接近配置颜色且是灰阶"的像素比例。
/// 不依赖任何图像库，直接把结果打到 stdout 并落一张 BMP 供人眼确认。
/// 用虚拟屏幕矩形而不是主屏尺寸：多显示器时主屏尺寸会把副屏的水印漏掉。
fn selftest_screenshot(cfg: &Config) -> Result<(), String> {
    use std::io::Write;
    unsafe {
        // SM_XVIRTUALSCREEN=76, SM_YVIRTUALSCREEN=77,
        // SM_CXVIRTUALSCREEN=78, SM_CYVIRTUALSCREEN=79
        let (mut vx, mut vy) = (GetSystemMetrics(76), GetSystemMetrics(77));
        let (mut w, mut h) = (GetSystemMetrics(78), GetSystemMetrics(79));
        if w <= 0 || h <= 0 {
            vx = 0;
            vy = 0;
            w = GetSystemMetrics(0);
            h = GetSystemMetrics(1);
        }
        if w <= 0 || h <= 0 {
            return Err("拿不到屏幕尺寸".to_string());
        }
        let screen_dc = GetDC(std::ptr::null_mut());
        if screen_dc.is_null() {
            return Err("GetDC(NULL) 失败".to_string());
        }
        let mem_dc = CreateCompatibleDC(screen_dc);
        let hbmp = CreateCompatibleBitmap(screen_dc, w, h);
        if mem_dc.is_null() || hbmp.is_null() {
            ReleaseDC(std::ptr::null_mut(), screen_dc);
            return Err("创建截图位图失败".to_string());
        }
        let old = SelectObject(mem_dc, hbmp as HGDIOBJ);
        if BitBlt(mem_dc, 0, 0, w, h, screen_dc, vx, vy, SRCCOPY) == 0 {
            SelectObject(mem_dc, old);
            DeleteObject(hbmp as HGDIOBJ);
            DeleteDC(mem_dc);
            ReleaseDC(std::ptr::null_mut(), screen_dc);
            return Err("BitBlt 失败".to_string());
        }
        // 用 GetDIBits 拷成 32bpp top-down，免得手动解设备相关位图。
        let mut bmi = BITMAPINFO {
            bmiHeader: BITMAPINFOHEADER {
                biSize: std::mem::size_of::<BITMAPINFOHEADER>() as DWORD,
                biWidth: w,
                biHeight: -h,
                biPlanes: 1,
                biBitCount: 32,
                biCompression: BI_RGB,
                biSizeImage: (w as u32) * (h as u32) * 4,
                biXPelsPerMeter: 0,
                biYPelsPerMeter: 0,
                biClrUsed: 0,
                biClrImportant: 0,
            },
            bmiColors: [0; 3],
        };
        let mut pixels = vec![0u8; (w as usize) * (h as usize) * 4];
        let got = GetDIBits(
            mem_dc,
            hbmp,
            0,
            h as u32,
            pixels.as_mut_ptr() as *mut c_void,
            &mut bmi,
            DIB_RGB_COLORS,
        );
        let old = SelectObject(mem_dc, old);
        let _ = old;
        DeleteObject(hbmp as HGDIOBJ);
        DeleteDC(mem_dc);
        ReleaseDC(std::ptr::null_mut(), screen_dc);
        if got == 0 {
            return Err("GetDIBits 失败".to_string());
        }

        let (tr, tg, tb) = util::parse_color(&cfg.color);
        let mut gray = 0usize;
        let total = (w as usize) * (h as usize);
        for i in 0..total {
            let b = pixels[i * 4] as i32;
            let g = pixels[i * 4 + 1] as i32;
            let r = pixels[i * 4 + 2] as i32;
            let near_color = (r - tr as i32).abs() <= 24
                && (g - tg as i32).abs() <= 24
                && (b - tb as i32).abs() <= 24;
            let is_gray = (r - g).abs() <= 12 && (g - b).abs() <= 12;
            if near_color && is_gray {
                gray += 1;
            }
        }
        let ratio = gray as f64 / total as f64;

        // 顺手存一张 BMP：BMP 自下而上，手上的数据是自上而下，写的时候反向。
        let out = std::env::temp_dir().join("screenwatermark_selftest.bmp");
        let mut f = std::fs::File::create(&out).map_err(|e| e.to_string())?;
        let row_bytes = (w as usize) * 4;
        let file_size = 14 + 40 + row_bytes * (h as usize);
        let mut hdr = Vec::with_capacity(54);
        hdr.extend_from_slice(b"BM");
        hdr.extend_from_slice(&(file_size as u32).to_le_bytes());
        hdr.extend_from_slice(&0u32.to_le_bytes());
        hdr.extend_from_slice(&54u32.to_le_bytes());
        hdr.extend_from_slice(&40u32.to_le_bytes());
        hdr.extend_from_slice(&w.to_le_bytes());
        hdr.extend_from_slice(&h.to_le_bytes());
        hdr.extend_from_slice(&1u16.to_le_bytes());
        hdr.extend_from_slice(&32u16.to_le_bytes());
        hdr.extend_from_slice(&0u32.to_le_bytes());
        hdr.extend_from_slice(&((row_bytes * h as usize) as u32).to_le_bytes());
        hdr.extend_from_slice(&2835u32.to_le_bytes());
        hdr.extend_from_slice(&2835u32.to_le_bytes());
        hdr.extend_from_slice(&0u32.to_le_bytes());
        hdr.extend_from_slice(&0u32.to_le_bytes());
        f.write_all(&hdr).map_err(|e| e.to_string())?;
        for row in (0..h as usize).rev() {
            f.write_all(&pixels[row * row_bytes..(row + 1) * row_bytes])
                .map_err(|e| e.to_string())?;
        }
        println!(
            "SELFTEST ok screen={}x{} color={} gray_pixels={} total={} ratio={:.6} bmp={}",
            w,
            h,
            cfg.color,
            gray,
            total,
            ratio,
            out.display()
        );
        Ok(())
    }
}

fn main() {
    let (args, text_override) = parse_args();
    if args.show_version {
        println!("{} {}", APP_NAME, APP_VERSION);
        return;
    }
    if args.show_help {
        println!(
            "{} {}\n用法：ScreenWatermark.exe [--text \"文字\"] [--settings] [--probe] [--save-config] [--selftest] [--log]\n快捷键：Ctrl+Alt+W 显示/隐藏　Ctrl+Alt+S 设置面板　Ctrl+Alt+Q 退出",
            APP_NAME, APP_VERSION
        );
        return;
    }

    // 日志：只有显式要求才写文件，避免默认在 exe 旁边留垃圾。
    let log_path = if args.log {
        Some(util::exe_dir().join("rust-debug.log"))
    } else {
        None
    };
    log::init(log_path, false);

    // DPI 感知放在最前面：manifest 已经声明 PerMonitorV2，这里再显式调一次，
    // 保证没有 manifest 时（比如直接跑 target 里的 exe）也是物理像素。
    unsafe {
        if SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2) == 0 {
            SetProcessDPIAware();
        }
    }

    let hinst = unsafe { GetModuleHandleW(std::ptr::null()) };

    // 一次性命令模式（--probe / --save-config / --selftest）刻意放在单实例
    // 检查之前：诊断和写配置不该被"另一个实例正在跑"挡住。
    if std::env::args().any(|a| a == "--probe")
        || std::env::args().any(|a| a == "--save-config")
        || std::env::args().any(|a| a == "--selftest")
    {
        std::process::exit(run_oneshot(&args, text_override, hinst));
    }

    // 单实例：已有实例就安静退出（第二次双击不该冒出第二个水印）。
    let mutex_name = util::to_wide(MUTEX_NAME);
    let mutex = unsafe { CreateMutexW(std::ptr::null_mut(), 0, mutex_name.as_ptr()) };
    if mutex.is_null() {
        util::fatal(&format!(
            "创建互斥体失败，错误码 {}。程序即将退出。",
            util::last_error()
        ));
        return;
    }
    if unsafe { GetLastError() } == ERROR_ALREADY_EXISTS {
        unsafe { CloseHandle(mutex) };
        return;
    }

    // GDI+ 全局初始化一次，token 留着退出时关。
    let gp_token = match render::gdiplus_startup() {
        Ok(t) => t,
        Err(e) => {
            util::fatal(&format!("{}\n水印无法渲染，程序即将退出。", e));
            unsafe { CloseHandle(mutex) };
            return;
        }
    };

    // 通用控件：TRACKBAR 必须先注册类，否则滑块建不出来。
    unsafe {
        let icc = INITCOMMONCONTROLSEX {
            dwSize: core::mem::size_of::<INITCOMMONCONTROLSEX>() as DWORD,
            dwICC: ICC_BAR_CLASSES | ICC_STANDARD_CLASSES,
        };
        InitCommonControlsEx(&icc);
    }

    if !overlay::register_overlay_class(hinst) {
        util::fatal(&format!(
            "水印窗口类注册失败，错误码 {}。程序即将退出。",
            util::last_error()
        ));
        unsafe {
            render::gdiplus_shutdown(gp_token);
            CloseHandle(mutex);
        }
        return;
    }
    if !settings::register_panel_class(hinst) {
        // 面板建不出来还能跑水印，只记日志不退出。
        log::line("设置面板窗口类注册失败，设置面板将不可用");
    }

    let (cfg, extras, cfg_path) = util::load_or_default();
    let mut cfg = cfg;
    if let Some(t) = text_override {
        cfg.text = t;
    }
    log::line(&format!(
        "启动 {} {}，配置 {}",
        APP_NAME,
        APP_VERSION,
        cfg_path.display()
    ));

    let app_box = Box::new(App::new(cfg, extras, cfg_path, hinst));
    let app_ptr: *mut App = Box::into_raw(app_box);

    // ---- 消息循环 ----
    let loop_handler = {
        let app_ptr = app_ptr as usize;
        Box::new(move |sig: Signal| {
            let app = unsafe { &mut *(app_ptr as *mut App) };
            handle_signal(app, sig);
        })
    };
    let mut msg_loop = match Loop::new(hinst, loop_handler) {
        Ok(l) => l,
        Err(e) => {
            util::fatal(&format!("{}\n程序即将退出。", e));
            unsafe {
                render::gdiplus_shutdown(gp_token);
                CloseHandle(mutex);
                drop(Box::from_raw(app_ptr));
            }
            return;
        }
    };

    let msg_hwnd = msg_loop.hwnd();
    let app = unsafe { &mut *app_ptr };
    app.msg_hwnd = msg_hwnd;

    // 托盘：失败只记警告，程序继续（托盘没了还有快捷键和面板）。
    let t = tray::Tray::install(msg_hwnd, hinst, app.cfg.enabled);
    if !t.added {
        log::line("托盘图标添加失败，只能用快捷键和设置面板控制");
    }
    app.tray = Some(t);

    let hotkeys = dispatch::register_hotkeys(msg_hwnd);
    // 每个动作各报一行："想要哪个、拿到哪个、为什么降级"。
    // 注册失败不影响运行，托盘菜单仍然可用。
    for l in hotkeys.log_lines() {
        log::line(&l);
    }
    log::line(&hotkeys.hint_line());
    app.hotkeys = hotkeys;

    // 顶置定时器 3 秒一次（规格要求）；刷新检查用同一个节奏。
    unsafe {
        SetTimer(msg_hwnd, TIMER_TOPMOST, 3000, std::ptr::null_mut());
        SetTimer(msg_hwnd, dispatch::TIMER_REFRESH, 3000, std::ptr::null_mut());
    }

    // 首次绘制。
    app.refresh_overlays(true);



    // 空闲回调：把节流后的重画补上。每轮消息泵之后跑一次，
    // 连续拖动滑块时只会重画最后那一帧。
    let idle_ptr = app_ptr as usize;
    msg_loop.set_idle(Box::new(move || {
        let app = unsafe { &mut *(idle_ptr as *mut App) };
        if app.pending_render {
            app.refresh_overlays(false);
        }
    }));

    if args.show_settings {
        app.open_settings();
    }

    msg_loop.run();

    // ---- 收尾 ----
    let app = unsafe { &mut *app_ptr };
    if let Some(mut t) = app.tray.take() {
        t.remove();
    }
    dispatch::unregister_hotkeys(msg_hwnd);
    unsafe {
        KillTimer(msg_hwnd, TIMER_TOPMOST);
        KillTimer(msg_hwnd, dispatch::TIMER_REFRESH);
    }
    app.overlays.destroy_all();
    unsafe {
        render::gdiplus_shutdown(gp_token);
        CloseHandle(mutex);
        drop(Box::from_raw(app_ptr));
    }
    log::line("已退出");
}

/// 把信号翻译成动作。托盘菜单也在这里处理，因为它需要 App 的状态。
fn handle_signal(app: &mut App, sig: Signal) {
    match sig {
        Signal::ToggleWatermark => app.toggle_watermark(),
        Signal::TogglePanel => app.toggle_settings(),
        Signal::Quit => app.quit(),
        Signal::Refresh => {
            log::line("显示器或系统设置变化，重建水印");
            app.refresh_overlays(true);
        }
        Signal::Tick => {
            // 顶置 + 模板时间跳变检查，都是便宜操作。
            app.overlays.raise_all();
            if app.cfg.template {
                let now = util::template_time_value(&app.cfg);
                if now != app.last_template {
                    app.pending_render = true;
                }
            }
        }
        Signal::TrayPopup => tray_popup_and_dispatch(app),
        Signal::TrayCommand(cmd) => run_tray_command(app, cmd),
    }
}

/// 弹托盘菜单并把选择执行掉。TrackPopupMenu 内部有自己的消息循环，
/// 期间收到的信号会重入 handle_signal —— 这是 Win32 的常态，
/// 各分支都不依赖"当前正在处理什么"，所以是安全的。
fn tray_popup_and_dispatch(app: &mut App) {
    let autostart = util::get_autostart();
    let owner = app
        .tray
        .as_ref()
        .map(|t| t.hwnd)
        .unwrap_or(app.msg_hwnd);
    let cmd = tray::show_menu(owner, &app.cfg, autostart);
    if cmd != 0 {
        run_tray_command(app, cmd);
    }
}

fn run_tray_command(app: &mut App, cmd: usize) {
    match cmd {
        tray::CMD_TOGGLE => app.toggle_watermark(),
        tray::CMD_SETTINGS => app.toggle_settings(),
        tray::CMD_RELOAD => app.reload_config(),
        tray::CMD_AUTOSTART => {
            let want = !util::get_autostart();
            if util::set_autostart(want) {
                app.cfg.autostart = want;
                app.save_config();
                log::line(if want {
                    "已开启开机自启"
                } else {
                    "已关闭开机自启"
                });
            } else {
                util::info_box("写入开机自启注册表项失败，请检查权限。");
            }
        }
        tray::CMD_EXIT => app.quit(),
        _ => {}
    }
}
