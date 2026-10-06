// 托盘图标 + 右键菜单。规格 §4：左键双击开面板，右键出菜单，菜单里能开关水印、
// 重载配置、切自启、退出。NIM_ADD 失败不许崩 —— 那时还能靠快捷键和托盘之外的方式控制。

use crate::config::Config;
use crate::ffi::*;
use crate::util::{to_wide, write_wide_array};

pub const TRAY_ID: UINT = 1;
pub const ICON_RESOURCE_ID: usize = 1;

/// 托盘菜单项 ID。数值随便挑，只要不和系统命令冲突。
pub const CMD_TOGGLE: usize = 1001;
pub const CMD_SETTINGS: usize = 1002;
pub const CMD_RELOAD: usize = 1003;
pub const CMD_AUTOSTART: usize = 1004;
pub const CMD_EXIT: usize = 1005;

pub struct Tray {
    pub added: bool,
    pub hwnd: HWND,
    pub hicon: HICON,
    /// 从资源里加载的图标是共享的，退出时不能 DestroyIcon。
    owns_icon: bool,
}

impl Tray {
    /// 把图标挂到通知区。失败只记录，不影响程序继续跑。
    pub fn install(hwnd: HWND, hinst: HINSTANCE, enabled: bool) -> Tray {
        let hicon = load_app_icon(hinst);
        let mut t = Tray {
            added: false,
            hwnd,
            hicon,
            owns_icon: false,
        };
        let mut nid = NOTIFYICONDATAW::default();
        nid.hWnd = hwnd;
        nid.uID = TRAY_ID;
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP;
        nid.uCallbackMessage = WM_TRAY;
        nid.hIcon = t.hicon;
        write_wide_array(&mut nid.szTip, &tip_text(enabled));
        let ok = unsafe { Shell_NotifyIconW(NIM_ADD, &mut nid) };
        t.added = ok != 0;
        if t.added {
            // 用 V4 版本才能收到 WM_CONTEXTMENU，菜单行为跟系统一致。
            let mut ver = NOTIFYICONDATAW::default();
            ver.hWnd = hwnd;
            ver.uID = TRAY_ID;
            ver.uVersion = NOTIFYICON_VERSION_4;
            unsafe { Shell_NotifyIconW(NIM_SETVERSION, &mut ver) };
        }
        t
    }

    pub fn update_tip(&self, enabled: bool) {
        if !self.added {
            return;
        }
        let mut nid = NOTIFYICONDATAW::default();
        nid.hWnd = self.hwnd;
        nid.uID = TRAY_ID;
        nid.uFlags = NIF_TIP;
        write_wide_array(&mut nid.szTip, &tip_text(enabled));
        unsafe { Shell_NotifyIconW(NIM_MODIFY, &mut nid) };
    }

    pub fn remove(&mut self) {
        if !self.added {
            return;
        }
        let mut nid = NOTIFYICONDATAW::default();
        nid.hWnd = self.hwnd;
        nid.uID = TRAY_ID;
        unsafe { Shell_NotifyIconW(NIM_DELETE, &mut nid) };
        self.added = false;
        if self.owns_icon && !self.hicon.is_null() {
            unsafe { DestroyIcon(self.hicon) };
            self.hicon = std::ptr::null_mut();
        }
    }
}

/// 托盘提示文字，规格里写死的两种。
pub fn tip_text(enabled: bool) -> String {
    if enabled {
        "ScreenWatermark · 已启用".to_string()
    } else {
        "ScreenWatermark · 已隐藏".to_string()
    }
}

/// 优先用资源里的 app.ico（windres 挂上去的，ID=1），拿不到退系统默认图标。
pub fn load_app_icon(hinst: HINSTANCE) -> HICON {
    unsafe {
        let h = LoadImageW(
            hinst,
            ICON_RESOURCE_ID as *const u16,
            IMAGE_ICON,
            0,
            0,
            LR_DEFAULTSIZE | LR_SHARED,
        );
        if !h.is_null() {
            return h as HICON;
        }
        let fallback = LoadIconW(std::ptr::null_mut(), IDI_APPLICATION as *const u16);
        if !fallback.is_null() {
            return fallback;
        }
        std::ptr::null_mut()
    }
}

/// 弹出右键菜单，返回被选中的命令 ID（0 = 用户点了别处）。
/// 必须先 SetForegroundWindow，否则菜单点了不消失，这是 Shell 的老规矩。
pub fn show_menu(hwnd: HWND, cfg: &Config, autostart: bool) -> usize {
    unsafe {
        let menu = CreatePopupMenu();
        if menu.is_null() {
            return 0;
        }
        let show_label = if cfg.enabled {
            "隐藏水印(&W)\tCtrl+Alt+W"
        } else {
            "显示水印(&W)\tCtrl+Alt+W"
        };
        AppendMenuW(menu, MF_STRING, CMD_TOGGLE, to_wide(show_label).as_ptr());
        AppendMenuW(menu, MF_STRING, CMD_SETTINGS, to_wide("设置(&S)…\tCtrl+Alt+S").as_ptr());
        AppendMenuW(menu, MF_STRING, CMD_RELOAD, to_wide("重新载入配置(&R)").as_ptr());
        AppendMenuW(menu, MF_SEPARATOR, 0, std::ptr::null());
        let auto_flags = if autostart { MF_STRING | MF_CHECKED } else { MF_STRING };
        AppendMenuW(menu, auto_flags, CMD_AUTOSTART, to_wide("开机自启(&A)").as_ptr());
        AppendMenuW(menu, MF_SEPARATOR, 0, std::ptr::null());
        AppendMenuW(menu, MF_STRING, CMD_EXIT, to_wide("退出(&X)\tCtrl+Alt+Q").as_ptr());

        let mut pt = POINT::default();
        GetCursorPos(&mut pt);
        SetForegroundWindow(hwnd);
        let cmd = TrackPopupMenuEx(
            menu,
            TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY,
            pt.x,
            pt.y,
            hwnd,
            std::ptr::null_mut(),
        );
        // 这条空 PostMessage 是 Shell 文档要求的，用来让菜单可靠地关闭。
        PostMessageW(hwnd, WM_NULL, 0, 0);
        DestroyMenu(menu);
        if cmd > 0 {
            cmd as usize
        } else {
            0
        }
    }
}

/// 托盘回调消息的 lParam 解包：低字是鼠标消息，高字是图标 ID。
pub fn tray_event(lparam: LPARAM) -> (u32, u32) {
    let v = lparam as u32;
    let msg = v & 0xFFFF;
    let id = (v >> 16) & 0xFFFF;
    (msg, id)
}

/// 双击=开面板（规格 §4）。WM_CONTEXTMENU 也要出菜单。
pub fn is_double_click(msg: u32) -> bool {
    msg == WM_LBUTTONDBLCLK
}

pub fn is_right_click(msg: u32) -> bool {
    msg == WM_RBUTTONUP || msg == WM_CONTEXTMENU
}
