// 所有 extern 声明和常量集中在这里：业务代码里出现裸指针就算跑题。
// 约定：Win32 API 用 extern "system"；GDI+ 的 flat API 是 cdecl，用 extern "C"。
// 64 位下两者调用约定相同，但写对能避免以后有人拿 32 位目标编时踩坑。

#![allow(non_snake_case)]
#![allow(non_camel_case_types)]
// GDI+ 的枚举成员沿用官方拼写（FontStyleBold 之类），改成全大写反而和文档对不上。
#![allow(non_upper_case_globals)]
#![allow(dead_code)]

use core::ffi::c_void;

pub type BOOL = i32;
pub type UINT = u32;
pub type DWORD = u32;
pub type WORD = u16;
pub type LONG = i32;
pub type ULONG = u32;
pub type ULONG_PTR = usize;
pub type ATOM = u16;
pub type WPARAM = usize;
pub type LPARAM = isize;
pub type LRESULT = isize;
pub type HINSTANCE = *mut c_void;
pub type HWND = *mut c_void;
pub type HMENU = *mut c_void;
pub type HICON = *mut c_void;
pub type HCURSOR = *mut c_void;
pub type HBRUSH = *mut c_void;
pub type HFONT = *mut c_void;
pub type HDC = *mut c_void;
pub type HBITMAP = *mut c_void;
pub type HGDIOBJ = *mut c_void;
pub type HANDLE = *mut c_void;
pub type HKEY = *mut c_void;
pub type HRGN = *mut c_void;
pub type LPCTSTR = *const u16;

pub const TRUE: BOOL = 1;
pub const FALSE: BOOL = 0;

// ---------------- 窗口类 / 窗口样式 ----------------

pub const CS_VREDRAW: UINT = 0x0001;
pub const CS_HREDRAW: UINT = 0x0002;
pub const CS_DBLCLKS: UINT = 0x0008;

pub const WS_OVERLAPPEDWINDOW: DWORD = 0x00CF0000;
pub const WS_POPUP: DWORD = 0x8000_0000;
pub const WS_CHILD: DWORD = 0x4000_0000;
pub const WS_VISIBLE: DWORD = 0x1000_0000;
pub const WS_DISABLED: DWORD = 0x0800_0000;
pub const WS_CLIPSIBLINGS: DWORD = 0x0400_0000;
pub const WS_TABSTOP: DWORD = 0x0001_0000;
pub const WS_BORDER: DWORD = 0x0080_0000;
pub const WS_CAPTION: DWORD = 0x00C0_0000;
pub const WS_SYSMENU: DWORD = 0x0008_0000;
pub const WS_MINIMIZEBOX: DWORD = 0x0002_0000;
pub const WS_MAXIMIZEBOX: DWORD = 0x0001_0000;
pub const WS_THICKFRAME: DWORD = 0x0004_0000;
pub const WS_VSCROLL: DWORD = 0x0020_0000;
pub const WS_GROUP: DWORD = 0x0002_0000;
pub const WS_HSCROLL: DWORD = 0x0010_0000;

pub const WS_EX_LAYERED: DWORD = 0x0008_0000;
pub const WS_EX_TRANSPARENT: DWORD = 0x0000_0020;
pub const WS_EX_TOOLWINDOW: DWORD = 0x0000_0080;
pub const WS_EX_NOACTIVATE: DWORD = 0x0800_0000;
pub const WS_EX_TOPMOST: DWORD = 0x0000_0008;
pub const WS_EX_APPWINDOW: DWORD = 0x0004_0000;
pub const WS_EX_DLGMODALFRAME: DWORD = 0x0000_0001;
pub const WS_EX_COMPOSITED: DWORD = 0x0200_0000;

pub const GWL_STYLE: i32 = -16;
pub const GWL_EXSTYLE: i32 = -20;
pub const GWLP_WNDPROC: i32 = -4;
pub const GWLP_USERDATA: i32 = -21;

pub const SW_SHOWNORMAL: i32 = 1;
pub const SW_SHOWNOACTIVATE: i32 = 4;
pub const SW_HIDE: i32 = 0;

pub const HWND_TOPMOST: HWND = -1isize as HWND;
pub const HWND_NOTOPMOST: HWND = -2isize as HWND;

pub const SWP_NOSIZE: UINT = 0x0001;
pub const SWP_NOMOVE: UINT = 0x0002;
pub const SWP_NOZORDER: UINT = 0x0004;
pub const SWP_NOACTIVATE: UINT = 0x0010;
pub const SWP_SHOWWINDOW: UINT = 0x0040;
pub const SWP_HIDEWINDOW: UINT = 0x0080;
pub const SWP_NOOWNERZORDER: UINT = 0x0200;

// ---------------- 消息 ----------------

