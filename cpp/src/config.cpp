#include "config.h"

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <utility>

namespace sw {
namespace {

// ---------------------------------------------------------------------------
// 极简 JSON：够读 config.json 就行，不打算做通用库。
// 对象用 vector<pair> 保序，这样写回配置时字段顺序稳定，和人手写的保持一致。
// ---------------------------------------------------------------------------

struct JValue {
    enum Type { Null, Bool, Num, Str, Arr, Obj } type = Null;
    bool b = false;
    double num = 0;
    std::wstring str;
    std::vector<JValue> arr;
    std::vector<std::pair<std::wstring, JValue>> obj;

    const JValue* find(const wchar_t* key) const {
        for (const auto& kv : obj)
            if (kv.first == key) return &kv.second;
        return nullptr;
    }
};

class JParser {
public:
    explicit JParser(const std::wstring& s) : s_(s) {}

    bool Parse(JValue& out) {
        SkipWs();
        if (!ParseValue(out)) return false;
        SkipWs();
        if (pos_ != s_.size()) {
            err_ = L"结尾有多余内容";
            return false;
        }
        return true;
    }

    const std::wstring& error() const { return err_; }

private:
    const std::wstring& s_;
    size_t pos_ = 0;
    std::wstring err_;

    void SkipWs() {
        while (pos_ < s_.size()) {
            wchar_t c = s_[pos_];
            if (c == L' ' || c == L'\t' || c == L'\r' || c == L'\n' || c == 0xFEFF)
                ++pos_;  // 有人手改配置存成了带 BOM，宽松吃掉
            else
                break;
        }
    }

    bool Fail(const wchar_t* msg) {
        wchar_t buf[160];
        swprintf(buf, 160, L"%s（位置 %zu）", msg, pos_);
        err_ = buf;
        return false;
    }

    bool ParseValue(JValue& v) {
        SkipWs();
        if (pos_ >= s_.size()) return Fail(L"内容意外结束");
        switch (s_[pos_]) {
            case L'{': return ParseObject(v);
            case L'[': return ParseArray(v);
            case L'"':
                v.type = JValue::Str;
                return ParseString(v.str);
            case L't':
                if (s_.compare(pos_, 4, L"true") == 0) {
                    v.type = JValue::Bool;
                    v.b = true;
                    pos_ += 4;
                    return true;
                }
                return Fail(L"非法字面量");
            case L'f':
                if (s_.compare(pos_, 5, L"false") == 0) {
                    v.type = JValue::Bool;
                    v.b = false;
                    pos_ += 5;
                    return true;
                }
                return Fail(L"非法字面量");
            case L'n':
                if (s_.compare(pos_, 4, L"null") == 0) {
                    v.type = JValue::Null;
                    pos_ += 4;
                    return true;
                }
                return Fail(L"非法字面量");
            default: return ParseNumber(v);
        }
    }

    bool ParseNumber(JValue& v) {
        size_t start = pos_;
        if (pos_ < s_.size() && (s_[pos_] == L'-' || s_[pos_] == L'+')) ++pos_;
        bool any = false;
        while (pos_ < s_.size()) {
            wchar_t c = s_[pos_];
            if ((c >= L'0' && c <= L'9') || c == L'.' || c == L'e' || c == L'E' || c == L'+' ||
                c == L'-') {
                if (c >= L'0' && c <= L'9') any = true;
                ++pos_;
            } else {
                break;
            }
        }
        if (!any) return Fail(L"数字格式错误");
        std::wstring tok = s_.substr(start, pos_ - start);
        wchar_t* end = nullptr;
        double d = wcstod(tok.c_str(), &end);
        if (end == tok.c_str()) return Fail(L"数字无法解析");
        if (std::isnan(d) || std::isinf(d)) d = 0;  // NaN/Inf 不是合法 JSON，归零了事
        v.type = JValue::Num;
        v.num = d;
        return true;
    }

