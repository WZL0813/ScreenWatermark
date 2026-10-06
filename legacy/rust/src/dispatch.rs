// 消息循环与隐藏的消息窗口。
// 单独一个窗口（而不是复用水印窗口）的原因：水印窗口在极端情况下会被
// 用户或系统销毁/重建，热点键和托盘回调不该跟着一起断。

use crate::ffi::*;
use crate::util;
use std::ffi::c_void;

pub const MSG_CLASS: &str = "ScreenWatermarkMsg";

/// PeekMessage 的 wRemoveMsg 取值。
#[allow(dead_code)] // 留着方便以后加"只抽不删"的探测循环
pub const PM_REMOVE: UINT = 0x0001;

/// 定时器 ID。顶置用 1，配置/模板刷新用 2。
pub const TIMER_REFRESH: usize = 2;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Signal {
    ToggleWatermark,
    TogglePanel,
    Quit,
    /// 托盘右键：该弹菜单了。
    TrayPopup,
    /// 托盘菜单命令，值就是 tray::CMD_*。
    #[allow(dead_code)] // 主逻辑直接调 run_tray_command，这个变体留给外部驱动
    TrayCommand(usize),
    /// 该重画了（配置变、模板跳变、屏幕变）
    Refresh,
    /// 定时器到点，主循环用来查有没有需要做的事
    Tick,
}

pub type Handler = Box<dyn FnMut(Signal)>;

struct Dispatcher {
    handler: Handler,
    hwnd: HWND,
}

/// 消息窗口的状态槽。窗口过程是 extern "system" 回调，拿不到 &mut self，
/// 所以用 GWLP_USERDATA 挂一个 Box 指针，销毁时收回。
static mut SLOT: *mut Dispatcher = std::ptr::null_mut();

pub struct Loop {
    hwnd: HWND,
    /// 空闲回调：每轮消息泵空转之后调一次，用来做节流后的重画。
    idle: Option<Box<dyn FnMut()>>,
}

impl Loop {
    /// 注册窗口类 + 建隐藏窗口，顺便把三个全局快捷键挂上。
    pub fn new(hinst: HINSTANCE, handler: Handler) -> Result<Loop, String> {
        unsafe {
            let mut wc: WNDCLASSEXW = std::mem::zeroed();
            wc.cbSize = core::mem::size_of::<WNDCLASSEXW>() as UINT;
            wc.lpfnWndProc = Some(msg_wndproc);
            wc.hInstance = hinst;
            // 必须先把宽字符串绑到局部变量：to_wide 的返回值如果当临时值用，
            // 语句结束就释放，窗口类名会变成野指针。
            let cls_name = util::to_wide(MSG_CLASS);
            wc.lpszClassName = cls_name.as_ptr();
            let atom = RegisterClassExW(&wc);
            if atom == 0 && util::last_error() != 1410 {
                return Err(format!("RegisterClassExW 失败，错误码 {}", util::last_error()));
            }
            let cls = util::to_wide(MSG_CLASS);
            let title = util::to_wide("ScreenWatermark");
            // 纯消息窗口，不显示、不进任务栏、不抢焦点。
            let hwnd = CreateWindowExW(
                WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
                cls.as_ptr(),
                title.as_ptr(),
                WS_POPUP,
                0,
                0,
                0,
                0,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                hinst,
                std::ptr::null_mut(),
            );
            if hwnd.is_null() {
                return Err(format!(
                    "消息窗口创建失败，错误码 {}",
                    util::last_error()
                ));
            }
            let d = Box::new(Dispatcher { handler, hwnd });
            let raw = Box::into_raw(d);
            SLOT = raw;
            SetWindowLongPtrW(hwnd, GWLP_USERDATA, raw as isize);
            Ok(Loop { hwnd, idle: None })
        }
    }

    pub fn hwnd(&self) -> HWND {
        self.hwnd
    }

    pub fn set_idle(&mut self, f: Box<dyn FnMut()>) {
        self.idle = Some(f);
    }