pub const WM_NULL: UINT = 0x0000;
pub const WM_CREATE: UINT = 0x0001;
pub const WM_DESTROY: UINT = 0x0002;
pub const WM_CLOSE: UINT = 0x0010;
pub const WM_PAINT: UINT = 0x000F;
pub const WM_QUERYENDSESSION: UINT = 0x0011;
pub const WM_ENDSESSION: UINT = 0x0016;
pub const WM_QUIT: UINT = 0x0012;
pub const WM_ERASEBKGND: UINT = 0x0014;
pub const WM_SHOWWINDOW: UINT = 0x0018;
pub const WM_SETTINGCHANGE: UINT = 0x001A;
pub const WM_DISPLAYCHANGE: UINT = 0x007E;
pub const WM_DPICHANGED: UINT = 0x02E0;
pub const WM_TIMER: UINT = 0x0113;
pub const WM_COMMAND: UINT = 0x0111;
pub const WM_SYSCOMMAND: UINT = 0x0112;
pub const WM_HSCROLL: UINT = 0x0114;
pub const WM_VSCROLL: UINT = 0x0115;
pub const WM_CTLCOLORSTATIC: UINT = 0x0138;
pub const WM_CTLCOLOREDIT: UINT = 0x0133;
pub const WM_CTLCOLORBTN: UINT = 0x0135;
pub const WM_CTLCOLORLISTBOX: UINT = 0x0134;
pub const WM_APP: UINT = 0x8000;
pub const WM_HOTKEY: UINT = 0x0312;
pub const WM_CONTEXTMENU: UINT = 0x007B;
pub const WM_LBUTTONUP: UINT = 0x0202;
pub const WM_LBUTTONDBLCLK: UINT = 0x0203;
pub const WM_RBUTTONUP: UINT = 0x0205;
pub const WM_NCHITTEST: UINT = 0x0084;
pub const WM_SETICON: UINT = 0x0080;

/// 托盘回调消息：WM_APP+1，规格里写死的。
pub const WM_TRAY: UINT = WM_APP + 1;

pub const SC_CLOSE: WPARAM = 0xF060;
pub const SC_KEYMENU: WPARAM = 0xF100;

pub const HTTRANSPARENT: LRESULT = -1;

// ---------------- 控件通知 ----------------

pub const EN_CHANGE: u16 = 0x0300;
pub const EN_SETFOCUS: u16 = 0x0100;
pub const BM_GETCHECK: UINT = 0x00F0;
pub const BM_SETCHECK: UINT = 0x00F1;
pub const BST_CHECKED: WPARAM = 1;
pub const BST_UNCHECKED: WPARAM = 0;
pub const WM_SETFONT: UINT = 0x0030;
pub const WS_EX_CLIENTEDGE: DWORD = 0x0000_0200;
/// trackbar 自动打刻度；滑块不支持负最小值，角度用 0..180 表示 -90..90。
pub const TBS_AUTOTICKS: DWORD = 0x0001;
pub const DEFAULT_GUI_FONT: i32 = 17;
pub const FW_NORMAL: DWORD = 400;
pub const DEFAULT_CHARSET: DWORD = 1;
pub const OUT_DEFAULT_PRECIS: DWORD = 0;
pub const CLIP_DEFAULT_PRECIS: DWORD = 0;
pub const CLEARTYPE_QUALITY: DWORD = 5;
pub const CBN_SELCHANGE: u16 = 1;
pub const BN_CLICKED: u16 = 0;

pub const TBM_GETPOS: UINT = WM_USER;
pub const TBM_SETPOS: UINT = WM_USER + 5;
pub const TBM_SETRANGE: UINT = WM_USER + 6;
pub const TBM_SETTICFREQ: UINT = WM_USER + 20;
pub const WM_USER: UINT = 0x0400;
pub const CB_ADDSTRING: UINT = 0x0143;
pub const CB_SETCURSEL: UINT = 0x014E;
pub const CB_GETCURSEL: UINT = 0x0147;
pub const CB_GETLBTEXT: UINT = 0x0148;
pub const CB_GETLBTEXTLEN: UINT = 0x0149;
pub const CB_FINDSTRINGEXACT: UINT = 0x0158;

pub const SWP_FLAGS_TOP: UINT = SWP_NOACTIVATE | SWP_NOMOVE | SWP_NOSIZE | SWP_NOOWNERZORDER;

/// 顶置定时器：3 秒一次，规格规定。
pub const TIMER_TOPMOST: usize = 1;

// ---------------- 标准控件样式 ----------------

pub const BS_PUSHBUTTON: DWORD = 0x0000_0000;
pub const BS_DEFPUSHBUTTON: DWORD = 0x0000_0001;
pub const BS_AUTOCHECKBOX: DWORD = 0x0000_0003;
pub const BS_GROUPBOX: DWORD = 0x0000_0007;
pub const ES_LEFT: DWORD = 0x0000;
pub const ES_MULTILINE: DWORD = 0x0004;
pub const ES_AUTOHSCROLL: DWORD = 0x0080;
pub const ES_NUMBER: DWORD = 0x2000;
pub const ES_READONLY: DWORD = 0x0800;
pub const ES_CENTER: DWORD = 0x0001;
pub const SS_LEFT: DWORD = 0x0000_0000;
pub const SS_CENTER: DWORD = 0x0000_0001;
pub const SS_RIGHT: DWORD = 0x0000_0002;
pub const SS_SUNKEN: DWORD = 0x0000_1000;

