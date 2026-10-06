// hotkey.h —— 全局快捷键的解析、格式化、注册与降级。
// 单独成模块的原因：主程序要注册、设置面板要录制和校验、配置要读写，
// 三边都用同一套规则，散在各处必然写歪。
#pragma once

#include <windows.h>

#include <string>
#include <vector>

namespace sw {

// 动作枚举的顺序要和面板上的三个输入框顺序一致
enum class HotkeyAction { Toggle = 0, Settings = 1, Quit = 2, Count = 3 };

inline int HotkeyActionIndex(HotkeyAction a) { return static_cast<int>(a); }

struct HotkeySpec {
    bool valid = false;      // 空串也是 valid（表示「不要这个快捷键」）
    std::wstring text;       // 规范化的显示文本，例如 L"Ctrl+Alt+F9"
    UINT mods = 0;           // MOD_CONTROL / MOD_ALT / MOD_SHIFT / MOD_WIN 的组合
    UINT vk = 0;             // 主键虚拟键码
    std::wstring error;      // 解析失败时说明错在哪，直接进 stderr 日志
};

// 解析 "Ctrl+Alt+W" / "control+shift+f9" / "" 这样的写法。
// 大小写不敏感；修饰键没有也算合法（比如就是 "F9"）；空串 valid=true 但 vk=0。
// 解析失败时 valid=false 并把原因写进 error，**不做任何回退**，回退交给调用方决定。
HotkeySpec ParseHotkey(const std::wstring& text);

// 把 spec 变回显示文本（按 Ctrl+Alt+Shift+Win+主键 的固定顺序）
std::wstring FormatHotkey(const HotkeySpec& spec);

// 加一个 Shift 的降级版本；主键是 F1-F24 时也照样加（不要动主键本身）
HotkeySpec AddShift(const HotkeySpec& spec);

// MOD_* 里的 MOD_NOREPEAT 不进配置文件，只影响注册行为；这里补齐
inline UINT HotkeyRegisterMods(const HotkeySpec& s) { return s.mods | MOD_NOREPEAT; }

// 一个动作的实际注册结果
struct HotkeyBinding {
    UINT id = 0;                 // RegisterHotKey 用的 id
    bool registered = false;     // 最终有没有注册上
    bool disabled = false;       // 配置里写的是空串
    std::wstring requested;      // 用户最初要的组合（规范化后）
    std::wstring active;         // 真正生效的组合（降级后）；没注册上就是空
};

// 集中管理三个热键的注册：先按配置注册，被占用就退到加 Shift 的版本。
class HotkeyManager {
public:
    // 全部注销（退出、重新注册前都调它）
    void UnregisterAll(HWND hwnd);
    // 按配置重新注册；out 里返回每个动作的结果，失败原因写进 log
    void Apply(HWND hwnd, const std::wstring (&keys)[3], std::vector<HotkeyBinding>* out,
               std::wstring* log);
    // 录制期间整体关掉，否则用户按自己的热键会先把水印关掉
    void Enable(HWND hwnd, bool on);
    bool enabled() const { return enabled_; }
    const std::vector<HotkeyBinding>& bindings() const { return bindings_; }

private:
    void RegisterOne(HWND hwnd, int idx, const std::wstring& want, std::wstring* log);

    HWND hwnd_ = nullptr;
    bool enabled_ = false;
    std::vector<HotkeyBinding> bindings_;
};

// "Ctrl+Alt+W 开关水印 · Ctrl+Alt+S 设置 · Ctrl+Alt+Q 退出" 这样一行提示
std::wstring HotkeyHintLine(const std::vector<HotkeyBinding>& bindings);

// 某个动作在提示行里的短名字
const wchar_t* HotkeyActionHint(HotkeyAction a);

}  // namespace sw
