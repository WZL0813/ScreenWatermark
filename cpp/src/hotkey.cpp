#include "hotkey.h"

#include <cstdio>

#include "util.h"

namespace sw {
namespace {

struct ModName {
    const wchar_t* name;  // 写进提示行的规范写法
    UINT flag;
};

// 顺序就是显示顺序：Ctrl+Alt+Shift+Win+主键
const ModName kMods[] = {
    {L"Ctrl", MOD_CONTROL},
    {L"Alt", MOD_ALT},
    {L"Shift", MOD_SHIFT},
    {L"Win", MOD_WIN},
};

std::wstring Lower(const std::wstring& s) {
    std::wstring o = s;
    for (auto& c : o)
        if (c >= L'A' && c <= L'Z') c = (wchar_t)(c - L'A' + L'a');
    return o;
}

// "Ctrl" / "Control" / "CTRL" 都能认
bool MatchModName(const std::wstring& lower, UINT& flag) {
    if (lower == L"ctrl" || lower == L"control") {
        flag = MOD_CONTROL;
        return true;
    }
    if (lower == L"alt") {
        flag = MOD_ALT;
        return true;
    }
    if (lower == L"shift") {
        flag = MOD_SHIFT;
        return true;
    }
    if (lower == L"win" || lower == L"windows") {
        flag = MOD_WIN;
        return true;
    }
    return false;
}

// 主键：A-Z、0-9、F1-F24。返回 0 表示认不出来。
UINT ParseMainKey(const std::wstring& part, std::wstring* canonical) {
    if (part.empty()) return 0;
    std::wstring up = part;
    for (auto& c : up)
        if (c >= L'a' && c <= L'z') c = (wchar_t)(c - L'a' + L'A');

    if (up.size() == 1) {
        wchar_t c = up[0];
        bool alpha = (c >= L'A' && c <= L'Z');
        bool digit = (c >= L'0' && c <= L'9');
        if (!alpha && !digit) return 0;
        if (canonical) *canonical = up;
        return (UINT)c;  // 字母和数字的虚拟键码正好等于大写 ASCII
    }
    // F1..F24：VK_F1 = 0x70 起
    if (up.size() >= 2 && up[0] == L'F') {
        int n = 0;
        for (size_t i = 1; i < up.size(); ++i) {
            if (up[i] < L'0' || up[i] > L'9') return 0;
            n = n * 10 + (up[i] - L'0');
            if (n > 999) return 0;
        }
        if (n < 1 || n > 24) return 0;
        if (canonical) *canonical = L"F" + std::to_wstring(n);
        return VK_F1 + (UINT)(n - 1);
    }
    return 0;
}

}  // namespace

HotkeySpec ParseHotkey(const std::wstring& raw) {
    HotkeySpec spec;
    spec.text = TrimW(raw);
    if (spec.text.empty()) {
        // 空串是「不要这个快捷键」，不是错误
        spec.valid = true;
        spec.mods = 0;
        spec.vk = 0;
        return spec;
    }

    std::vector<std::wstring> parts;
    size_t start = 0;
    while (start <= spec.text.size()) {
        size_t plus = spec.text.find(L'+', start);
        std::wstring piece = TrimW(spec.text.substr(
            start, (plus == std::wstring::npos ? spec.text.size() : plus) - start));
        if (!piece.empty()) parts.push_back(piece);
        if (plus == std::wstring::npos) break;
        start = plus + 1;
    }
    if (parts.empty()) {
        spec.error = L"只有加号，没有按键名";
        return spec;
    }

    UINT mods = 0;
    std::wstring canonical;
    bool has_main = false;
    for (size_t i = 0; i < parts.size(); ++i) {
        const std::wstring& p = parts[i];
        UINT flag = 0;
        if (MatchModName(Lower(p), flag)) {
            if (i + 1 == parts.size()) {
                spec.error = L"最后一段必须是主键，不能是修饰键 " + p;
                return spec;
            }
            mods |= flag;
            continue;
        }
        if (has_main) {
            spec.error = L"出现了不止一个主键：" + p;
            return spec;
        }
        UINT vk = ParseMainKey(p, &canonical);
        if (vk == 0) {
            spec.error = L"认不出的按键名 " + p + L"（主键只支持 A-Z / 0-9 / F1-F24）";
            return spec;
        }
        spec.vk = vk;
        has_main = true;
    }
    if (!has_main) {
        spec.error = L"没有主键";
        return spec;
    }
    spec.mods = mods;
    spec.valid = true;
    spec.text = FormatHotkey(spec);
    return spec;
}

std::wstring FormatHotkey(const HotkeySpec& spec) {
    if (spec.vk == 0) return std::wstring();
    std::wstring out;
    for (const auto& m : kMods) {
        if (spec.mods & m.flag) {
            out += m.name;
            out += L"+";
        }
    }
    // 主键名字：字母数字直接按 VK 还原，功能键换算回 F1-F24
    if (spec.vk >= VK_F1 && spec.vk <= VK_F24) {
        out += L"F" + std::to_wstring(spec.vk - VK_F1 + 1);
    } else if ((spec.vk >= 'A' && spec.vk <= 'Z') || (spec.vk >= '0' && spec.vk <= '9')) {
        out.push_back((wchar_t)spec.vk);
    } else {
        // 理论上到不了这里；真到了就吐个十六进制，别输出空字符串骗人
        wchar_t buf[16];
        swprintf(buf, 16, L"VK%02X", spec.vk);
        out += buf;
    }
    return out;
}

HotkeySpec AddShift(const HotkeySpec& spec) {
    HotkeySpec s = spec;
    if (!s.valid || s.vk == 0) return s;
    s.mods |= MOD_SHIFT;
    s.text = FormatHotkey(s);
    return s;
}

const wchar_t* HotkeyActionHint(HotkeyAction a) {
    switch (a) {
        case HotkeyAction::Toggle: return L"开关水印";
        case HotkeyAction::Settings: return L"设置";
        case HotkeyAction::Quit: return L"退出";
        default: return L"?";
    }
}

void HotkeyManager::UnregisterAll(HWND hwnd) {
    if (hwnd) {
        for (const auto& b : bindings_) {
            if (b.registered && b.id) ::UnregisterHotKey(hwnd, (int)b.id);
        }
    }
    bindings_.clear();
    enabled_ = false;
    hwnd_ = hwnd;
}

void HotkeyManager::RegisterOne(HWND hwnd, int idx, const std::wstring& want, std::wstring* log) {
    HotkeyBinding b;
    b.id = (UINT)(idx + 1);  // 动作 id 从 1 开始，0 留给「没绑定」
    b.requested = want;

    HotkeySpec spec = ParseHotkey(want);
    if (!spec.valid) {
        if (log) *log += L"快捷键第 " + std::to_wstring(idx + 1) + L" 项（" +
                          HotkeyActionHint((HotkeyAction)idx) + L"）写法不合法：\"" + want +
                          L"\"，" + spec.error + L"。该项本次不注册。\n";
        bindings_.push_back(b);
        return;
    }    if (spec.vk == 0) {
        b.disabled = true;
        bindings_.push_back(b);
        return;
    }

    ::SetLastError(0);
    if (::RegisterHotKey(hwnd, (int)b.id, HotkeyRegisterMods(spec), spec.vk)) {
        b.registered = true;
        b.active = spec.text;
        bindings_.push_back(b);
        return;
    }

    // 首选被占用（1409 = ERROR_HOTKEY_ALREADY_REGISTERED）→ 退一级加 Shift
    DWORD first_err = ::GetLastError();
    HotkeySpec alt = AddShift(spec);
    ::SetLastError(0);
    if (::RegisterHotKey(hwnd, (int)b.id, HotkeyRegisterMods(alt), alt.vk)) {
        b.registered = true;
        b.active = alt.text;
        // 降级必须说清楚：用户按配置里的组合没反应时，得知道真实生效的是哪个
        std::wstring m = L"快捷键 " + spec.text + L"（" + HotkeyActionHint((HotkeyAction)idx) +
                         L"）已被别的程序占用，自动改用 " + alt.text + L"。";
        if (log) *log += m + L"\n";
        LogWarn(m);
        bindings_.push_back(b);
        return;
    }
    DWORD second_err = ::GetLastError();
    {
        std::wstring m = L"快捷键 " + spec.text + L"（" + HotkeyActionHint((HotkeyAction)idx) +
                         L"）注册失败，加 Shift 的 " + alt.text + L" 也不行（错误码 " +
                         std::to_wstring(first_err) + L" / " + std::to_wstring(second_err) +
                         L"），该功能只能用托盘菜单。";
        if (log) *log += m + L"\n";
        LogWarn(m);
    }
    bindings_.push_back(b);
}

void HotkeyManager::Apply(HWND hwnd, const std::wstring (&keys)[3], std::vector<HotkeyBinding>* out,
                          std::wstring* log) {
    UnregisterAll(hwnd);
    for (int i = 0; i < 3; ++i) RegisterOne(hwnd, i, keys[i], log);
    enabled_ = true;
    if (out) *out = bindings_;
}

void HotkeyManager::Enable(HWND hwnd, bool on) {
    if (on == enabled_) return;
    if (!on) {
        // 录制期间：把已注册的全部撤掉，避免用户按到自己的热键先把水印关了
        for (const auto& b : bindings_) {
            if (b.registered && b.id) ::UnregisterHotKey(hwnd, (int)b.id);
        }
        enabled_ = false;
        return;
    }
    // 恢复：按 bindings_ 里记下的「实际生效组合」重新注册
    for (auto& b : bindings_) {
        if (!b.registered || b.active.empty()) continue;
        HotkeySpec spec = ParseHotkey(b.active);
        if (!spec.valid || spec.vk == 0) continue;
        if (!::RegisterHotKey(hwnd, (int)b.id, HotkeyRegisterMods(spec), spec.vk)) {
            DebugLog(L"恢复热键 %s 失败 err=%lu", b.active.c_str(), ::GetLastError());
            b.registered = false;
        }
    }
    enabled_ = true;
}

std::wstring HotkeyHintLine(const std::vector<HotkeyBinding>& bindings) {
    std::wstring line = L"快捷键：";
    bool first = true;
    for (int i = 0; i < (int)bindings.size(); ++i) {
        const HotkeyBinding& b = bindings[i];
        std::wstring part;
        if (b.disabled) {
            part = std::wstring(L"未设置（") + HotkeyActionHint((HotkeyAction)i) + L"）";
        } else if (b.registered) {
            part = b.active + L" " + HotkeyActionHint((HotkeyAction)i);
        } else if (!b.requested.empty()) {
            part = b.requested + L" 被占用（" + HotkeyActionHint((HotkeyAction)i) + L"）";
        } else {
            part = std::wstring(L"未设置（") + HotkeyActionHint((HotkeyAction)i) + L"）";
        }
        if (!first) line += L" · ";
        line += part;
        first = false;
    }
    return line;
}

}  // namespace sw