// ---------------- 菜单 ----------------

pub const MF_STRING: UINT = 0x0000_0000;
pub const MF_CHECKED: UINT = 0x0000_0008;
pub const MF_UNCHECKED: UINT = 0x0000_0000;
pub const MF_SEPARATOR: UINT = 0x0000_0800;
pub const MF_GRAYED: UINT = 0x0000_0001;
pub const MF_DISABLED: UINT = 0x0000_0002;

pub const TPM_LEFTALIGN: UINT = 0x0000;
pub const TPM_RIGHTBUTTON: UINT = 0x0002;
pub const TPM_RETURNCMD: UINT = 0x0100;
pub const TPM_NONOTIFY: UINT = 0x0080;

pub const NIM_ADD: DWORD = 0x0000_0000;
pub const NIM_MODIFY: DWORD = 0x0000_0001;
pub const NIM_DELETE: DWORD = 0x0000_0002;
pub const NIM_SETVERSION: DWORD = 0x0000_0004;
pub const NOTIFYICON_VERSION_4: DWORD = 4;
pub const NIF_MESSAGE: DWORD = 0x0000_0001;
pub const NIF_ICON: DWORD = 0x0000_0002;
pub const NIF_TIP: DWORD = 0x0000_0004;
pub const NIF_INFO: DWORD = 0x0000_0010;
pub const NIIF_INFO: DWORD = 0x0000_0001;

pub const IDI_APPLICATION: usize = 32512;
pub const IMAGE_ICON: UINT = 1;
pub const LR_DEFAULTSIZE: UINT = 0x0000_0040;
pub const LR_SHARED: UINT = 0x0000_8000;

pub const COLOR_WINDOW: i32 = 5;
pub const COLOR_BTNFACE: i32 = 15;

// ---------------- 显示器 / DPI ----------------

pub const MONITOR_DEFAULTTONEAREST: DWORD = 2;
pub const MONITORINFOF_PRIMARY: DWORD = 0x0000_0001;

pub const DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2: isize = -4;

// ---------------- 热键 ----------------

pub const MOD_ALT: UINT = 0x0001;
pub const MOD_CONTROL: UINT = 0x0002;
pub const MOD_SHIFT: UINT = 0x0004;
pub const MOD_NOREPEAT: UINT = 0x4000;

// ---------------- 注册表 ----------------

pub const HKEY_CURRENT_USER: HKEY = 0x8000_0001u32 as usize as HKEY;
pub const KEY_READ: DWORD = 0x0002_0019;
pub const KEY_WRITE: DWORD = 0x0002_0006;
pub const REG_SZ: DWORD = 1;
pub const ERROR_SUCCESS: LONG = 0;
pub const ERROR_FILE_NOT_FOUND: LONG = 2;
pub const ERROR_MORE_DATA: LONG = 234;
pub const ERROR_CLASS_ALREADY_EXISTS: DWORD = 1410;
/// CreateMutexW 之后 GetLastError 返回它表示已经有实例在跑。
pub const ERROR_ALREADY_EXISTS: DWORD = 183;
/// RegisterHotKey 失败时返回它：该组合已被别的程序（或本进程）占用。
pub const ERROR_HOTKEY_ALREADY_REGISTERED: DWORD = 1409;

// ---------------- GDI ----------------

pub const BI_RGB: DWORD = 0;
pub const DIB_RGB_COLORS: UINT = 0;
pub const SRCCOPY: DWORD = 0x00CC_0020;
pub const ULW_ALPHA: DWORD = 0x0000_0002;
pub const AC_SRC_OVER: u8 = 0x00;
pub const AC_SRC_ALPHA: u8 = 0x01;

#[repr(C)]
#[derive(Clone, Copy, Debug, Default)]
pub struct POINT {
    pub x: i32,
    pub y: i32,
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Default)]
pub struct SIZE {
    pub cx: i32,
    pub cy: i32,
}

#[repr(C)]
#[derive(Clone, Copy, Debug, Default)]
pub struct RECT {
    pub left: i32,
    pub top: i32,
    pub right: i32,
    pub bottom: i32,
}

impl RECT {
    pub fn width(&self) -> i32 {
        self.right - self.left
    }
    pub fn height(&self) -> i32 {
        self.bottom - self.top
    }
}

#[repr(C)]
#[derive(Clone, Copy)]
pub struct BLENDFUNCTION {
    pub BlendOp: u8,
    pub BlendFlags: u8,
    pub SourceConstantAlpha: u8,
    pub AlphaFormat: u8,
}

