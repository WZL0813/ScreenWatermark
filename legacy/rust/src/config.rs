// 配置结构体 + 手写 JSON 读写 + 写回时保留未知字段。
// 为什么不用 serde：规格要零第三方 crate，而且这里只需要一个足够小的解析器。

use crate::util::{clamp_f, clamp_i, color_to_hex, parse_color};
use std::collections::BTreeMap;
use std::path::Path;

/// 与 DESIGN.md §2 的字段一一对应。字段名即 JSON 键名。
#[derive(Clone, Debug, PartialEq)]
pub struct Config {
    pub text: String,
    pub font_family: String,
    pub font_size: i32,
    pub bold: bool,
    pub italic: bool,
    pub color: String,
    pub opacity: f64,
    pub angle: i32,
    pub gap_x: i32,
    pub gap_y: i32,
    pub line_spacing: f64,
    pub enabled: bool,
    pub click_through: bool,
    pub template: bool,
    pub time_format: String,
    pub refresh_seconds: i32,
    pub all_monitors: bool,
    pub phase_offset: bool,
    pub autostart: bool,
}

impl Default for Config {
    fn default() -> Self {
        Config {
            text: "内部资料 请勿外传".to_string(),
            font_family: "Microsoft YaHei".to_string(),
            font_size: 30,
            bold: true,
            italic: false,
            color: "#808080".to_string(),
            opacity: 0.15,
            angle: -30,
            gap_x: 150,
            gap_y: 120,
            line_spacing: 1.2,
            enabled: true,
            click_through: true,
            template: false,
            time_format: "%Y-%m-%d %H:%M".to_string(),
            refresh_seconds: 30,
            all_monitors: true,
            phase_offset: true,
            autostart: false,
        }
    }
}

impl Config {
    /// 把越界值拉回 §2 的范围。UI 和配置文件两条路都要过这一关。
    pub fn normalized(mut self) -> Config {
        self.font_size = clamp_i(self.font_size as i64, 8, 400) as i32;
        self.opacity = clamp_f(self.opacity, 0.01, 1.0);
        self.angle = clamp_i(self.angle as i64, -90, 90) as i32;
        self.gap_x = clamp_i(self.gap_x as i64, 0, 2000) as i32;
        self.gap_y = clamp_i(self.gap_y as i64, 0, 2000) as i32;
        self.line_spacing = clamp_f(self.line_spacing, 0.5, 3.0);
        self.refresh_seconds = clamp_i(self.refresh_seconds as i64, 5, 3600) as i32;
        if self.time_format.trim().is_empty() {
            self.time_format = "%Y-%m-%d %H:%M".to_string();
        }
        if self.color.trim().is_empty() {
            self.color = "#808080".to_string();
        } else {
            // 统一成 #RRGGBB，避免各实现写出不同写法。
            self.color = color_to_hex(parse_color(&self.color));
        }
        if self.font_family.trim().is_empty() {
            self.font_family = "Microsoft YaHei".to_string();
        }
        self
    }