    /// 取回挂在窗口上的回调，只有主循环退出时用。
    fn reclaim(&mut self) {
        unsafe {
            if !SLOT.is_null() {
                let d = Box::from_raw(SLOT);
                // 顺手把窗口上的指针清掉，避免销毁时再被碰一次。
                SetWindowLongPtrW(d.hwnd, GWLP_USERDATA, 0);
                SLOT = std::ptr::null_mut();
            }
        }
    }

    /// 主循环。GetMessage 空闲时会把 CPU 让出去，静置占用接近 0%。
    pub fn run(&mut self) {
        unsafe {
            let mut msg: MSG = std::mem::zeroed();
            loop {
                let r = GetMessageW(&mut msg, std::ptr::null_mut(), 0, 0);
                if r == 0 {
                    break; // WM_QUIT
                }
                if r == -1 {
                    break; // 出错，别死循环
                }
                if IsDialogMessageW(msg.hwnd, &mut msg) != 0 {
                    continue; // 让设置面板的 Tab / 回车工作
                }
                TranslateMessage(&msg);
                DispatchMessageW(&msg);
                if let Some(f) = self.idle.as_mut() {
                    f();
                }
            }
        }
        self.reclaim();
    }
}

/// 快捷键 ID。数值无所谓，只要不同。
pub const HK_TOGGLE: i32 = 1;
pub const HK_PANEL: i32 = 2;
pub const HK_QUIT: i32 = 3;

pub const VK_W: u32 = 0x57;
pub const VK_S: u32 = 0x53;
pub const VK_Q: u32 = 0x51;

/// 三个需要全局热键的动作。用它做索引和匹配，别在代码里到处比较魔数 ID。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum HotkeyAction {
    ToggleWatermark,
    TogglePanel,
    Quit,
}

impl HotkeyAction {
    pub fn all() -> [HotkeyAction; 3] {
        [
            HotkeyAction::ToggleWatermark,
            HotkeyAction::TogglePanel,
            HotkeyAction::Quit,
        ]
    }

    pub fn id(self) -> i32 {
        match self {
            HotkeyAction::ToggleWatermark => HK_TOGGLE,
            HotkeyAction::TogglePanel => HK_PANEL,
            HotkeyAction::Quit => HK_QUIT,
        }
    }

    /// 候选组合，按优先级排列：首选 Ctrl+Alt+X，被占用就退一级到 Ctrl+Alt+Shift+X。
    /// 顺序即降级顺序，改这个表就等于改降级策略。
    pub fn candidates(self) -> [(UINT, u32); 2] {
        match self {
            HotkeyAction::ToggleWatermark => [
                (MOD_CONTROL | MOD_ALT, VK_W),
                (MOD_CONTROL | MOD_ALT | MOD_SHIFT, VK_W),
            ],
            HotkeyAction::TogglePanel => [
                (MOD_CONTROL | MOD_ALT, VK_S),
                (MOD_CONTROL | MOD_ALT | MOD_SHIFT, VK_S),
            ],
            HotkeyAction::Quit => [
                (MOD_CONTROL | MOD_ALT, VK_Q),
                (MOD_CONTROL | MOD_ALT | MOD_SHIFT, VK_Q),
            ],
        }
    }

    /// 首选组合的显示名，用于日志里解释"为什么降级了"。
    pub fn preferred_label(self) -> String {
        let (mods, vk) = self.candidates()[0];
        combo_label(mods, vk)
    }
}

/// "Ctrl+Alt+Shift+W" 这种可读写法。顺序固定，方便一眼比对。
pub fn combo_label(mods: UINT, vk: u32) -> String {
    let mut s = String::new();
    if mods & MOD_CONTROL != 0 {
        s.push_str("Ctrl+");
    }
    if mods & MOD_ALT != 0 {
        s.push_str("Alt+");
    }
    if mods & MOD_SHIFT != 0 {
        s.push_str("Shift+");
    }
    // 只用来显示 W/S/Q 这三个键，够用就不引 CharUpper。
    match vk {
        VK_W => s.push('W'),
        VK_S => s.push('S'),
        VK_Q => s.push('Q'),
        other => s.push_str(&format!("0x{:02X}", other)),
    }
    s
}