/// 预乘 alpha + 负高度（top-down），这是 §10 明确要求的像素布局。
#[repr(C)]
pub struct BITMAPINFO {
    pub bmiHeader: BITMAPINFOHEADER,
    pub bmiColors: [u32; 3],
}

#[repr(C)]
#[derive(Clone, Copy, Default)]
pub struct BITMAPINFOHEADER {
    pub biSize: DWORD,
    pub biWidth: LONG,
    pub biHeight: LONG,
    pub biPlanes: WORD,
    pub biBitCount: WORD,
    pub biCompression: DWORD,
    pub biSizeImage: DWORD,
    pub biXPelsPerMeter: LONG,
    pub biYPelsPerMeter: LONG,
    pub biClrUsed: DWORD,
    pub biClrImportant: DWORD,
}

#[repr(C)]
#[derive(Clone, Copy, Default)]
pub struct MONITORINFO {
    pub cbSize: DWORD,
    pub rcMonitor: RECT,
    pub rcWork: RECT,
    pub dwFlags: DWORD,
}

#[repr(C)]
pub struct WNDCLASSEXW {
    pub cbSize: UINT,
    pub style: UINT,
    pub lpfnWndProc: WNDPROC,
    pub cbClsExtra: i32,
    pub cbWndExtra: i32,
    pub hInstance: HINSTANCE,
    pub hIcon: HICON,
    pub hCursor: HCURSOR,
    pub hbrBackground: HBRUSH,
    pub lpszMenuName: *const u16,
    pub lpszClassName: *const u16,
    pub hIconSm: HICON,
}

pub type WNDPROC = Option<unsafe extern "system" fn(HWND, UINT, WPARAM, LPARAM) -> LRESULT>;

#[repr(C)]
pub struct MSG {
    pub hwnd: HWND,
    pub message: UINT,
    pub wParam: WPARAM,
    pub lParam: LPARAM,
    pub time: DWORD,
    pub pt: POINT,
}

#[repr(C)]
pub struct PAINTSTRUCT {
    pub hdc: HDC,
    pub fErase: BOOL,
    pub rcPaint: RECT,
    pub fRestore: BOOL,
    pub fIncUpdate: BOOL,
    pub rgbReserved: [u8; 32],
}

/// NOTIFYICONDATAW 的 V2 尺寸：Windows 会按 cbSize 判断能用哪些字段。
/// 这里声明成完整版本，cbSize 用 size_of 算出来，省得手数偏移。
#[repr(C)]
pub struct NOTIFYICONDATAW {
    pub cbSize: DWORD,
    pub hWnd: HWND,
    pub uID: UINT,
    pub uFlags: UINT,
    pub uCallbackMessage: UINT,
    pub hIcon: HICON,
    pub szTip: [u16; 128],
    pub dwState: DWORD,
    pub dwStateMask: DWORD,
    pub szInfo: [u16; 256],
    pub uVersion: UINT,
    pub szInfoTitle: [u16; 64],
    pub dwInfoFlags: DWORD,
    pub guidItem: [u8; 16],
    pub hBalloonIcon: HICON,
}

impl Default for NOTIFYICONDATAW {
    fn default() -> Self {
        // 手写 Default：数组太长，derive 也能做，但这里顺便把 cbSize 填好。
        NOTIFYICONDATAW {
            cbSize: core::mem::size_of::<NOTIFYICONDATAW>() as DWORD,
            hWnd: core::ptr::null_mut(),
            uID: 1,
            uFlags: 0,
            uCallbackMessage: 0,
            hIcon: core::ptr::null_mut(),
            szTip: [0; 128],
            dwState: 0,
            dwStateMask: 0,
            szInfo: [0; 256],
            uVersion: 0,
            szInfoTitle: [0; 64],
            dwInfoFlags: 0,
            guidItem: [0; 16],
            hBalloonIcon: core::ptr::null_mut(),
        }
    }
}

#[repr(C)]
#[derive(Clone, Copy, Default)]
pub struct INITCOMMONCONTROLSEX {
    pub dwSize: DWORD,
    pub dwICC: DWORD,
}

pub const ICC_BAR_CLASSES: DWORD = 0x0000_0004;
pub const ICC_STANDARD_CLASSES: DWORD = 0x0000_4000;

#[repr(C)]
#[derive(Clone, Copy, Default)]
pub struct SYSTEMTIME {
    pub wYear: WORD,
    pub wMonth: WORD,
    pub wDayOfWeek: WORD,
    pub wDay: WORD,
    pub wHour: WORD,
    pub wMinute: WORD,
    pub wSecond: WORD,
    pub wMilliseconds: WORD,
}

// ================= kernel32 =================

