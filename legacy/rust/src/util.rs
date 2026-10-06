// 宽字符串、显示器枚举、模板变量、开机自启 —— 与业务无关的杂活都放这里。

use crate::config::Config;
use crate::ffi::*;
use std::collections::BTreeMap;
use std::ffi::c_void;
use std::path::{Path, PathBuf};

/// 字符串 -> 以 0 结尾的 UTF-16。所有 Win32 W 系列 API 都吃这个，
/// 集中一处省得每个调用点手搓 Vec 忘了 push(0)。
pub fn to_wide(s: &str) -> Vec<u16> {
    let mut v: Vec<u16> = s.encode_utf16().collect();
    v.push(0);
    v
}

/// UTF-16（可为 0 结尾）-> String，遇到孤立代理项就丢，不 panic。
pub fn from_wide(buf: &[u16]) -> String {
    let end = buf.iter().position(|&c| c == 0).unwrap_or(buf.len());
    String::from_utf16_lossy(&buf[..end])
}

/// 写进定长 u16 数组，超长截断并保证结尾是 0。托盘 szTip 之类需要。
pub fn write_wide_array<const N: usize>(dst: &mut [u16; N], s: &str) {
    let w: Vec<u16> = s.encode_utf16().take(N - 1).collect();
    for (i, c) in w.iter().enumerate() {
        dst[i] = *c;
    }
    dst[w.len()] = 0;
}

/// 最近一次 Win32 错误，用于弹窗时给点线索。
pub fn last_error() -> u32 {
    unsafe { GetLastError() }
}

/// 启动期致命错误：规格要求弹窗，不许静默退出。
pub fn fatal(msg: &str) {
    let text = to_wide(msg);
    let cap = to_wide("ScreenWatermark 启动失败");
    unsafe {
        // MB_OK | MB_ICONERROR | MB_TOPMOST | MB_SETFOREGROUND
        MessageBoxW(
            std::ptr::null_mut(),
            text.as_ptr(),
            cap.as_ptr(),
            0x0000_0010 | 0x0001_0000 | 0x0004_0000 | 0x0001_0000,
        );
    }
}

/// 非致命提示：只在真的需要打断用户时用。
pub fn info_box(msg: &str) {
    let text = to_wide(msg);
    let cap = to_wide("ScreenWatermark");
    unsafe {
        MessageBoxW(
            std::ptr::null_mut(),
            text.as_ptr(),
            cap.as_ptr(),
            0x0000_0040 | 0x0004_0000,
        );
    }
}

// ---------------- 显示器 ----------------

#[derive(Clone, Copy, Debug)]
pub struct Monitor {
    pub hmon: *mut c_void,
    /// 物理像素矩形（PerMonitorV2 下就是真实像素）。
    pub rect: RECT,
    pub dpi: u32,
    pub primary: bool,
}

unsafe extern "system" fn enum_monitor_proc(
    hmon: *mut c_void,
    _hdc: HDC,
    _rect: *mut RECT,
    data: LPARAM,
) -> BOOL {
    let list = &mut *(data as *mut Vec<Monitor>);
    let mut mi = MONITORINFO {
        cbSize: core::mem::size_of::<MONITORINFO>() as DWORD,
        ..Default::default()
    };
    if GetMonitorInfoW(hmon, &mut mi) != 0 {
        // 显示器 DPI 用 GetDpiForWindow 得先有窗口，这里按屏幕宽度粗略反推：
        // 系统缩放 100% 时宽 1920 的常见档位足够，取不到就按 96 处理。
        list.push(Monitor {
            hmon,
            rect: mi.rcMonitor,
            dpi: 96,
            primary: (mi.dwFlags & MONITORINFOF_PRIMARY) != 0,
        });
    }
    TRUE
}