    bool ParseString(std::wstring& out) {
        if (pos_ >= s_.size() || s_[pos_] != L'"') return Fail(L"缺少字符串起始引号");
        ++pos_;
        out.clear();
        while (pos_ < s_.size()) {
            wchar_t c = s_[pos_++];
            if (c == L'"') return true;
            if (c != L'\\') {
                out.push_back(c);
                continue;
            }
            if (pos_ >= s_.size()) return Fail(L"转义序列不完整");
            wchar_t e = s_[pos_++];
            switch (e) {
                case L'"': out.push_back(L'"'); break;
                case L'\\': out.push_back(L'\\'); break;
                case L'/': out.push_back(L'/'); break;
                case L'b': out.push_back(L'\b'); break;
                case L'f': out.push_back(L'\f'); break;
                case L'n': out.push_back(L'\n'); break;
                case L'r': out.push_back(L'\r'); break;
                case L't': out.push_back(L'\t'); break;
                case L'u': {
                    unsigned cp = 0;
                    if (!ReadHex4(cp)) return false;
                    if (cp >= 0xD800 && cp <= 0xDBFF) {
                        // UTF-16 代理对要合成一个码点，不然 emoji 会变成两个乱码
                        if (pos_ + 1 < s_.size() && s_[pos_] == L'\\' && s_[pos_ + 1] == L'u') {
                            size_t save = pos_;
                            pos_ += 2;
                            unsigned lo = 0;
                            if (ReadHex4(lo) && lo >= 0xDC00 && lo <= 0xDFFF)
                                cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00);
                            else
                                pos_ = save;  // 不成对就按孤立代理处理，别把后面的内容吞了
                        }
                    }
                    AppendUtf16(out, cp);
                    break;
                }
                default: return Fail(L"未知转义字符");
            }
        }
        return Fail(L"字符串没有闭合");
    }

    bool ReadHex4(unsigned& out) {
        if (pos_ + 4 > s_.size()) return Fail(L"\\u 后面不足 4 位");
        out = 0;
        for (int i = 0; i < 4; ++i) {
            wchar_t c = s_[pos_++];
            out <<= 4;
            if (c >= L'0' && c <= L'9') out |= (unsigned)(c - L'0');
            else if (c >= L'a' && c <= L'f') out |= (unsigned)(c - L'a' + 10);
            else if (c >= L'A' && c <= L'F') out |= (unsigned)(c - L'A' + 10);
            else return Fail(L"\\u 里出现非十六进制字符");
        }
        return true;
    }

    static void AppendUtf16(std::wstring& out, unsigned cp) {
        if (cp <= 0xFFFF) {
            out.push_back((wchar_t)cp);
        } else {
            cp -= 0x10000;
            out.push_back((wchar_t)(0xD800 + (cp >> 10)));
            out.push_back((wchar_t)(0xDC00 + (cp & 0x3FF)));
        }
    }

    bool ParseArray(JValue& v) {
        v.type = JValue::Arr;
        ++pos_;
        SkipWs();
        if (pos_ < s_.size() && s_[pos_] == L']') {
            ++pos_;
            return true;
        }
        for (;;) {
            JValue item;
            if (!ParseValue(item)) return false;
            v.arr.push_back(std::move(item));
            SkipWs();
            if (pos_ >= s_.size()) return Fail(L"数组没有闭合");
            if (s_[pos_] == L',') {
                ++pos_;
                continue;
            }
            if (s_[pos_] == L']') {
                ++pos_;
                return true;
            }
            return Fail(L"数组里期望 , 或 ]");
        }
    }