#[link(name = "kernel32")]
extern "system" {
    pub fn GetModuleHandleW(lpModuleName: *const u16) -> HINSTANCE;
    pub fn GetLastError() -> DWORD;
    /// 探测"上次错误"前必须先清零，否则会读到更早调用留下的陈旧值。
    pub fn SetLastError(dwErrCode: DWORD);
    pub fn CreateMutexW(lpMutexAttributes: *mut c_void, bInitialOwner: BOOL, lpName: *const u16)
        -> HANDLE;
    pub fn CloseHandle(hObject: HANDLE) -> BOOL;
    pub fn GetLocalTime(lpSystemTime: *mut SYSTEMTIME);
    pub fn GetSystemTime(lpSystemTime: *mut SYSTEMTIME);
    pub fn GetUserNameW(lpBuffer: *mut u16, pcbBuffer: *mut DWORD) -> BOOL;
    pub fn GetComputerNameW(lpBuffer: *mut u16, nSize: *mut DWORD) -> BOOL;
    pub fn GetModuleFileNameW(hModule: HINSTANCE, lpFilename: *mut u16, nSize: DWORD) -> DWORD;
    pub fn Sleep(dwMilliseconds: DWORD);
    pub fn GetTickCount() -> DWORD;
    pub fn LocalFree(hMem: HANDLE) -> HANDLE;
    pub fn FormatMessageW(
        dwFlags: DWORD,
        lpSource: *mut c_void,
        dwMessageId: DWORD,
        dwLanguageId: DWORD,
        lpBuffer: *mut u16,
        nSize: DWORD,
        Arguments: *mut c_void,
    ) -> DWORD;
}

// ================= user32 =================