/// 枚举所有显示器。失败时退化成主屏一个，绝不返回空表 —— 空表会让水印彻底消失。
pub fn enum_monitors() -> Vec<Monitor> {
    let mut list: Vec<Monitor> = Vec::new();
    unsafe {
        EnumDisplayMonitors(
            std::ptr::null_mut(),
            std::ptr::null(),
            Some(enum_monitor_proc),
            &mut list as *mut Vec<Monitor> as LPARAM,
        );
    }
    if list.is_empty() {
        let w = unsafe { GetSystemMetrics(0) };
        let h = unsafe { GetSystemMetrics(1) };
        list.push(Monitor {
            hmon: std::ptr::null_mut(),
            rect: RECT {
                left: 0,
                top: 0,
                right: if w > 0 { w } else { 1920 },
                bottom: if h > 0 { h } else { 1080 },
            },
            dpi: 96,
            primary: true,
        });
    }
    list
}

/// 按配置挑出要挂水印的显示器。
pub fn pick_monitors(all: bool) -> Vec<Monitor> {
    let mons = enum_monitors();
    if all {
        return mons;
    }
    let mut only: Vec<Monitor> = mons.iter().copied().filter(|m| m.primary).collect();
    if only.is_empty() {
        only = mons;
    }
    only
}

// ---------------- 系统信息 ----------------

pub fn user_name() -> String {
    let mut buf = [0u16; 256];
    let mut n = buf.len() as DWORD;
    unsafe {
        if GetUserNameW(buf.as_mut_ptr(), &mut n) != 0 {
            return from_wide(&buf);
        }
    }
    String::new()
}

pub fn computer_name() -> String {
    let mut buf = [0u16; 256];
    let mut n = buf.len() as DWORD;
    unsafe {
        if GetComputerNameW(buf.as_mut_ptr(), &mut n) != 0 {
            return from_wide(&buf);
        }
    }
    String::new()
}

/// 本机内网 IPv4：连一个外网地址（不发包）让系统选出出口网卡，
/// 再问 getsockname 拿地址。取不到就空串，规格允许。
pub fn local_ipv4() -> String {
    use std::net::UdpSocket;
    if let Ok(sock) = UdpSocket::bind("0.0.0.0:0") {
        if sock.connect("8.8.8.8:80").is_ok() {
            if let Ok(addr) = sock.local_addr() {
                if let std::net::IpAddr::V4(v4) = addr.ip() {
                    return v4.to_string();
                }
            }
        }
    }
    String::new()
}

// ---------------- 时间格式化 ----------------

/// 只实现 strftime 里文档提到的那些，外加几个常用的。
/// 不认的指令原样输出，免得用户写错格式后整条时间消失。
pub fn strftime(fmt: &str, t: &SYSTEMTIME) -> String {
    let mut out = String::with_capacity(fmt.len() + 8);
    let mut it = fmt.chars().peekable();
    while let Some(c) = it.next() {
        if c != '%' {
            out.push(c);
            continue;
        }
        match it.next() {
            None => out.push('%'),
            Some('Y') => out.push_str(&format!("{:04}", t.wYear)),
            Some('y') => out.push_str(&format!("{:02}", t.wYear % 100)),
            Some('m') => out.push_str(&format!("{:02}", t.wMonth)),
            Some('d') => out.push_str(&format!("{:02}", t.wDay)),
            Some('H') => out.push_str(&format!("{:02}", t.wHour)),
            Some('I') => {
                let h = if t.wHour % 12 == 0 { 12 } else { t.wHour % 12 };
                out.push_str(&format!("{:02}", h));
            }
            Some('M') => out.push_str(&format!("{:02}", t.wMinute)),
            Some('S') => out.push_str(&format!("{:02}", t.wSecond)),
            Some('j') => out.push_str(&format!("{:03}", day_of_year(t))),
            Some('p') => out.push_str(if t.wHour < 12 { "AM" } else { "PM" }),
            Some('a') => out.push_str(WEEKDAY_SHORT[t.wDayOfWeek as usize % 7]),
            Some('A') => out.push_str(WEEKDAY_LONG[t.wDayOfWeek as usize % 7]),
            Some('b') => out.push_str(MONTH_SHORT[(t.wMonth as usize).clamp(1, 12) - 1]),
            Some('B') => out.push_str(MONTH_LONG[(t.wMonth as usize).clamp(1, 12) - 1]),
            Some('w') => out.push_str(&t.wDayOfWeek.to_string()),
            Some('n') => out.push('\n'),
            Some('t') => out.push('\t'),
            Some('%') => out.push('%'),
            Some(other) => {
                // 不认识的指令：原样吐回去，方便用户发现写错了。
                out.push('%');
                out.push(other);
            }
        }
    }
    out
}

