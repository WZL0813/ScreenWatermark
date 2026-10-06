#include "util.h"

// winsock2.h 必须在 windows.h 之前（util.h 里已经间接包含过 windows.h 了，MinGW 能容忍这个顺序）。
// 不包含它的话，iptypes.h 里的 GAA_FLAG_* 和 IP_ADAPTER_ADDRESSES 会被 _WINSOCK2API_ 挡在门外。
#include <winsock2.h>

#include <iphlpapi.h>
#include <shellapi.h>   // ShellExecuteW（「关于」打开仓库用）
#include <tlhelp32.h>

#include <cstdio>
#include <cstring>
#include <ctime>
#include <cstdarg>

namespace sw {

const wchar_t* const kAppName = L"ScreenWatermark";
const wchar_t* const kAppVersion = L"1.0.0";
const wchar_t* const kRepoUrl = L"https://github.com/WZL0813/ScreenWatermark";
const wchar_t* const kMutexName = L"Local\\ScreenWatermark_SingleInstance_9F2C";
const wchar_t* const kMsgWndClass = L"ScreenWatermarkMsgWnd";
const wchar_t* const kOverlayWndClass = L"ScreenWatermarkOverlayWnd";

std::string W2U8(const std::wstring& s) {
    if (s.empty()) return std::string();
    int n = ::WideCharToMultiByte(CP_UTF8, 0, s.c_str(), (int)s.size(), nullptr, 0, nullptr, nullptr);
    if (n <= 0) return std::string();
    std::string out((size_t)n, '\0');
    ::WideCharToMultiByte(CP_UTF8, 0, s.c_str(), (int)s.size(), &out[0], n, nullptr, nullptr);
    return out;
}

std::wstring U82W(const std::string& s) {
    if (s.empty()) return std::wstring();
    int n = ::MultiByteToWideChar(CP_UTF8, 0, s.c_str(), (int)s.size(), nullptr, 0);
    if (n <= 0) return std::wstring();
    std::wstring out((size_t)n, L'\0');
    ::MultiByteToWideChar(CP_UTF8, 0, s.c_str(), (int)s.size(), &out[0], n);
    return out;
}

std::wstring TrimW(const std::wstring& s) {
    size_t b = 0, e = s.size();
    auto isws = [](wchar_t c) {
        return c == L' ' || c == L'\t' || c == L'\r' || c == L'\n' || c == 0x3000;
    };
    while (b < e && isws(s[b])) ++b;
    while (e > b && isws(s[e - 1])) --e;
    return s.substr(b, e - b);
}

bool HasSubstrW(const std::wstring& hay, const std::wstring& needle) {
    if (needle.empty()) return true;
    if (hay.size() < needle.size()) return false;
    // 只对 ASCII 做大小写折叠，够用于关键字匹配；中文没有大小写问题
    for (size_t i = 0; i + needle.size() <= hay.size(); ++i) {
        size_t j = 0;
        for (; j < needle.size(); ++j) {
            wchar_t a = hay[i + j], b = needle[j];
            if (a >= L'A' && a <= L'Z') a = (wchar_t)(a - L'A' + L'a');
            if (b >= L'A' && b <= L'Z') b = (wchar_t)(b - L'A' + L'a');
            if (a != b) break;
        }
        if (j == needle.size()) return true;
    }
    return false;
}

std::wstring ModuleDir() {
    // 路径长度不确定，用循环放大缓冲；截断过的路径是错的，不如问清楚
    DWORD cap = MAX_PATH;
    for (;;) {
        std::wstring buf(cap, L'\0');
        DWORD n = ::GetModuleFileNameW(nullptr, &buf[0], cap);
        if (n == 0) return L".";
        if (n < cap - 1) {
            buf.resize(n);
            size_t p = buf.find_last_of(L"\\/");
            return (p == std::wstring::npos) ? std::wstring(L".") : buf.substr(0, p);
        }
        cap *= 2;
        if (cap > 32768) return L".";
    }
}

std::wstring JoinPath(const std::wstring& dir, const std::wstring& name) {
    if (dir.empty()) return name;
    if (dir.back() == L'\\' || dir.back() == L'/') return dir + name;
    return dir + L"\\" + name;
}

bool FileExists(const std::wstring& path) {
    DWORD a = ::GetFileAttributesW(path.c_str());
    return a != INVALID_FILE_ATTRIBUTES && !(a & FILE_ATTRIBUTE_DIRECTORY);
}

bool CanWriteDir(const std::wstring& dir) {
    std::wstring probe = JoinPath(dir, L".sw_write_probe");
    HANDLE h = ::CreateFileW(probe.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS,
                             FILE_ATTRIBUTE_TEMPORARY | FILE_FLAG_DELETE_ON_CLOSE, nullptr);
    if (h == INVALID_HANDLE_VALUE) return false;
    ::CloseHandle(h);
    return true;
}

static BOOL CALLBACK MonitorEnumProc(HMONITOR, HDC, LPRECT lprc, LPARAM data) {
    auto* out = reinterpret_cast<std::vector<MonitorRect>*>(data);
    MonitorRect m;
    m.rc = *lprc;
    out->push_back(m);
    return TRUE;
}

std::vector<MonitorRect> ListMonitors() {
    std::vector<MonitorRect> out;
    ::EnumDisplayMonitors(nullptr, nullptr, MonitorEnumProc, reinterpret_cast<LPARAM>(&out));
    if (out.empty()) {
        // 枚举失败也不能一个水印窗都没有，至少兜住主屏
        MonitorRect m;
        m.rc.left = 0;
        m.rc.top = 0;
        m.rc.right = ::GetSystemMetrics(SM_CXSCREEN);
        m.rc.bottom = ::GetSystemMetrics(SM_CYSCREEN);
        out.push_back(m);
    }
    return out;
}

RECT PrimaryMonitorRect() {
    POINT pt{0, 0};
    HMONITOR hm = ::MonitorFromPoint(pt, MONITOR_DEFAULTTOPRIMARY);
    MONITORINFO mi{};
    mi.cbSize = sizeof(mi);
    if (hm && ::GetMonitorInfoW(hm, &mi)) return mi.rcMonitor;
    RECT r{};
    r.right = ::GetSystemMetrics(SM_CXSCREEN);
    r.bottom = ::GetSystemMetrics(SM_CYSCREEN);
    return r;
}

void DebugLog(const wchar_t* fmt, ...) {
    // 默认什么都不做：诊断日志只在设了 SW_DEBUG=1 时开，正常用户不会看到多余文件
    static int enabled = -1;
    if (enabled < 0) {
        wchar_t v[8] = {0};
        DWORD n = ::GetEnvironmentVariableW(L"SW_DEBUG", v, 8);
        enabled = (n > 0 && v[0] == L'1') ? 1 : 0;
    }
    if (!enabled) return;

    wchar_t buf[1024];
    va_list ap;
    va_start(ap, fmt);
    _vsnwprintf(buf, 1023, fmt, ap);
    va_end(ap);
    buf[1023] = L'\0';

    std::wstring path = JoinPath(ModuleDir(), L"debug.log");
    FILE* f = _wfopen(path.c_str(), L"a, ccs=UTF-8");
    if (!f) return;
    fputws(buf, f);
    fputws(L"\r\n", f);
    fclose(f);
}

void LogWarn(const std::wstring& msg) {
    // stderr：只有从控制台启动时才看得到，但留着不吃亏
    std::wstring line = msg;
    if (line.empty() || line.back() != L'\n') line += L'\n';
    fputws(line.c_str(), stderr);
    // debug.log：程序是 GUI 子系统，stderr 常常是空的，所以同一句话再落一份文件
    DebugLog(L"警告: %s", msg.c_str());
}

void EnsureDpiAwareness() {
    // manifest 已经把进程标成 PerMonitorV2。这里只在「还没被别人定过」时兜底补一刀：
    // 一旦进程已经是 aware，再调 SetProcessDPIAware / SetProcessDpiAwareness 会失败，
    // 顺手调用反而可能把状态搞乱，所以先查当前状态，只在 UNAWARE 时才动手
    typedef HANDLE(WINAPI * PFN_GetThreadCtx)();
    typedef int(WINAPI * PFN_GetAwareness)(HANDLE);
    HMODULE user32 = ::GetModuleHandleW(L"user32.dll");
    int awareness = -1;  // 0=UNAWARE 1=SYSTEM 2=PER_MONITOR
    if (user32) {
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wcast-function-type"
        auto getctx = reinterpret_cast<PFN_GetThreadCtx>(
            ::GetProcAddress(user32, "GetThreadDpiAwarenessContext"));
        auto getaware = reinterpret_cast<PFN_GetAwareness>(
            ::GetProcAddress(user32, "GetAwarenessFromDpiAwarenessContext"));
#pragma GCC diagnostic pop
        if (getctx && getaware) awareness = getaware(getctx());
    }
    if (awareness == 0 || awareness == -1) {
        // 只处理「完全不知道 DPI」这一种情况，这是会导致坐标被虚拟化的那种
        typedef BOOL(WINAPI * PFN_SetCtx)(HANDLE);
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wcast-function-type"
        auto setctx = user32 ? reinterpret_cast<PFN_SetCtx>(
                                   ::GetProcAddress(user32, "SetProcessDpiAwarenessContext"))
                             : nullptr;
#pragma GCC diagnostic pop
        if (!setctx || !setctx((HANDLE)(INT_PTR)-4)) ::SetProcessDPIAware();
    }
    // 记一笔现状：这块出问题时日志是唯一线索
    DebugLog(L"DPI 感知 awareness=%d（0=不知 1=系统 2=每屏）", awareness);
}

UINT DpiForWindowSafe(HWND hwnd) {
    // 动态取地址而不是直接调用：老系统上没有这个符号，静态导入会让 exe 直接起不来
    typedef UINT(WINAPI * PFN_GetDpiForWindow)(HWND);
    static PFN_GetDpiForWindow pfn = nullptr;
    static bool tried = false;
    if (!tried) {
        tried = true;
        HMODULE u = ::GetModuleHandleW(L"user32.dll");
        if (u) {
            // GetProcAddress 给的是无类型函数指针，转成具体签名必然触发 -Wcast-function-type；
            // 这是 Win32 动态取址的固有形态，局部关掉这条警告而不是关掉整文件
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wcast-function-type"
            pfn = reinterpret_cast<PFN_GetDpiForWindow>(::GetProcAddress(u, "GetDpiForWindow"));
#pragma GCC diagnostic pop
        }
    }
    UINT dpi = 0;
    if (pfn && hwnd) dpi = pfn(hwnd);
    if (dpi == 0) {
        HDC dc = ::GetDC(nullptr);
        if (dc) {
            dpi = (UINT)::GetDeviceCaps(dc, LOGPIXELSY);
            ::ReleaseDC(nullptr, dc);
        }
    }
    return dpi ? dpi : 96;
}

static const wchar_t* kRunKey = L"Software\\Microsoft\\Windows\\CurrentVersion\\Run";

bool IsAutostartEnabled() {
    HKEY k = nullptr;
    if (::RegOpenKeyExW(HKEY_CURRENT_USER, kRunKey, 0, KEY_READ, &k) != ERROR_SUCCESS) return false;
    wchar_t buf[1024];
    DWORD cb = sizeof(buf);
    DWORD type = 0;
    LONG r = ::RegQueryValueExW(k, kAppName, nullptr, &type, reinterpret_cast<LPBYTE>(buf), &cb);
    ::RegCloseKey(k);
    return r == ERROR_SUCCESS && cb > 2;
}

bool SetAutostart(bool on) {
    HKEY k = nullptr;
    if (::RegCreateKeyExW(HKEY_CURRENT_USER, kRunKey, 0, nullptr, 0, KEY_SET_VALUE, nullptr, &k,
                          nullptr) != ERROR_SUCCESS)
        return false;
    bool ok = true;
    if (on) {
        // 路径必须带引号，否则 Program Files 里的空格会把命令行拆坏
        std::wstring quoted = L"\"" + JoinPath(ModuleDir(), L"ScreenWatermark.exe") + L"\"";
        LONG r = ::RegSetValueExW(k, kAppName, 0, REG_SZ,
                                  reinterpret_cast<const BYTE*>(quoted.c_str()),
                                  (DWORD)((quoted.size() + 1) * sizeof(wchar_t)));
        ok = (r == ERROR_SUCCESS);
    } else {
        LONG r = ::RegDeleteValueW(k, kAppName);
        ok = (r == ERROR_SUCCESS || r == ERROR_FILE_NOT_FOUND);
    }
    ::RegCloseKey(k);
    return ok;
}

int CountOtherInstances() {    // 只按「可执行文件名」比，不比全路径：用户完全可能把不同版本的 exe 拷到不同目录，
    // 那样比路径就漏了。四个实现的 exe 都叫 ScreenWatermark.exe，正好一网打尽。
    const DWORD me = ::GetCurrentProcessId();
    HANDLE snap = ::CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snap == INVALID_HANDLE_VALUE) return 0;
    PROCESSENTRY32W pe{};
    pe.dwSize = sizeof(pe);
    int others = 0;
    if (::Process32FirstW(snap, &pe)) {
        do {
            if (pe.th32ProcessID == me) continue;
            if (::lstrcmpiW(pe.szExeFile, L"ScreenWatermark.exe") == 0) ++others;
        } while (::Process32NextW(snap, &pe));
    }
    ::CloseHandle(snap);
    return others;
}