#[link(name = "user32")]
extern "system" {
    pub fn RegisterClassExW(lpWndClass: *const WNDCLASSEXW) -> ATOM;
    pub fn UnregisterClassW(lpClassName: *const u16, hInstance: HINSTANCE) -> BOOL;
    pub fn CreateWindowExW(
        dwExStyle: DWORD,
        lpClassName: *const u16,
        lpWindowName: *const u16,
        dwStyle: DWORD,
        X: i32,
        Y: i32,
        nWidth: i32,
        nHeight: i32,
        hWndParent: HWND,
        hMenu: HMENU,
        hInstance: HINSTANCE,
        lpParam: *mut c_void,
    ) -> HWND;
    pub fn DestroyWindow(hWnd: HWND) -> BOOL;
    pub fn DefWindowProcW(hWnd: HWND, Msg: UINT, wParam: WPARAM, lParam: LPARAM) -> LRESULT;
    pub fn GetMessageW(lpMsg: *mut MSG, hWnd: HWND, wMsgFilterMin: UINT, wMsgFilterMax: UINT)
        -> BOOL;
    pub fn PeekMessageW(
        lpMsg: *mut MSG,
        hWnd: HWND,
        wMsgFilterMin: UINT,
        wMsgFilterMax: UINT,
        wRemoveMsg: UINT,
    ) -> BOOL;
    pub fn TranslateMessage(lpMsg: *const MSG) -> BOOL;
    pub fn DispatchMessageW(lpMsg: *const MSG) -> LRESULT;
    pub fn PostQuitMessage(nExitCode: i32);
    pub fn PostMessageW(hWnd: HWND, Msg: UINT, wParam: WPARAM, lParam: LPARAM) -> BOOL;
    pub fn SendMessageW(hWnd: HWND, Msg: UINT, wParam: WPARAM, lParam: LPARAM) -> LRESULT;
    pub fn SetWindowLongPtrW(hWnd: HWND, nIndex: i32, dwNewLong: isize) -> isize;
    pub fn GetWindowLongPtrW(hWnd: HWND, nIndex: i32) -> isize;
    pub fn SetWindowPos(
        hWnd: HWND,
        hWndInsertAfter: HWND,
        X: i32,
        Y: i32,
        cx: i32,
        cy: i32,
        uFlags: UINT,
    ) -> BOOL;
    pub fn ShowWindow(hWnd: HWND, nCmdShow: i32) -> BOOL;
    pub fn UpdateWindow(hWnd: HWND) -> BOOL;
    pub fn IsWindow(hWnd: HWND) -> BOOL;
    pub fn IsWindowVisible(hWnd: HWND) -> BOOL;
    pub fn GetClientRect(hWnd: HWND, lpRect: *mut RECT) -> BOOL;
    pub fn GetWindowRect(hWnd: HWND, lpRect: *mut RECT) -> BOOL;
    pub fn SetForegroundWindow(hWnd: HWND) -> BOOL;
    pub fn GetForegroundWindow() -> HWND;
    pub fn SetFocus(hWnd: HWND) -> HWND;
    pub fn GetFocus() -> HWND;
    pub fn InvalidateRect(hWnd: HWND, lpRect: *const RECT, bErase: BOOL) -> BOOL;
    pub fn BeginPaint(hWnd: HWND, lpPaint: *mut PAINTSTRUCT) -> HDC;
    pub fn EndPaint(hWnd: HWND, lpPaint: *const PAINTSTRUCT) -> BOOL;
    pub fn FillRect(hDC: HDC, lprc: *const RECT, hbr: HBRUSH) -> i32;
    pub fn GetSystemMetrics(nIndex: i32) -> i32;
    pub fn GetDC(hWnd: HWND) -> HDC;
    pub fn ReleaseDC(hWnd: HWND, hDC: HDC) -> i32;
    pub fn UpdateLayeredWindow(
        hWnd: HWND,
        hdcDst: HDC,
        pptDst: *const POINT,
        psize: *const SIZE,
        hdcSrc: HDC,
        pptSrc: *const POINT,
        crKey: DWORD,
        pblend: *const BLENDFUNCTION,
        dwFlags: DWORD,
    ) -> BOOL;
    pub fn SetLayeredWindowAttributes(hWnd: HWND, crKey: DWORD, bAlpha: u8, dwFlags: DWORD) -> BOOL;
    pub fn RegisterHotKey(hWnd: HWND, id: i32, fsModifiers: UINT, vk: UINT) -> BOOL;
    pub fn UnregisterHotKey(hWnd: HWND, id: i32) -> BOOL;
    pub fn GetKeyState(nVirtKey: i32) -> i16;
    pub fn LoadIconW(hInstance: HINSTANCE, lpIconName: *const u16) -> HICON;
    pub fn LoadImageW(
        hInst: HINSTANCE,
        name: *const u16,
        type_: UINT,
        cx: i32,
        cy: i32,
        fuLoad: UINT,
    ) -> HANDLE;
    pub fn DestroyIcon(hIcon: HICON) -> BOOL;
    pub fn SetTimer(hWnd: HWND, nIDEvent: usize, uElapse: UINT, lpTimerFunc: *mut c_void) -> usize;
    pub fn KillTimer(hWnd: HWND, uIDEvent: usize) -> BOOL;
    pub fn MessageBoxW(hWnd: HWND, lpText: *const u16, lpCaption: *const u16, uType: UINT) -> i32;
    pub fn GetDpiForWindow(hWnd: HWND) -> UINT;
    pub fn SetProcessDpiAwarenessContext(value: isize) -> BOOL;
    pub fn SetProcessDPIAware() -> BOOL;
    pub fn EnumDisplayMonitors(
        hdc: HDC,
        lprcClip: *const RECT,
        lpfnEnum: MONITORENUMPROC,
        dwData: LPARAM,
    ) -> BOOL;
    pub fn GetMonitorInfoW(hMonitor: *mut c_void, lpmi: *mut MONITORINFO) -> BOOL;
    pub fn MonitorFromPoint(pt: POINT, dwFlags: DWORD) -> *mut c_void;
    pub fn GetCursorPos(lpPoint: *mut POINT) -> BOOL;
    pub fn GetWindowTextW(hWnd: HWND, lpString: *mut u16, nMaxCount: i32) -> i32;
    pub fn SetWindowTextW(hWnd: HWND, lpString: *const u16) -> BOOL;
    pub fn GetWindowTextLengthW(hWnd: HWND) -> i32;
    pub fn EnableWindow(hWnd: HWND, bEnable: BOOL) -> BOOL;
    pub fn GetDesktopWindow() -> HWND;
    pub fn SetCursor(hCursor: HCURSOR) -> HCURSOR;
    pub fn LoadCursorW(hInstance: HINSTANCE, lpCursorName: *const u16) -> HCURSOR;
    pub fn GetDlgCtrlID(hWnd: HWND) -> i32;
    pub fn IsDialogMessageW(hDlg: HWND, lpMsg: *mut MSG) -> BOOL;
    pub fn OpenClipboard(hWndNewOwner: HWND) -> BOOL;
    pub fn EmptyClipboard() -> BOOL;
    pub fn CloseClipboard() -> BOOL;
    pub fn GetSysColorBrush(nIndex: i32) -> HBRUSH;
    pub fn TrackPopupMenuEx(
        hMenu: HMENU,
        fuFlags: UINT,
        x: i32,
        y: i32,
        hwnd: HWND,
        lptpm: *mut c_void,
    ) -> BOOL;
    pub fn GetSystemMenu(hWnd: HWND, bRevert: BOOL) -> HMENU;
    pub fn DrawMenuBar(hWnd: HWND) -> BOOL;
}

// ---------------- 菜单 ----------------

#[link(name = "user32")]
extern "system" {
    pub fn CreatePopupMenu() -> HMENU;
    pub fn DestroyMenu(hMenu: HMENU) -> BOOL;
    pub fn AppendMenuW(hMenu: HMENU, uFlags: UINT, uIDNewItem: usize, lpNewItem: *const u16) -> BOOL;
    pub fn CheckMenuItem(hMenu: HMENU, uIDCheckItem: UINT, uCheck: UINT) -> DWORD;
    pub fn SetMenuDefaultItem(hMenu: HMENU, uItem: UINT, fByPos: UINT) -> BOOL;
}