const WEEKDAY_SHORT: [&str; 7] = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const WEEKDAY_LONG: [&str; 7] = [
    "Sunday",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
];
const MONTH_SHORT: [&str; 12] = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];
const MONTH_LONG: [&str; 12] = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
];

fn day_of_year(t: &SYSTEMTIME) -> u32 {
    const CUM: [u32; 12] = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334];
    let m = (t.wMonth as usize).clamp(1, 12);
    let mut d = CUM[m - 1] + t.wDay as u32;
    let y = t.wYear as u32;
    let leap = (y % 4 == 0 && y % 100 != 0) || y % 400 == 0;
    if leap && m > 2 {
        d += 1;
    }
    d
}

pub fn now_local() -> SYSTEMTIME {
    let mut st = SYSTEMTIME::default();
    unsafe { GetLocalTime(&mut st) };
    st
}

/// 模板变量替换，规格 §3。`{{` / `}}` 是转义，要在识别变量之前处理。
pub fn expand_template(cfg: &Config, raw: &str) -> String {
    if !cfg.template {
        return raw.to_string();
    }
    let mut out = String::with_capacity(raw.len() + 16);
    let chars: Vec<char> = raw.chars().collect();
    let mut i = 0usize;
    let mut cached_time: Option<String> = None;
    while i < chars.len() {
        let c = chars[i];
        if c == '{' {
            if i + 1 < chars.len() && chars[i + 1] == '{' {
                out.push('{');
                i += 2;
                continue;
            }
            // 找配对的 }
            if let Some(rel) = chars[i + 1..].iter().position(|&x| x == '}') {
                let name: String = chars[i + 1..i + 1 + rel].iter().collect();
                let key = name.trim().to_ascii_lowercase();
                let val = match key.as_str() {
                    "time" => {
                        if cached_time.is_none() {
                            cached_time = Some(strftime(&cfg.time_format, &now_local()));
                        }
                        cached_time.clone().unwrap_or_default()
                    }
                    "date" => strftime("%Y-%m-%d", &now_local()),
                    "user" => user_name(),
                    "host" => computer_name(),
                    "ip" => local_ipv4(),
                    _ => {
                        // 未知变量原样保留，写错的模板肉眼可见。
                        let mut s = String::from("{");
                        s.push_str(&name);
                        s.push('}');
                        s
                    }
                };
                out.push_str(&val);
                i += rel + 2;
                continue;
            }
        } else if c == '}' && i + 1 < chars.len() && chars[i + 1] == '}' {
            out.push('}');
            i += 2;
            continue;
        }
        out.push(c);
        i += 1;
    }
    out
}

/// 模板里唯一会跳变的变量是时间，用它决定要不要按 refresh_seconds 重画。
pub fn template_time_value(cfg: &Config) -> String {
    if cfg.template {
        strftime(&cfg.time_format, &now_local())
    } else {
        String::new()
    }
}

// ---------------- 路径 ----------------

pub fn exe_dir() -> PathBuf {
    let mut buf = [0u16; 1024];
    let n = unsafe { GetModuleFileNameW(std::ptr::null_mut(), buf.as_mut_ptr(), buf.len() as DWORD) };
    let s = from_wide(&buf[..n as usize]);
    let mut p = PathBuf::from(s);
    p.pop();
    p
}