    /// 解析成 (配置, 未知字段的原始 JSON 文本)。
    /// 未知字段存成"键 -> 原样 JSON 片段"，写回时按字母序拼回去，
    /// 这样别的实现加的字段不会被我们吃掉。
    pub fn parse_with_extras(s: &str) -> Option<(Config, BTreeMap<String, String>)> {
        let v = parse_json(s)?;
        let obj = match v {
            Json::Obj(o) => o,
            _ => return None,
        };
        let mut c = Config::default();
        let mut extras: BTreeMap<String, String> = BTreeMap::new();
        for (k, val) in obj.iter() {
            match k.as_str() {
                "text" => c.text = val.as_str().unwrap_or(c.text.clone()),
                "font_family" => c.font_family = val.as_str().unwrap_or(c.font_family.clone()),
                "font_size" => c.font_size = val.as_int().unwrap_or(c.font_size),
                "bold" => c.bold = val.as_bool().unwrap_or(c.bold),
                "italic" => c.italic = val.as_bool().unwrap_or(c.italic),
                "color" => c.color = val.as_str().unwrap_or(c.color.clone()),
                "opacity" => c.opacity = val.as_float().unwrap_or(c.opacity),
                "angle" => c.angle = val.as_int().unwrap_or(c.angle),
                "gap_x" => c.gap_x = val.as_int().unwrap_or(c.gap_x),
                "gap_y" => c.gap_y = val.as_int().unwrap_or(c.gap_y),
                "line_spacing" => c.line_spacing = val.as_float().unwrap_or(c.line_spacing),
                "enabled" => c.enabled = val.as_bool().unwrap_or(c.enabled),
                "click_through" => c.click_through = val.as_bool().unwrap_or(c.click_through),
                "template" => c.template = val.as_bool().unwrap_or(c.template),
                "time_format" => c.time_format = val.as_str().unwrap_or(c.time_format.clone()),
                "refresh_seconds" => {
                    c.refresh_seconds = val.as_int().unwrap_or(c.refresh_seconds)
                }
                "all_monitors" => c.all_monitors = val.as_bool().unwrap_or(c.all_monitors),
                "phase_offset" => c.phase_offset = val.as_bool().unwrap_or(c.phase_offset),
                "autostart" => c.autostart = val.as_bool().unwrap_or(c.autostart),
                _ => {
                    extras.insert(k.clone(), val.to_json());
                }
            }
        }
        Some((c.normalized(), extras))
    }

    /// 序列化成 §2 顺序的 JSON 文本（末尾带换行，方便人看）。
    pub fn to_json(&self, extras: &BTreeMap<String, String>) -> String {
        let mut out = String::with_capacity(768);
        out.push_str("{\n");
        let mut lines: Vec<String> = Vec::with_capacity(20 + extras.len());
        lines.push(format!("  \"text\": {}", json_string(&self.text)));
        lines.push(format!(
            "  \"font_family\": {}",
            json_string(&self.font_family)
        ));
        lines.push(format!("  \"font_size\": {}", self.font_size));
        lines.push(format!("  \"bold\": {}", json_bool(self.bold)));
        lines.push(format!("  \"italic\": {}", json_bool(self.italic)));
        lines.push(format!("  \"color\": {}", json_string(&self.color)));
        lines.push(format!("  \"opacity\": {}", json_num(self.opacity)));
        lines.push(format!("  \"angle\": {}", self.angle));
        lines.push(format!("  \"gap_x\": {}", self.gap_x));
        lines.push(format!("  \"gap_y\": {}", self.gap_y));
        lines.push(format!("  \"line_spacing\": {}", json_num(self.line_spacing)));
        lines.push(format!("  \"enabled\": {}", json_bool(self.enabled)));
        lines.push(format!(
            "  \"click_through\": {}",
            json_bool(self.click_through)
        ));
        lines.push(format!("  \"template\": {}", json_bool(self.template)));
        lines.push(format!(
            "  \"time_format\": {}",
            json_string(&self.time_format)
        ));
        lines.push(format!("  \"refresh_seconds\": {}", self.refresh_seconds));
        lines.push(format!(
            "  \"all_monitors\": {}",
            json_bool(self.all_monitors)
        ));
        lines.push(format!(
            "  \"phase_offset\": {}",
            json_bool(self.phase_offset)
        ));
        lines.push(format!("  \"autostart\": {}", json_bool(self.autostart)));
        // 未知字段（别的实现写进来的）挂到后面，一个都不丢。
        for (k, v) in extras.iter() {
            lines.push(format!("  {}: {}", json_string(k), v));
        }
        for (i, l) in lines.iter().enumerate() {
            out.push_str(l);
            if i + 1 < lines.len() {
                out.push(',');
            }
            out.push('\n');
        }
        out.push_str("}\n");
        out
    }

