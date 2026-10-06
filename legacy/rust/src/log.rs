// 极简日志。GUI 子系统没有控制台，出问题只能写文件 —— 但也不能把用户的
// 硬盘当草稿纸，所以文件名固定、按需追加，不轮转。
//
// 只有命令行传了 --log 才真的写文件；否则日志只在挂调试器时可见（OutputDebugString）。
// 这样默认双击运行时不会在 exe 旁边多出一个没人看的文件。

use std::fs::{File, OpenOptions};
use std::io::Write;
use std::sync::Mutex;
use std::sync::OnceLock;

static SINK: OnceLock<Mutex<Option<File>>> = OnceLock::new();
static DEBUG_OUT: OnceLock<bool> = OnceLock::new();

/// 进程启动时调一次。file=None 表示不写文件。
pub fn init(file: Option<std::path::PathBuf>, debug_out: bool) {
    let f = file.and_then(|p| {
        OpenOptions::new()
            .create(true)
            .append(true)
            .open(&p)
            .ok()
    });
    let _ = SINK.set(Mutex::new(f));
    let _ = DEBUG_OUT.set(debug_out);
}

/// 写一行日志。失败一律忽略 —— 日志写不进去不该影响水印。
pub fn line(msg: &str) {
    // 时间戳用 Win32 本地时间，省一个时钟依赖。
    let ts = crate::util::strftime("%H:%M:%S", &crate::util::now_local());
    let text = format!("[{}] {}\n", ts, msg);
    if let Some(m) = SINK.get() {
        if let Ok(mut g) = m.lock() {
            if let Some(f) = g.as_mut() {
                let _ = f.write_all(text.as_bytes());
            }
        }
    }
    if DEBUG_OUT.get().copied().unwrap_or(false) {
        debug_string(&text);
    }
}

fn debug_string(s: &str) {
    let w = crate::util::to_wide(s);
    unsafe {
        OutputDebugStringW(w.as_ptr());
    }
}

#[link(name = "kernel32")]
extern "system" {
    fn OutputDebugStringW(lpOutputString: *const u16);
}

/// 打日志的小语法糖，避免每处都写 format!。
#[macro_export]
macro_rules! logln {
    ($($arg:tt)*) => {
        $crate::log::line(&format!($($arg)*))
    };
}