    bool ParseObject(JValue& v) {
        v.type = JValue::Obj;
        ++pos_;
        SkipWs();
        if (pos_ < s_.size() && s_[pos_] == L'}') {
            ++pos_;
            return true;
        }
        for (;;) {
            SkipWs();
            std::wstring key;
            if (!ParseString(key)) return false;
            SkipWs();
            if (pos_ >= s_.size() || s_[pos_] != L':') return Fail(L"键后面缺少冒号");
            ++pos_;
            JValue val;
            if (!ParseValue(val)) return false;
            v.obj.emplace_back(std::move(key), std::move(val));
            SkipWs();
            if (pos_ >= s_.size()) return Fail(L"对象没有闭合");
            if (s_[pos_] == L',') {
                ++pos_;
                continue;
            }
            if (s_[pos_] == L'}') {
                ++pos_;
                return true;
            }
            return Fail(L"对象里期望 , 或 }");
        }
    }
};

std::wstring EscapeJson(const std::wstring& in) {
    std::wstring out;
    out.reserve(in.size() + 8);
    for (wchar_t c : in) {
        switch (c) {
            case L'"': out += L"\\\""; break;
            case L'\\': out += L"\\\\"; break;
            case L'\n': out += L"\\n"; break;
            case L'\r': out += L"\\r"; break;
            case L'\t': out += L"\\t"; break;
            case L'\b': out += L"\\b"; break;
            case L'\f': out += L"\\f"; break;
            default:
                if (c < 0x20) {  // 控制字符必须转义，否则写出来的 JSON 别人读不了
                    wchar_t buf[8];
                    swprintf(buf, 8, L"\\u%04X", (unsigned)c);
                    out += buf;
                } else {
                    out.push_back(c);  // 中文原样输出，配置文件保持人可读
                }
        }
    }
    return out;
}

std::wstring NumToStr(double d) {
    // 整数值不写小数点，和 Python json.dump 的输出长得一样，便于三份配置互相 diff
    if (std::fabs(d - std::floor(d + 0.5)) < 1e-9 && std::fabs(d) < 1e15)
        return std::to_wstring((long long)std::floor(d + 0.5));
    wchar_t buf[64];
    swprintf(buf, 64, L"%.4f", d);
    std::wstring s(buf);
    while (!s.empty() && s.back() == L'0') s.pop_back();
    if (!s.empty() && s.back() == L'.') s.pop_back();
    return s;
}

int GetInt(const JValue& o, const wchar_t* key, int def) {
    const JValue* v = o.find(key);
    if (!v) return def;
    if (v->type == JValue::Num) return (int)std::lround(v->num);
    if (v->type == JValue::Bool) return v->b ? 1 : 0;
    return def;
}

double GetDouble(const JValue& o, const wchar_t* key, double def) {
    const JValue* v = o.find(key);
    if (!v) return def;
    if (v->type == JValue::Num) return v->num;
    return def;
}

bool GetBool(const JValue& o, const wchar_t* key, bool def) {
    const JValue* v = o.find(key);
    if (!v) return def;
    if (v->type == JValue::Bool) return v->b;
    if (v->type == JValue::Num) return v->num != 0;
    return def;
}

std::wstring GetStr(const JValue& o, const wchar_t* key, const std::wstring& def) {
    const JValue* v = o.find(key);
    if (!v) return def;
    if (v->type == JValue::Str) return v->str;
    return def;
}

// 未知字段重新序列化成紧凑 JSON 存起来，写回时原样带上
std::wstring SerializeValue(const JValue& v) {
    switch (v.type) {
        case JValue::Null: return L"null";
        case JValue::Bool: return v.b ? L"true" : L"false";
        case JValue::Num: return NumToStr(v.num);
        case JValue::Str: return L"\"" + EscapeJson(v.str) + L"\"";
        case JValue::Arr: {
            std::wstring s = L"[";
            for (size_t i = 0; i < v.arr.size(); ++i) {
                if (i) s += L", ";
                s += SerializeValue(v.arr[i]);
            }
            return s + L"]";
        }
        case JValue::Obj: {
            std::wstring s = L"{";
            for (size_t i = 0; i < v.obj.size(); ++i) {
                if (i) s += L", ";
                s += L"\"" + EscapeJson(v.obj[i].first) + L"\": " + SerializeValue(v.obj[i].second);
            }
            return s + L"}";
        }
    }
    return L"null";
}

const wchar_t* const kKnownKeys[] = {
    L"text",       L"font_family",     L"font_size",  L"bold",        L"italic",
    L"color",      L"opacity",         L"angle",      L"gap_x",       L"gap_y",
    L"line_spacing", L"enabled",       L"click_through", L"template", L"time_format",
    L"refresh_seconds", L"all_monitors", L"phase_offset", L"autostart", L"hotkeys"};

// hotkeys 对象里的三个键名，顺序必须和 Config::hotkeys / HotkeyAction 一致
const wchar_t* const kHotkeyKeys[3] = {L"toggle", L"settings", L"quit"};

bool IsKnownKey(const std::wstring& k) {
    for (const wchar_t* s : kKnownKeys)
        if (k == s) return true;
    return false;
}

// 单个热键字段的读取：缺字段 → 用当前值（默认值）；
// 写法不合法 → 只让这一项退回默认值，并把「哪一项、原文、原因」记进 warning，绝不整份回退
std::wstring ReadHotkey(const JValue& hk, const wchar_t* key, const std::wstring& def,
                        std::wstring* warning) {
    const JValue* v = hk.find(key);
    if (!v || v->type != JValue::Str) return def;
    const std::wstring& raw = v->str;
    HotkeySpec spec = ParseHotkey(raw);
    if (!spec.valid) {
        if (warning) {
            *warning += L"config.json 的 hotkeys." + std::wstring(key) + L" = \"" + raw +
                        L"\" 写法不合法（" + spec.error + L"），该项已退回默认值 " + def + L"。";
        }
        return def;
    }
    // 合法的空串保留成空串：那是「不要这个快捷键」
    return spec.text;
}

}  // namespace