pub type MONITORENUMPROC =
    Option<unsafe extern "system" fn(*mut c_void, HDC, *mut RECT, LPARAM) -> BOOL>;

pub const IDC_ARROW: usize = 32512;

// ================= gdi32 =================

#[link(name = "gdi32")]
extern "system" {
    pub fn CreateCompatibleDC(hdc: HDC) -> HDC;
    pub fn DeleteDC(hdc: HDC) -> BOOL;
    pub fn CreateDIBSection(
        hdc: HDC,
        pbmi: *const BITMAPINFO,
        usage: UINT,
        ppvBits: *mut *mut c_void,
        hSection: HANDLE,
        offset: DWORD,
    ) -> HBITMAP;
    pub fn SelectObject(hdc: HDC, h: HGDIOBJ) -> HGDIOBJ;
    pub fn DeleteObject(ho: HGDIOBJ) -> BOOL;
    pub fn BitBlt(
        hdcDest: HDC,
        x: i32,
        y: i32,
        cx: i32,
        cy: i32,
        hdcSrc: HDC,
        x1: i32,
        y1: i32,
        rop: DWORD,
    ) -> BOOL;
    pub fn CreateSolidBrush(color: DWORD) -> HBRUSH;
    pub fn CreateCompatibleBitmap(hdc: HDC, cx: i32, cy: i32) -> HBITMAP;
    pub fn GetDeviceCaps(hdc: HDC, index: i32) -> i32;
    pub fn GetDIBits(
        hdc: HDC,
        hbm: HBITMAP,
        start: UINT,
        cLines: UINT,
        lpvBits: *mut c_void,
        lpbmi: *mut BITMAPINFO,
        usage: UINT,
    ) -> i32;
}

// ================= gdiplus（flat API，cdecl）=================
// 不用 C++ 包装类，直接调导出的 C 函数；状态码 0 表示成功。

pub type GpStatus = i32;
pub type GpGraphics = *mut c_void;
pub type GpFontFamily = *mut c_void;
pub type GpFont = *mut c_void;
pub type GpBrush = *mut c_void;
pub type GpStringFormat = *mut c_void;
pub type GpImage = *mut c_void;
pub type GpBitmap = *mut c_void;
pub type ARGB = u32;
pub type Unit = i32;
pub type StringAlignment = i32;
pub type StringFormatFlags = i32;

/// GDI+ 的状态码。刻意叫 GP_OK 而不是 Ok —— 后者会在 use ffi::* 的模块里
/// 把标准库的 Result::Ok 遮住，导致所有 Ok(...) 模式匹配编译失败。
pub const GP_OK: GpStatus = 0;
pub const FontStyleRegular: i32 = 0;
pub const FontStyleBold: i32 = 1;
pub const FontStyleItalic: i32 = 2;
pub const SmoothingModeAntiAlias: i32 = 4;
pub const TextRenderingHintAntiAliasGridFit: i32 = 3;
pub const TextRenderingHintClearTypeGridFit: i32 = 5;
pub const UnitPoint: Unit = 3;
pub const UnitPixel: Unit = 2;
pub const StringAlignmentNear: StringAlignment = 0;
pub const StringFormatFlagsNoWrap: StringFormatFlags = 0x0000_1000;
pub const PixelFormat32bppPARGB: i32 = 0x000E_200B;

#[repr(C)]
#[derive(Clone, Copy, Default)]
pub struct GdiplusStartupInput {
    pub GdiplusVersion: u32,
    pub DebugEventCallback: *mut c_void,
    pub SuppressBackgroundThread: BOOL,
    pub SuppressExternalCodecs: BOOL,
}

#[repr(C)]
#[derive(Clone, Copy, Default)]
pub struct RectF {
    pub X: f32,
    pub Y: f32,
    pub Width: f32,
    pub Height: f32,
}