    /// 写回磁盘：UTF-8 无 BOM（std::fs::write 不会加 BOM）。
    /// 先写临时文件再改名，避免写一半断电把配置弄成半个 JSON。
    pub fn save(&self, extras: &BTreeMap<String, String>, path: &Path) -> std::io::Result<()> {
        let text = self.to_json(extras);
        if let Some(parent) = path.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        let tmp = path.with_extension("json.tmp");
        std::fs::write(&tmp, text.as_bytes())?;
        match std::fs::rename(&tmp, path) {
            Ok(_) => Ok(()),
            Err(e) => {
                let _ = std::fs::remove_file(&tmp);
                Err(e)
            }
        }
    }
}

fn json_bool(b: bool) -> &'static str {
    if b {
        "true"
    } else {
        "false"
    }
}

/// 浮点写成短形式：0.15 而不是 0.15000000000000002。
fn json_num(v: f64) -> String {
    if v.fract() == 0.0 && v.abs() < 1e15 {
        format!("{}", v as i64)
    } else {
        let s = format!("{:.4}", v);
        let s = s.trim_end_matches('0').trim_end_matches('.').to_string();
        if s.is_empty() {
            "0".to_string()
        } else {
            s
        }
    }
}

/// JSON 字符串转义。中文按原样输出（UTF-8 直出），不转 \u。
pub fn json_string(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 2);
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push('"');
    out
}

// ---------------- 手写 JSON ----------------

#[derive(Clone, Debug, PartialEq)]
pub enum Json {
    Null,
    Bool(bool),
    Num(f64),
    Str(String),
    Arr(Vec<Json>),
    /// 用 Vec 保序：写回时字段顺序稳定，diff 更干净。
    Obj(Vec<(String, Json)>),
}

impl Json {
    pub fn as_str(&self) -> Option<String> {
        match self {
            Json::Str(s) => Some(s.clone()),
            _ => None,
        }
    }
    /// 数字取整。JSON 里 30 和 30.0 都接受。
    pub fn as_int(&self) -> Option<i32> {
        match self {
            Json::Num(n) => {
                if n.is_finite() {
                    Some(*n as i32)
                } else {
                    None
                }
            }
            _ => None,
        }
    }
    pub fn as_float(&self) -> Option<f64> {
        match self {
            Json::Num(n) => {
                if n.is_finite() {
                    Some(*n)
                } else {
                    None
                }
            }
            _ => None,
        }
    }
    /// 宽松布尔：也认 0/1 和 "true"/"false"，跨实现容错。
    pub fn as_bool(&self) -> Option<bool> {
        match self {
            Json::Bool(b) => Some(*b),
            Json::Num(n) => Some(*n != 0.0),
            Json::Str(s) => match s.to_ascii_lowercase().as_str() {
                "true" | "1" | "yes" => Some(true),
                "false" | "0" | "no" => Some(false),
                _ => None,
            },
            _ => None,
        }
    }

    pub fn to_json(&self) -> String {
        let mut out = String::new();
        self.write_json(&mut out);
        out
    }

    fn write_json(&self, out: &mut String) {
        match self {
            Json::Null => out.push_str("null"),
            Json::Bool(b) => out.push_str(json_bool(*b)),
            Json::Num(n) => out.push_str(&json_num(*n)),
            Json::Str(s) => out.push_str(&json_string(s)),
            Json::Arr(a) => {
                out.push('[');
                for (i, v) in a.iter().enumerate() {
                    if i > 0 {
                        out.push(',');
                    }
                    v.write_json(out);
                }
                out.push(']');
            }
            Json::Obj(o) => {
                out.push('{');
                for (i, (k, v)) in o.iter().enumerate() {
                    if i > 0 {
                        out.push(',');
                    }
                    out.push_str(&json_string(k));
                    out.push(':');
                    v.write_json(out);
                }
                out.push('}');
            }
        }
    }
}