void SetDefaults(Config& c) {
    Config d;
    d.load_warning = c.load_warning;
    d.unknown_raw = c.unknown_raw;
    c = d;
}

void ClampConfig(Config& c) {
    if (c.font_size < 8) c.font_size = 8;
    if (c.font_size > 400) c.font_size = 400;
    if (c.opacity < 0.01) c.opacity = 0.01;
    if (c.opacity > 1.0) c.opacity = 1.0;
    if (c.angle < -90) c.angle = -90;
    if (c.angle > 90) c.angle = 90;
    if (c.gap_x < 0) c.gap_x = 0;
    if (c.gap_x > 2000) c.gap_x = 2000;
    if (c.gap_y < 0) c.gap_y = 0;
    if (c.gap_y > 2000) c.gap_y = 2000;
    if (c.line_spacing < 0.5) c.line_spacing = 0.5;
    if (c.line_spacing > 3.0) c.line_spacing = 3.0;
    if (c.refresh_seconds < 5) c.refresh_seconds = 5;
    if (c.refresh_seconds > 3600) c.refresh_seconds = 3600;
    if (c.font_family.empty()) c.font_family = L"Microsoft YaHei";
    if (c.time_format.empty()) c.time_format = L"%Y-%m-%d %H:%M";
    if (c.color.size() != 7 || c.color[0] != L'#') c.color = L"#808080";

    // 热键：面板手上可能塞进半截字符串，这里统一规范化；真不合法就退回该项默认值
    const std::wstring defs[3] = {L"Ctrl+Alt+W", L"Ctrl+Alt+S", L"Ctrl+Alt+Q"};
    for (int i = 0; i < 3; ++i) {
        HotkeySpec spec = ParseHotkey(c.hotkeys[i]);
        if (spec.valid)
            c.hotkeys[i] = spec.text;  // 空串会被规范成空串，保持「不要这个键」
        else
            c.hotkeys[i] = defs[i];
    }
}

std::wstring ConfigPath() {
    std::wstring dir = ModuleDir();
    if (CanWriteDir(dir)) return JoinPath(dir, L"config.json");
    // 装在 Program Files 这类只读位置时落到 %APPDATA%，三个实现仍然共用同一路径
    wchar_t appdata[MAX_PATH] = {0};
    DWORD n = ::GetEnvironmentVariableW(L"APPDATA", appdata, MAX_PATH);
    std::wstring base = (n > 0 && n < MAX_PATH) ? std::wstring(appdata, n) : dir;
    std::wstring sub = JoinPath(base, L"ScreenWatermark");
    ::CreateDirectoryW(sub.c_str(), nullptr);
    return JoinPath(sub, L"config.json");
}