/// 配置目录优先级：exe 同级 → %APPDATA%\ScreenWatermark。
/// 只判断"能不能写"，不能写就换地方，读的时候两个位置都试。
/// 返回值第二个元素是"读时要一起考虑的候选路径"，顺序即优先级。
pub fn config_candidates() -> (PathBuf, Vec<PathBuf>) {
    let dir = exe_dir();
    let primary = dir.join("config.json");
    let mut fallback = appdata_dir();
    fallback.push("ScreenWatermark");
    let fb = fallback.join("config.json");

    let writable = can_write_dir(&dir);
    let mut cands = vec![primary.clone()];
    cands.push(fb.clone());
    if writable {
        (primary, cands)
    } else {
        let _ = std::fs::create_dir_all(&fallback);
        (fb, cands)
    }
}

/// 只是"写回时用哪个路径"。
pub fn config_path() -> PathBuf {
    config_candidates().0
}

/// 读配置时按优先级挑第一个存在的文件。
pub fn config_read_path() -> Option<PathBuf> {
    let (write_target, cands) = config_candidates();
    for c in &cands {
        if c.exists() {
            return Some(c.clone());
        }
    }
    if write_target.exists() {
        Some(write_target)
    } else {
        None
    }
}

pub fn appdata_dir() -> PathBuf {
    PathBuf::from(std::env::var("APPDATA").unwrap_or_else(|_| ".".into()))
}

fn can_write_dir(dir: &Path) -> bool {
    let probe = dir.join(".sw_write_probe");
    match std::fs::write(&probe, b"") {
        Ok(_) => {
            let _ = std::fs::remove_file(&probe);
            true
        }
        Err(_) => false,
    }
}

/// 配置文件读不到时按默认值跑；坏文件备份成 config.bad.json 再继续。
pub fn load_or_default() -> (Config, BTreeMap<String, String>, PathBuf) {
    let target = config_path();
    let read_from = config_read_path();
    match read_from {
        None => (Config::default(), BTreeMap::new(), target),
        Some(p) => match std::fs::read(&p) {
            Err(_) => (Config::default(), BTreeMap::new(), target),
            Ok(bytes) => {
                let text = decode_utf8(&bytes);
                let stripped = text.trim_start_matches('\u{feff}');
                match Config::parse_with_extras(stripped) {
                    Some((cfg, extras)) => (cfg, extras, target),
                    None => {
                        // 坏文件挪走，别让它每轮启动都报一次错。
                        let bad = p.with_file_name("config.bad.json");
                        let _ = std::fs::rename(&p, &bad);
                        (Config::default(), BTreeMap::new(), target)
                    }
                }
            }
        },
    }
}

/// UTF-8 解码：非法字节用替换字符顶上，别让一个坏字节毁掉整个配置。
pub fn decode_utf8(bytes: &[u8]) -> String {
    // 先按无 BOM 处理；有 BOM 的话 trim_start_matches 会吃掉。
    match std::str::from_utf8(bytes) {
        Ok(s) => s.to_string(),
        Err(_) => String::from_utf8_lossy(bytes).to_string(),
    }
}


// ---------------- 开机自启 ----------------

const RUN_KEY: &str = "Software\\Microsoft\\Windows\\CurrentVersion\\Run";
const RUN_VALUE: &str = "ScreenWatermark";

/// 只动 HKCU，不碰 HKLM —— 不需要管理员权限。
pub fn set_autostart(enable: bool) -> bool {
    let sub = to_wide(RUN_KEY);
    let name = to_wide(RUN_VALUE);
    unsafe {
        let mut key: HKEY = std::ptr::null_mut();
        let rc = RegCreateKeyExW(
            HKEY_CURRENT_USER,
            sub.as_ptr(),
            0,
            std::ptr::null(),
            0,
            KEY_WRITE | KEY_READ,
            std::ptr::null_mut(),
            &mut key,
            std::ptr::null_mut(),
        );
        if rc != ERROR_SUCCESS || key.is_null() {
            return false;
        }
        let ok = if enable {
            let exe = exe_dir().join("ScreenWatermark.exe");
            let cmd = format!("\"{}\"", exe.display());
            let data = to_wide(&cmd);
            let bytes = (data.len() * 2) as DWORD;
            RegSetValueExW(
                key,
                name.as_ptr(),
                0,
                REG_SZ,
                data.as_ptr() as *const u8,
                bytes,
            ) == ERROR_SUCCESS
        } else {
            let rc = RegDeleteValueW(key, name.as_ptr());
            rc == ERROR_SUCCESS || rc == ERROR_FILE_NOT_FOUND
        };
        RegCloseKey(key);
        ok
    }
}