/// 一个动作最终的注册结果。
#[derive(Clone, Debug)]
pub struct Binding {
    pub action: HotkeyAction,
    /// 最终采用的组合（ok=false 时是"最后尝试过的那一个"）
    pub mods: UINT,
    pub vk: u32,
    /// 是否真的注册上了
    pub ok: bool,
    /// 最终这次尝试的错误码（ok=true 时为 0）
    pub err: DWORD,
    /// 首选组合那次尝试的错误码。降级的原因就在这个值里（1409 = 被占用）。
    pub preferred_err: DWORD,
    /// 首选组合失败、退到了第二候选
    pub fallback: bool,
}

impl Binding {
    pub fn label(&self) -> String {
        combo_label(self.mods & !MOD_NOREPEAT, self.vk)
    }

    /// 首选组合的显示名，便于对比"想要什么、拿到了什么"。
    pub fn preferred_label(&self) -> String {
        self.action.preferred_label()
    }
}

/// 三个动作的注册结果集合。
#[derive(Clone, Debug, Default)]
pub struct Hotkeys {
    pub bindings: Vec<Binding>,
}

impl Hotkeys {
    /// 逐个动作注册，首选失败自动降级。任何一个失败都不算致命错误。
    pub fn register_all(hwnd: HWND) -> Hotkeys {
        let mut bindings = Vec::with_capacity(3);
        for action in HotkeyAction::all() {
            let cands = action.candidates();
            let mut chosen: Option<Binding> = None;
            let mut preferred_err: DWORD = 0;
            let mut last_err: DWORD = 0;
            for (i, (mods, vk)) in cands.iter().enumerate() {
                // 先清零：RegisterHotKey 成功时不会写 last error，
                // 不清零就会把上一次留下的 1409 误当成这次的失败原因。
                let (ok, err) = unsafe {
                    SetLastError(0);
                    let r = RegisterHotKey(hwnd, action.id(), *mods | MOD_NOREPEAT, *vk);
                    let e = if r == 0 { GetLastError() } else { 0 };
                    (r != 0, e)
                };
                if i == 0 {
                    preferred_err = err;
                }
                if ok {
                    chosen = Some(Binding {
                        action,
                        mods: *mods,
                        vk: *vk,
                        ok: true,
                        err: 0,
                        preferred_err,
                        fallback: i > 0,
                    });
                    break;
                }
                last_err = err;
            }
            // 全部候选都失败：记下最后尝试的组合和错误码，程序照常跑。
            bindings.push(chosen.unwrap_or_else(|| {
                let last = cands[cands.len() - 1];
                Binding {
                    action,
                    mods: last.0,
                    vk: last.1,
                    ok: false,
                    err: last_err,
                    preferred_err,
                    fallback: false,
                }
            }));
        }
        Hotkeys { bindings }
    }

    pub fn get(&self, action: HotkeyAction) -> Option<&Binding> {
        self.bindings.iter().find(|b| b.action == action)
    }

    /// 实际生效的组合；没注册上就返回 None。
    pub fn effective_label(&self, action: HotkeyAction) -> Option<String> {
        self.get(action).filter(|b| b.ok).map(|b| b.label())
    }

    /// 设置面板底部那行提示。没注册上的动作要如实说"未注册"，
    /// 否则用户按了没反应会以为是程序坏了。
    pub fn hint_line(&self) -> String {
        let f = |a: HotkeyAction, what: &str| -> String {
            match self.effective_label(a) {
                Some(l) => format!("{} {}", l, what),
                None => format!("{} 未注册", what),
            }
        };
        format!(
            "快捷键：{}　{}　{}（关面板不退出程序）",
            f(HotkeyAction::ToggleWatermark, "显示/隐藏"),
            f(HotkeyAction::TogglePanel, "面板"),
            f(HotkeyAction::Quit, "退出"),
        )
    }

