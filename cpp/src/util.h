// util.h —— 跨模块公用的小工具：字符串、路径、DPI、显示器、模板变量、开机自启。
// 这里刻意不放和业务耦合的东西，避免 main / overlay / settings 互相 include 成环。
#pragma once

// 目标系统 Win10 1809+：不声明版本号的话，MinGW 头文件会把 GetAdaptersAddresses、
// GetDpiForWindow 这些新 API 藏起来（编译报 "has not been declared"）。
#ifndef WINVER
#define WINVER 0x0A00
#endif
#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0A00
#endif
// 瘦身版的 windows.h：不拉 winsock1，util.cpp 才能先包含 winsock2.h 拿全 iphlpapi 的声明
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif

#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif

#include <windows.h>

#include <string>
#include <vector>

namespace sw {

// 显示器物理矩形；PerMonitorV2 进程里 EnumDisplayMonitors 给的就是真实像素
struct MonitorRect {
    RECT rc{};
};

// 程序版本号：--version 和托盘提示都用它
extern const wchar_t* const kAppName;
extern const wchar_t* const kAppVersion;

// 单实例互斥体名、消息窗口类名、overlay 窗口类名
extern const wchar_t* const kMutexName;
extern const wchar_t* const kMsgWndClass;
extern const wchar_t* const kOverlayWndClass;

// 托盘图标的回调消息（tray.cpp 发，main.cpp 收），放这里免得两边各写一个常量写歪
const UINT kMsgTrayCallback = WM_APP + 1;

// ---- 字符串 ----
std::string W2U8(const std::wstring& s);
std::wstring U82W(const std::string& s);
std::wstring TrimW(const std::wstring& s);
bool HasSubstrW(const std::wstring& hay, const std::wstring& needle);  // 大小写不敏感

// 返回的路径没有尾部斜杠
std::wstring ModuleDir();
std::wstring JoinPath(const std::wstring& dir, const std::wstring& name);
bool FileExists(const std::wstring& path);
// 建一个随即删掉的探针文件来判断目录可写，决定 config.json 落在 exe 旁还是 %APPDATA%
bool CanWriteDir(const std::wstring& dir);

// ---- 调试 ----
// 设了 SW_DEBUG=1 才写日志（默认零开销、零垃圾文件）；出问题时用它定位
// 注意：它内部会跑 DPI 检查，所以只能在 EnsureDpiAwareness 之后调
void DebugLog(const wchar_t* fmt, ...);
// 用户必须知道的警告：同时写 stderr 和 debug.log。
// 为什么不能只写 stderr：本程序是 -mwindows 子系统，CRT 的 stderr 没关联任何
// 文件/管道（实测重定向也拿不到内容），只写 stderr 等于把消息扔了。
// debug.log 只在 SW_DEBUG=1 时写，所以消息文本里也写清「怎么打开日志」
void LogWarn(const std::wstring& msg);
// 尽早调一次，把进程标成 PerMonitorV2。manifest 里已经声明，这里是运行时兜底：
// 实测有环境不认 manifest 的资源，结果 EnumDisplayMonitors 返回被 DPI 虚拟化过的尺寸
// （屏幕 1440x960 却报 2520x1680），水印会被贴到窗外去
void EnsureDpiAwareness();

// ---- 系统信息 ----
// 显示器物理矩形；PerMonitorV2 进程里 EnumDisplayMonitors 给的就是真实像素
// 名字别叫 EnumMonitors：UNICODE 宏会把它展开成 EnumMonitorsW，最后链接找不到符号
std::vector<MonitorRect> ListMonitors();
RECT PrimaryMonitorRect();
UINT DpiForWindowSafe(HWND hwnd);  // 拿不到就退 96，绝不让字号算成 0
bool IsAutostartEnabled();
bool SetAutostart(bool on);

// ---- 模板变量 ----
std::wstring UserName();
std::wstring HostName();
std::wstring LocalIPv4();  // 取不到返回空串
// strftime 风格格式串；CRT 的 wcsftime 与 Python strftime 在常用指令上一致
std::wstring FormatNow(const std::wstring& strftime_fmt);
// 只认 §3 的六个变量：{time} {date} {user} {host} {ip} 以及 {{ }} 转义
std::wstring ExpandTemplate(const std::wstring& tmpl, const std::wstring& time_format);
// 模板里是否含随时间变化的变量（目前只有 {time}），决定要不要按 refresh_seconds 重绘
bool TemplateHasTime(const std::wstring& tmpl);

}  // namespace sw