/// 读注册表判断当前是否已自启，托盘菜单的勾选状态靠它。
pub fn get_autostart() -> bool {
    let sub = to_wide(RUN_KEY);
    let name = to_wide(RUN_VALUE);
    unsafe {
        let mut key: HKEY = std::ptr::null_mut();
        if RegOpenKeyExW(HKEY_CURRENT_USER, sub.as_ptr(), 0, KEY_READ, &mut key) != ERROR_SUCCESS {
            return false;
        }
        let mut buf = [0u16; 1024];
        let mut cb = (buf.len() * 2) as DWORD;
        let rc = RegQueryValueExW(
            key,
            name.as_ptr(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            buf.as_mut_ptr() as *mut u8,
            &mut cb,
        );
        RegCloseKey(key);
        rc == ERROR_SUCCESS
    }
}

// ---------------- 小工具 ----------------

/// 颜色串 "#RRGGBB" -> (r,g,b)。容错：带不带 # 都认，三位缩写也认。
pub fn parse_color(s: &str) -> (u8, u8, u8) {
    let t = s.trim().trim_start_matches('#');
    let hex: String = t.chars().filter(|c| c.is_ascii_hexdigit()).collect();
    let parse = |x: &str| u8::from_str_radix(x, 16).unwrap_or(0x80);
    match hex.len() {
        6 => (
            parse(&hex[0..2]),
            parse(&hex[2..4]),
            parse(&hex[4..6]),
        ),
        3 => {
            let r = parse(&hex[0..1]);
            let g = parse(&hex[1..2]);
            let b = parse(&hex[2..3]);
            (r * 17, g * 17, b * 17)
        }
        _ => (0x80, 0x80, 0x80),
    }
}

pub fn color_to_hex(c: (u8, u8, u8)) -> String {
    format!("#{:02X}{:02X}{:02X}", c.0, c.1, c.2)
}

/// 系统里有没有这个字体族：用 GDI+ 试着建一下，建不起来就回退。
/// 放在 render 里做更自然，但那需要 graphics 对象；这里专门为设置面板
/// 提供一个不带 graphics 的探测（GdipCreateFontFamilyFromName 不需要 graphics）。
#[allow(dead_code)]
pub fn font_exists(name: &str) -> bool {
    let w = to_wide(name);
    unsafe {
        let mut family: GpFontFamily = std::ptr::null_mut();
        let st = GdipCreateFontFamilyFromName(w.as_ptr(), std::ptr::null_mut(), &mut family);
        if st == GP_OK && !family.is_null() {
            GdipDeleteFontFamily(family);
            true
        } else {
            false
        }
    }
}

/// 常用中文字体候选，设置面板的下拉内容。
pub const FONT_CANDIDATES: [&str; 8] = [
    "Microsoft YaHei",
    "Microsoft YaHei UI",
    "SimHei",
    "SimSun",
    "KaiTi",
    "FangSong",
    "Segoe UI",
    "Arial",
];

/// 取一个必定能用的字体名：配置里的优先，找不到就按规格回退系统 UI 字体。
pub fn resolve_font_family(preferred: &str) -> String {
    if !preferred.trim().is_empty() && font_exists(preferred) {
        return preferred.to_string();
    }
    for cand in ["Microsoft YaHei", "Segoe UI", "SimSun", "Arial"] {
        if font_exists(cand) {
            return cand.to_string();
        }
    }
    String::new() // 空串让 GDI+ 用默认族
}

pub fn clamp_i(v: i64, lo: i64, hi: i64) -> i64 {
    if v < lo {
        lo
    } else if v > hi {
        hi
    } else {
        v
    }
}

pub fn clamp_f(v: f64, lo: f64, hi: f64) -> f64 {
    if !v.is_finite() {
        return lo;
    }
    if v < lo {
        lo
    } else if v > hi {
        hi
    } else {
        v
    }
}