/// 手写递归下降解析器。要求覆盖 \" \\ \/ \b \f \n \r \t \uXXXX、中文、
/// 数字/布尔/null，以及嵌套对象和数组（未知字段可能是任何东西）。
pub fn parse_json(s: &str) -> Option<Json> {
    let chars: Vec<char> = s.chars().collect();
    let mut p = Parser { c: &chars, i: 0 };
    p.skip_ws();
    let v = p.value(0)?;
    p.skip_ws();
    // 后面还有垃圾字符就当解析失败，交给上层走"备份坏文件"分支。
    if p.i != p.c.len() {
        return None;
    }
    Some(v)
}

const MAX_DEPTH: usize = 64;

struct Parser<'a> {
    c: &'a [char],
    i: usize,
}

impl<'a> Parser<'a> {
    fn peek(&self) -> Option<char> {
        self.c.get(self.i).copied()
    }
    fn bump(&mut self) -> Option<char> {
        let c = self.peek();
        if c.is_some() {
            self.i += 1;
        }
        c
    }
    fn skip_ws(&mut self) {
        while let Some(c) = self.peek() {
            if c == ' ' || c == '\t' || c == '\n' || c == '\r' {
                self.i += 1;
            } else {
                break;
            }
        }
    }
    fn eat(&mut self, expect: char) -> Option<()> {
        if self.peek() == Some(expect) {
            self.i += 1;
            Some(())
        } else {
            None
        }
    }
    fn lit(&mut self, word: &str) -> Option<()> {
        for ch in word.chars() {
            if self.bump() != Some(ch) {
                return None;
            }
        }
        Some(())
    }

    fn value(&mut self, depth: usize) -> Option<Json> {
        if depth > MAX_DEPTH {
            return None; // 防御深嵌套把栈打爆
        }
        self.skip_ws();
        match self.peek()? {
            '{' => self.object(depth),
            '[' => self.array(depth),
            '"' => self.string().map(Json::Str),
            't' => {
                self.lit("true")?;
                Some(Json::Bool(true))
            }
            'f' => {
                self.lit("false")?;
                Some(Json::Bool(false))
            }
            'n' => {
                self.lit("null")?;
                Some(Json::Null)
            }
            c if c == '-' || c.is_ascii_digit() => self.number(),
            _ => None,
        }
    }

    fn object(&mut self, depth: usize) -> Option<Json> {
        self.eat('{')?;
        let mut out: Vec<(String, Json)> = Vec::new();
        self.skip_ws();
        if self.peek() == Some('}') {
            self.i += 1;
            return Some(Json::Obj(out));
        }
        loop {
            self.skip_ws();
            let k = self.string()?;
            self.skip_ws();
            self.eat(':')?;
            let v = self.value(depth + 1)?;
            out.push((k, v));
            self.skip_ws();
            match self.bump()? {
                ',' => continue,
                '}' => break,
                _ => return None,
            }
        }
        Some(Json::Obj(out))
    }

    fn array(&mut self, depth: usize) -> Option<Json> {
        self.eat('[')?;
        let mut out: Vec<Json> = Vec::new();
        self.skip_ws();
        if self.peek() == Some(']') {
            self.i += 1;
            return Some(Json::Arr(out));
        }
        loop {
            let v = self.value(depth + 1)?;
            out.push(v);
            self.skip_ws();
            match self.bump()? {
                ',' => continue,
                ']' => break,
                _ => return None,
            }
        }
        Some(Json::Arr(out))
    }