void OpenUrl(const std::wstring& url) {
    // 交给 shell 用默认浏览器打开。返回值 >32 才算成功，失败只记日志不弹窗 ——
    // 「关于」点不开不值得打断用户
    HINSTANCE r = ::ShellExecuteW(nullptr, L"open", url.c_str(), nullptr, nullptr, SW_SHOWNORMAL);
    if (reinterpret_cast<INT_PTR>(r) <= 32) DebugLog(L"打开链接失败(%p): %s", r, url.c_str());
}

std::wstring UserName() {
    wchar_t buf[256];
    DWORD n = 256;
    if (::GetUserNameW(buf, &n) && n > 1) return std::wstring(buf, n - 1);
    return std::wstring();
}

std::wstring HostName() {
    wchar_t buf[256];
    DWORD n = 256;
    if (::GetComputerNameW(buf, &n) && n > 0) return std::wstring(buf, n);
    return std::wstring();
}

std::wstring LocalIPv4() {
    // 用 GetAdaptersAddresses：不需要先初始化 winsock，也不会像 gethostname 那样返回 127.0.0.1
    ULONG size = 16 * 1024;
    std::vector<BYTE> buf(size);
    ULONG flags = GAA_FLAG_SKIP_ANYCAST | GAA_FLAG_SKIP_MULTICAST | GAA_FLAG_SKIP_DNS_SERVER;
    ULONG r = ::GetAdaptersAddresses(AF_INET, flags, nullptr,
                                     reinterpret_cast<IP_ADAPTER_ADDRESSES*>(buf.data()), &size);
    if (r == ERROR_BUFFER_OVERFLOW) {
        buf.resize(size);
        r = ::GetAdaptersAddresses(AF_INET, flags, nullptr,
                                   reinterpret_cast<IP_ADAPTER_ADDRESSES*>(buf.data()), &size);
    }
    if (r != NO_ERROR) return std::wstring();
    for (auto* a = reinterpret_cast<IP_ADAPTER_ADDRESSES*>(buf.data()); a; a = a->Next) {
        if (a->IfType == IF_TYPE_SOFTWARE_LOOPBACK) continue;
        if (a->OperStatus != IfOperStatusUp) continue;
        for (auto* ua = a->FirstUnicastAddress; ua; ua = ua->Next) {
            if (!ua->Address.lpSockaddr) continue;
            if (ua->Address.lpSockaddr->sa_family != AF_INET) continue;
            auto* sin = reinterpret_cast<sockaddr_in*>(ua->Address.lpSockaddr);
            BYTE* b = reinterpret_cast<BYTE*>(&sin->sin_addr);
            if (b[0] == 127) continue;
            wchar_t out[32];
            swprintf(out, 32, L"%u.%u.%u.%u", b[0], b[1], b[2], b[3]);
            return std::wstring(out);
        }
    }
    return std::wstring();
}