#[link(name = "gdiplus")]
extern "C" {
    pub fn GdiplusStartup(
        token: *mut ULONG_PTR,
        input: *const GdiplusStartupInput,
        output: *mut *mut c_void,
    ) -> GpStatus;
    pub fn GdiplusShutdown(token: ULONG_PTR);

    pub fn GdipCreateFromHDC(hdc: HDC, graphics: *mut GpGraphics) -> GpStatus;
    pub fn GdipDeleteGraphics(graphics: GpGraphics) -> GpStatus;
    pub fn GdipSetSmoothingMode(graphics: GpGraphics, mode: i32) -> GpStatus;
    pub fn GdipSetTextRenderingHint(graphics: GpGraphics, mode: i32) -> GpStatus;

    pub fn GdipCreateFontFamilyFromName(
        name: *const u16,
        fontCollection: *mut c_void,
        family: *mut GpFontFamily,
    ) -> GpStatus;
    pub fn GdipDeleteFontFamily(family: GpFontFamily) -> GpStatus;
    pub fn GdipCreateFont(
        family: GpFontFamily,
        emSize: f32,
        style: i32,
        unit: Unit,
        font: *mut GpFont,
    ) -> GpStatus;
    pub fn GdipDeleteFont(font: GpFont) -> GpStatus;
    pub fn GdipGetFontHeightGivenDPI(font: GpFont, dpi: f32, height: *mut f32) -> GpStatus;

    pub fn GdipCreateSolidFill(color: ARGB, brush: *mut GpBrush) -> GpStatus;
    pub fn GdipDeleteBrush(brush: GpBrush) -> GpStatus;

    pub fn GdipCreateStringFormat(
        formatAttributes: i32,
        language: u16,
        format: *mut GpStringFormat,
    ) -> GpStatus;
    pub fn GdipDeleteStringFormat(format: GpStringFormat) -> GpStatus;
    pub fn GdipSetStringFormatAlign(format: GpStringFormat, align: StringAlignment) -> GpStatus;
    pub fn GdipSetStringFormatLineAlign(
        format: GpStringFormat,
        align: StringAlignment,
    ) -> GpStatus;
    pub fn GdipSetStringFormatFlags(format: GpStringFormat, flags: i32) -> GpStatus;

    pub fn GdipDrawString(
        graphics: GpGraphics,
        string: *const u16,
        length: i32,
        font: GpFont,
        layoutRect: *const RectF,
        stringFormat: GpStringFormat,
        brush: GpBrush,
    ) -> GpStatus;
    pub fn GdipMeasureString(
        graphics: GpGraphics,
        string: *const u16,
        length: i32,
        font: GpFont,
        layoutRect: *const RectF,
        stringFormat: GpStringFormat,
        boundingBox: *mut RectF,
        codepointsFitted: *mut i32,
        linesFilled: *mut i32,
    ) -> GpStatus;

    pub fn GdipTranslateWorldTransform(
        graphics: GpGraphics,
        dx: f32,
        dy: f32,
        order: i32,
    ) -> GpStatus;
    pub fn GdipRotateWorldTransform(graphics: GpGraphics, angle: f32, order: i32) -> GpStatus;
    pub fn GdipResetWorldTransform(graphics: GpGraphics) -> GpStatus;

    pub fn GdipCreateBitmapFromScan0(
        width: i32,
        height: i32,
        stride: i32,
        format: i32,
        scan0: *mut u8,
        bitmap: *mut GpBitmap,
    ) -> GpStatus;
    pub fn GdipDisposeImage(image: GpImage) -> GpStatus;
    pub fn GdipGetImageGraphicsContext(image: GpImage, graphics: *mut GpGraphics) -> GpStatus;
    pub fn GdipGraphicsClear(graphics: GpGraphics, color: ARGB) -> GpStatus;
    pub fn GdipFlush(graphics: GpGraphics, intention: i32) -> GpStatus;
}

pub const MatrixOrderPrepend: i32 = 0;
pub const MatrixOrderAppend: i32 = 1;
pub const FlushIntentionSync: i32 = 1;

// ================= shell32 / advapi32 / comctl32 =================

#[link(name = "shell32")]
extern "system" {
    pub fn Shell_NotifyIconW(dwMessage: DWORD, lpData: *mut NOTIFYICONDATAW) -> BOOL;
}

#[link(name = "comctl32")]
extern "system" {
    pub fn InitCommonControlsEx(picce: *const INITCOMMONCONTROLSEX) -> BOOL;
}

#[link(name = "advapi32")]
extern "system" {
    pub fn RegCreateKeyExW(
        hKey: HKEY,
        lpSubKey: *const u16,
        Reserved: DWORD,
        lpClass: *const u16,
        dwOptions: DWORD,
        samDesired: DWORD,
        lpSecurityAttributes: *mut c_void,
        phkResult: *mut HKEY,
        lpdwDisposition: *mut DWORD,
    ) -> LONG;
    pub fn RegSetValueExW(
        hKey: HKEY,
        lpValueName: *const u16,
        Reserved: DWORD,
        dwType: DWORD,
        lpData: *const u8,
        cbData: DWORD,
    ) -> LONG;
    pub fn RegQueryValueExW(
        hKey: HKEY,
        lpValueName: *const u16,
        lpReserved: *mut DWORD,
        lpType: *mut DWORD,
        lpData: *mut u8,
        lpcbData: *mut DWORD,
    ) -> LONG;
    pub fn RegOpenKeyExW(
        hKey: HKEY,
        lpSubKey: *const u16,
        ulOptions: DWORD,
        samDesired: DWORD,
        phkResult: *mut HKEY,
    ) -> LONG;
    pub fn RegDeleteValueW(hKey: HKEY, lpValueName: *const u16) -> LONG;
    pub fn RegCloseKey(hKey: HKEY) -> LONG;
}
