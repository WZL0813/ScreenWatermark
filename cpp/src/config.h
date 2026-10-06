// config.h —— 配置结构与自研 JSON 读写。
// 字段名 / 类型 / 取值范围严格对齐 DESIGN.md §2，和 Python、C# 版共用同一份 config.json。
#pragma once

#include <string>
#include <utility>
#include <vector>

#include "hotkey.h"
#include "util.h"

namespace sw {

struct Config {
    std::wstring text = L"内部资料 请勿外传";
    std::wstring font_family = L"Microsoft YaHei";
    int font_size = 30;               // 8..400，磅
    bool bold = true;
    bool italic = false;
    std::wstring color = L"#808080";  // #RRGGBB，不带 alpha
    double opacity = 0.15;            // 0.01..1.0
    int angle = -30;                  // -90..90，逆时针为正
    int gap_x = 150;                  // 0..2000
    int gap_y = 120;                  // 0..2000
    // 每屏强制平铺的行列数；0 = 自动（按 gap_x / gap_y 算），老配置不受影响。
    // >0 时：cell_w = 屏宽 / cols、cell_h = 屏高 / rows，正好画 cols 列 rows 行
    int cols = 0;                     // 0..200
    int rows = 0;                     // 0..200
    double line_spacing = 1.2;        // 0.5..3.0
    bool enabled = true;
    bool click_through = true;
    bool templ = false;               // JSON 字段名是 template，C++ 关键字躲开
    std::wstring time_format = L"%Y-%m-%d %H:%M";
    int refresh_seconds = 30;         // 5..3600
    bool all_monitors = true;
    bool phase_offset = true;
    bool autostart = false;

    // §2 的 hotkeys 对象：三个动作各一个组合字符串。
    // 顺序固定为 开关水印 / 设置 / 退出，和 HotkeyAction 一致。
    // 空串表示「这个快捷键不要」，不是错误；写法不合法的项由 ClampConfig 退回默认值
    std::wstring hotkeys[3] = {L"Ctrl+Alt+W", L"Ctrl+Alt+S", L"Ctrl+Alt+Q"};

    // 非配置字段：坏文件提示，以及原样保留的未知字段（写回时带上，别吃掉别人新增的键）
    std::wstring load_warning;
    // 哪一项 hotkeys 写法不合法（空表示都正常），由 main 决定打不打印
    std::wstring hotkey_warning;
    std::vector<std::pair<std::wstring, std::wstring>> unknown_raw;
};

// exe 同目录优先；不可写则 %APPDATA%\ScreenWatermark\config.json（§2）
std::wstring ConfigPath();

void SetDefaults(Config& c);
// 解析失败不崩：备份成 config.bad.json，返回默认值并填 load_warning
Config LoadConfig(const std::wstring& path);
// UTF-8 无 BOM，缩进 2 空格，末尾换行
bool SaveConfig(const std::wstring& path, const Config& c);

std::wstring ExpandIfTemplate(const Config& c);
int ParseColorHex(const std::wstring& hex, int def_rgb);

// 逐项夹到合法区间，UI 里手输 1e9 也不能把渲染搞崩
void ClampConfig(Config& c);

}  // namespace sw