    /// 启动日志：每个动作报"想要哪个、拿到哪个、失败原因"。
    pub fn log_lines(&self) -> Vec<String> {
        let mut out = Vec::new();
        for b in &self.bindings {
            if b.ok {
                if b.fallback {
                    out.push(format!(
                        "快捷键 {} 已被占用（错误码 {}），降级为 {} 生效",
                        b.preferred_label(),
                        ERROR_HOTKEY_ALREADY_REGISTERED,
                        b.label()
                    ));
                } else {
                    out.push(format!("快捷键 {} 已注册", b.label()));
                }
            } else {
                out.push(format!(
                    "快捷键 {} 注册失败（错误码 {}），该动作只能用托盘菜单",
                    b.label(),
                    b.err
                ));
            }
        }
        out
    }
}

/// 注册三个全局快捷键（含自动降级）。
pub fn register_hotkeys(hwnd: HWND) -> Hotkeys {
    Hotkeys::register_all(hwnd)
}

pub fn unregister_hotkeys(hwnd: HWND) {
    unsafe {
        UnregisterHotKey(hwnd, HK_TOGGLE);
        UnregisterHotKey(hwnd, HK_PANEL);
        UnregisterHotKey(hwnd, HK_QUIT);
    }
}

unsafe extern "system" fn msg_wndproc(
    hwnd: HWND,
    msg: UINT,
    wparam: WPARAM,
    lparam: LPARAM,
) -> LRESULT {
    // 不在 WM_CREATE 里取状态：那个指针在 CreateWindowExW 返回后也有效，
    // 直接用 SLOT 更省事，但 SLOT 只在主循环退出时清空。
    match msg {
        WM_HOTKEY => {
            let id = wparam as i32;
            with_handler(|d| {
                let sig = match id {
                    HK_TOGGLE => Some(Signal::ToggleWatermark),
                    HK_PANEL => Some(Signal::TogglePanel),
                    HK_QUIT => Some(Signal::Quit),
                    _ => None,
                };
                if let Some(s) = sig {
                    (d.handler)(s);
                }
            });
            0
        }
        WM_TRAY => {
            let (ev, _id) = crate::tray::tray_event(lparam);
            let dbl = crate::tray::is_double_click(ev);
            let right = crate::tray::is_right_click(ev);
            if dbl {
                with_handler(|d| (d.handler)(Signal::TogglePanel));
            } else if right {
                // 菜单要同步弹出（TrackPopupMenu 自己跑内嵌消息循环），
                // 所以只通知"该弹菜单"，实际弹窗由主逻辑做。
                with_handler(|d| (d.handler)(Signal::TrayPopup));
            }
            0
        }
        WM_TIMER => {
            if wparam == TIMER_REFRESH {
                with_handler(|d| (d.handler)(Signal::Tick));
            }
            0
        }
        WM_DISPLAYCHANGE | WM_DPICHANGED | WM_SETTINGCHANGE => {
            with_handler(|d| (d.handler)(Signal::Refresh));
            0
        }
        WM_CLOSE => {
            // 消息窗口不接受关闭，退出只能走托盘/快捷键。
            0
        }
        WM_DESTROY => {
            PostQuitMessage(0);
            0
        }
        _ => DefWindowProcW(hwnd, msg, wparam, lparam),
    }
}

/// 取出回调并调用。参数里的 hwnd 只用于日志，不参与逻辑。
unsafe fn with_handler<F: FnOnce(&mut Dispatcher)>(f: F) {
    if SLOT.is_null() {
        return;
    }
    f(&mut *SLOT);
}

// c_void 在本模块只用于 HWND 的 typedef，占个位避免未用导入。
const _: Option<*mut c_void> = None;