Config LoadConfig(const std::wstring& path) {
    Config c;  // 先摆默认值，缺字段靠它补齐（§2 要求）
    SetDefaults(c);
    if (!FileExists(path)) return c;

    HANDLE h = ::CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING,
                             FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h == INVALID_HANDLE_VALUE) {
        c.load_warning = L"配置文件无法打开，已使用默认值";
        return c;
    }
    LARGE_INTEGER sz{};
    ::GetFileSizeEx(h, &sz);
    std::string raw;
    if (sz.QuadPart > 0 && sz.QuadPart < 4 * 1024 * 1024) {
        raw.resize((size_t)sz.QuadPart);
        DWORD got = 0;
        ::ReadFile(h, &raw[0], (DWORD)raw.size(), &got, nullptr);
        raw.resize(got);
    }
    ::CloseHandle(h);

    if (raw.size() >= 3 && (unsigned char)raw[0] == 0xEF && (unsigned char)raw[1] == 0xBB &&
        (unsigned char)raw[2] == 0xBF)
        raw.erase(0, 3);  // 别人手改存成了带 BOM，帮它去掉再解析

    // 必须先把 UTF-8 转成具名的 std::wstring 再交给 JParser：
    // JParser 内部存的是引用，若直接传 U82W(raw) 的临时对象，它会在这个完整表达式结束时析构，
    // 解析器随后读到的是悬空内存（实测表现为「位置 0、错误信息乱码、永远解析失败」）
    std::wstring text = U82W(raw);
    JValue root;
    JParser p(text);
    if (!p.Parse(root) || root.type != JValue::Obj) {
        std::wstring bad = path;
        size_t dot = bad.find_last_of(L'.');
        size_t slash = bad.find_last_of(L"\\/");
        if (dot != std::wstring::npos && (slash == std::wstring::npos || dot > slash))
            bad = bad.substr(0, dot) + L".bad.json";
        else
            bad += L".bad.json";
        ::CopyFileW(path.c_str(), bad.c_str(), FALSE);
        c.load_warning = L"config.json 解析失败，已备份为 config.bad.json，本次使用默认值";
        DebugLog(L"LoadConfig 解析失败: %s", p.error().c_str());
        return c;
    }

    const JValue& o = root;
    c.text = GetStr(o, L"text", c.text);
    c.font_family = GetStr(o, L"font_family", c.font_family);
    c.font_size = GetInt(o, L"font_size", c.font_size);
    c.bold = GetBool(o, L"bold", c.bold);
    c.italic = GetBool(o, L"italic", c.italic);
    c.color = GetStr(o, L"color", c.color);
    c.opacity = GetDouble(o, L"opacity", c.opacity);
    c.angle = GetInt(o, L"angle", c.angle);
    c.gap_x = GetInt(o, L"gap_x", c.gap_x);
    c.gap_y = GetInt(o, L"gap_y", c.gap_y);
    c.line_spacing = GetDouble(o, L"line_spacing", c.line_spacing);
    c.enabled = GetBool(o, L"enabled", c.enabled);
    c.click_through = GetBool(o, L"click_through", c.click_through);
    c.templ = GetBool(o, L"template", c.templ);
    c.time_format = GetStr(o, L"time_format", c.time_format);
    c.refresh_seconds = GetInt(o, L"refresh_seconds", c.refresh_seconds);
    c.all_monitors = GetBool(o, L"all_monitors", c.all_monitors);
    c.phase_offset = GetBool(o, L"phase_offset", c.phase_offset);
    c.autostart = GetBool(o, L"autostart", c.autostart);

    // hotkeys：整段没有就三个默认值全上（老配置必须照常工作）；
    // 有但类型不对，或者里面某一项写歪了，都只影响那一项
    c.hotkey_warning.clear();
    if (const JValue* hk = o.find(L"hotkeys")) {
        if (hk->type != JValue::Obj) {
            c.hotkey_warning = L"config.json 的 hotkeys 不是对象，三个快捷键都退回默认值。";
        } else {
            for (int i = 0; i < 3; ++i)
                c.hotkeys[i] = ReadHotkey(*hk, kHotkeyKeys[i], c.hotkeys[i], &c.hotkey_warning);
        }
    }

    for (const auto& kv : o.obj)
        if (!IsKnownKey(kv.first)) c.unknown_raw.emplace_back(kv.first, SerializeValue(kv.second));

    ClampConfig(c);
    return c;
}