    fn string(&mut self) -> Option<String> {
        self.eat('"')?;
        let mut out = String::new();
        loop {
            let c = self.bump()?;
            match c {
                '"' => break,
                '\\' => {
                    let e = self.bump()?;
                    match e {
                        '"' => out.push('"'),
                        '\\' => out.push('\\'),
                        '/' => out.push('/'),
                        'b' => out.push('\u{08}'),
                        'f' => out.push('\u{0c}'),
                        'n' => out.push('\n'),
                        'r' => out.push('\r'),
                        't' => out.push('\t'),
                        'u' => {
                            let hi = self.hex4()?;
                            // 代理对：高位后必须跟 \uDC00-\uDFFF，否则按原码位塞进去
                            if (0xD800..0xDC00).contains(&hi) {
                                if self.peek() == Some('\\') {
                                    let save = self.i;
                                    self.i += 1;
                                    if self.peek() == Some('u') {
                                        self.i += 1;
                                        if let Some(lo) = self.hex4() {
                                            if (0xDC00..0xE000).contains(&lo) {
                                                let cp = 0x10000
                                                    + ((hi - 0xD800) << 10)
                                                    + (lo - 0xDC00);
                                                if let Some(ch) = char::from_u32(cp) {
                                                    out.push(ch);
                                                    continue;
                                                }
                                            }
                                        }
                                    }
                                    self.i = save; // 不是合法代理对，回退
                                }
                                out.push('\u{FFFD}');
                            } else if (0xDC00..0xE000).contains(&hi) {
                                out.push('\u{FFFD}');
                            } else if let Some(ch) = char::from_u32(hi) {
                                out.push(ch);
                            } else {
                                out.push('\u{FFFD}');
                            }
                        }
                        _ => return None,
                    }
                }
                c => out.push(c),
            }
        }
        Some(out)
    }

    fn hex4(&mut self) -> Option<u32> {
        let mut v: u32 = 0;
        for _ in 0..4 {
            let c = self.bump()?;
            let d = c.to_digit(16)?;
            v = v * 16 + d;
        }
        Some(v)
    }

    fn number(&mut self) -> Option<Json> {
        let start = self.i;
        if self.peek() == Some('-') {
            self.i += 1;
        }
        while let Some(c) = self.peek() {
            if c.is_ascii_digit() || c == '.' || c == 'e' || c == 'E' || c == '+' || c == '-' {
                self.i += 1;
            } else {
                break;
            }
        }
        let s: String = self.c[start..self.i].iter().collect();
        s.parse::<f64>().ok().map(Json::Num)
    }
}

/// 供 UI 用：把配置里的颜色转成 COLORREF（GDI 的 0x00BBGGRR）。
pub fn colorref(hex: &str) -> u32 {
    let (r, g, b) = parse_color(hex);
    (r as u32) | ((g as u32) << 8) | ((b as u32) << 16)
}

/// 供设置面板用：把 COLORREF 转回 "#RRGGBB"。
pub fn colorref_to_hex(cr: u32) -> String {
    let r = (cr & 0xFF) as u8;
    let g = ((cr >> 8) & 0xFF) as u8;
    let b = ((cr >> 16) & 0xFF) as u8;
    color_to_hex((r, g, b))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_and_roundtrips() {
        let src = r#"{"text":"内部 \"A\"\n","font_size":42,"opacity":0.5,"bold":false,"未知":123}"#;
        let (c, extras) = Config::parse_with_extras(src).expect("should parse");
        assert_eq!(c.font_size, 42);
        assert_eq!(c.opacity, 0.5);
        assert!(!c.bold);
        assert!(extras.contains_key("未知"));
        let out = c.to_json(&extras);
        assert!(out.contains("\"未知\":123"), "{}", out);
        let (c2, _) = Config::parse_with_extras(&out).expect("reparse");
        assert_eq!(c2.text, c.text);
    }

    #[test]
    fn surrogate_pair() {
        let v = parse_json(r#""\ud83d\ude00""#).unwrap();
        assert_eq!(v.as_str().unwrap(), "😀");
    }

    #[test]
    fn rejects_garbage() {
        assert!(parse_json("{").is_none());
        assert!(parse_json("").is_none());
    }
}