std::wstring FormatNow(const std::wstring& fmt) {
    std::wstring f = fmt.empty() ? std::wstring(L"%Y-%m-%d %H:%M") : fmt;
    std::time_t t = std::time(nullptr);
    std::tm tmv{};
    if (localtime_s(&tmv, &t) != 0) return std::wstring();
    wchar_t buf[512];
    size_t n = wcsftime(buf, 512, f.c_str(), &tmv);
    if (n == 0) return std::wstring();  // 格式串非法时返回空，调用方用原文兜底
    return std::wstring(buf, n);
}

static bool IsIdentChar(wchar_t c) {
    return (c >= L'a' && c <= L'z') || (c >= L'A' && c <= L'Z') || c == L'_';
}

std::wstring ExpandTemplate(const std::wstring& tmpl, const std::wstring& time_format) {
    std::wstring out;
    out.reserve(tmpl.size() + 32);
    for (size_t i = 0; i < tmpl.size();) {
        if (tmpl[i] != L'{') {
            // 顺手把 }} 折成 }：不在这里做的话就要多跑一趟
            if (tmpl[i] == L'}' && i + 1 < tmpl.size() && tmpl[i + 1] == L'}') {
                out.push_back(L'}');
                i += 2;
                continue;
            }
            out.push_back(tmpl[i++]);
            continue;
        }
        if (i + 1 < tmpl.size() && tmpl[i + 1] == L'{') {  // {{ -> 字面量 {
            out.push_back(L'{');
            i += 2;
            continue;
        }
        size_t close = tmpl.find(L'}', i + 1);
        if (close == std::wstring::npos) {  // 没闭合，原样吐出去，不要吞字符
            out.push_back(tmpl[i++]);
            continue;
        }
        std::wstring name = tmpl.substr(i + 1, close - i - 1);
        std::wstring lower;
        bool ident = !name.empty();
        for (wchar_t c : name) {
            if (!IsIdentChar(c)) ident = false;
            lower.push_back((c >= L'A' && c <= L'Z') ? (wchar_t)(c - L'A' + L'a') : c);
        }
        if (ident && lower == L"time") {
            std::wstring s = FormatNow(time_format);
            out += s.empty() ? std::wstring(L"{time}") : s;
        } else if (ident && lower == L"date") {
            out += FormatNow(L"%Y-%m-%d");
        } else if (ident && lower == L"user") {
            std::wstring s = UserName();
            out += s.empty() ? std::wstring(L"-") : s;
        } else if (ident && lower == L"host") {
            std::wstring s = HostName();
            out += s.empty() ? std::wstring(L"-") : s;
        } else if (ident && lower == L"ip") {
            out += LocalIPv4();  // 取不到就是空串，§3 就是这么定的
        } else {
            out += tmpl.substr(i, close - i + 1);  // 未知变量留原文，用户能看出写错了
        }
        i = close + 1;
    }
    return out;
}

bool TemplateHasTime(const std::wstring& tmpl) {
    for (size_t i = 0; i + 1 < tmpl.size(); ++i) {
        if (tmpl[i] != L'{') continue;
        if (tmpl[i + 1] == L'{') {
            ++i;
            continue;
        }
        size_t close = tmpl.find(L'}', i + 1);
        if (close == std::wstring::npos) continue;
        std::wstring name = tmpl.substr(i + 1, close - i - 1);
        for (auto& c : name)
            if (c >= L'A' && c <= L'Z') c = (wchar_t)(c - L'A' + L'a');
        if (name == L"time") return true;
        i = close;
    }
    return false;
}

}  // namespace sw