bool SaveConfig(const std::wstring& path, const Config& c) {
    Config cc = c;
    ClampConfig(cc);
    std::wstring s = L"{\n";
    auto kv = [&s](const wchar_t* k, const std::wstring& v, bool last = false) {
        s += L"  \"";
        s += k;
        s += L"\": ";
        s += v;
        s += last ? L"\n" : L",\n";
    };
    kv(L"text", L"\"" + EscapeJson(cc.text) + L"\"");
    kv(L"font_family", L"\"" + EscapeJson(cc.font_family) + L"\"");
    kv(L"font_size", NumToStr(cc.font_size));
    kv(L"bold", cc.bold ? L"true" : L"false");
    kv(L"italic", cc.italic ? L"true" : L"false");
    kv(L"color", L"\"" + EscapeJson(cc.color) + L"\"");
    kv(L"opacity", NumToStr(cc.opacity));
    kv(L"angle", NumToStr(cc.angle));
    kv(L"gap_x", NumToStr(cc.gap_x));
    kv(L"gap_y", NumToStr(cc.gap_y));
    kv(L"line_spacing", NumToStr(cc.line_spacing));
    kv(L"enabled", cc.enabled ? L"true" : L"false");
    kv(L"click_through", cc.click_through ? L"true" : L"false");
    kv(L"template", cc.templ ? L"true" : L"false");
    kv(L"time_format", L"\"" + EscapeJson(cc.time_format) + L"\"");
    kv(L"refresh_seconds", NumToStr(cc.refresh_seconds));
    kv(L"all_monitors", cc.all_monitors ? L"true" : L"false");
    kv(L"phase_offset", cc.phase_offset ? L"true" : L"false");
    kv(L"autostart", cc.autostart ? L"true" : L"false");
    // hotkeys 放在 autostart 后面、未知字段前面。整段由我们自己写，不参与 unknown_raw，
    // 所以「未知字段保留」的逻辑不受影响
    s += L"  \"hotkeys\": {\n";
    for (int i = 0; i < 3; ++i) {
        s += L"    \"";
        s += kHotkeyKeys[i];
        s += L"\": \"";
        s += EscapeJson(cc.hotkeys[i]);
        s += (i + 1 < 3) ? L"\",\n" : L"\"\n";
    }
    s += L"  }";
    s += cc.unknown_raw.empty() ? L"\n" : L",\n";
    for (size_t i = 0; i < cc.unknown_raw.size(); ++i) {
        s += L"  \"" + EscapeJson(cc.unknown_raw[i].first) + L"\": " + cc.unknown_raw[i].second;
        s += (i + 1 == cc.unknown_raw.size()) ? L"\n" : L",\n";
    }
    s += L"}\n";

    std::string utf8 = W2U8(s);
    HANDLE h = ::CreateFileW(path.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS,
                             FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h == INVALID_HANDLE_VALUE) return false;
    DWORD wrote = 0;
    BOOL ok = ::WriteFile(h, utf8.data(), (DWORD)utf8.size(), &wrote, nullptr);
    ::CloseHandle(h);
    return ok && wrote == utf8.size();
}

std::wstring ExpandIfTemplate(const Config& c) {
    if (c.templ) return ExpandTemplate(c.text, c.time_format);
    // 模板关掉时把 {{ }} 折回 {}，否则用户会看到双花括号
    std::wstring out;
    for (size_t i = 0; i < c.text.size();) {
        if (i + 1 < c.text.size() && c.text[i] == L'{' && c.text[i + 1] == L'{') {
            out.push_back(L'{');
            i += 2;
        } else if (i + 1 < c.text.size() && c.text[i] == L'}' && c.text[i + 1] == L'}') {
            out.push_back(L'}');
            i += 2;
        } else {
            out.push_back(c.text[i++]);
        }
    }
    return out;
}

int ParseColorHex(const std::wstring& hex, int def_rgb) {
    if (hex.size() != 7 || hex[0] != L'#') return def_rgb;
    int v = 0;
    for (int i = 1; i < 7; ++i) {
        wchar_t c = hex[i];
        int d;
        if (c >= L'0' && c <= L'9') d = c - L'0';
        else if (c >= L'a' && c <= L'f') d = c - L'a' + 10;
        else if (c >= L'A' && c <= L'F') d = c - L'A' + 10;
        else return def_rgb;
        v = (v << 4) | d;
    }
    return v;
}

}  // namespace sw
