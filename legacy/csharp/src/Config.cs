// Config.cs —— 配置对象 + JSON 读写 + 模板变量。
//
// 为什么底层压着一个 Dictionary<string, object>：
// 规格要求「未知字段保留不删」。如果用强类型类直接反序列化，Python 版或将来新加的字段
// 会在 C# 这边存盘时被静默吃掉，两个实现就再也没法互换配置了。
// 所以：字典是唯一真相，强类型属性只是它上面的视图。
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Web.Script.Serialization;

namespace ScreenWatermark
{
    internal sealed class Config
    {
        // ---- 默认值：和 DESIGN.md §2 的表格逐行对应 ----------------------
        public const string DefText = "内部资料 请勿外传";
        public const string DefFontFamily = "Microsoft YaHei";
        public const int DefFontSize = 30;
        public const bool DefBold = true;
        public const bool DefItalic = false;
        public const string DefColor = "#808080";
        public const double DefOpacity = 0.15;
        public const int DefAngle = -30;
        public const int DefGapX = 150;
        public const int DefGapY = 120;
        public const double DefLineSpacing = 1.2;
        public const bool DefEnabled = true;
        public const bool DefClickThrough = true;
        public const bool DefTemplate = false;
        public const string DefTimeFormat = "%Y-%m-%d %H:%M";
        public const int DefRefreshSeconds = 30;
        public const bool DefAllMonitors = true;
        public const bool DefPhaseOffset = true;
        public const bool DefAutostart = false;

        private readonly Dictionary<string, object> _data = new Dictionary<string, object>(StringComparer.Ordinal);

        // 加工过的模板结果缓存：{time} 每 30 秒才变一次，没必要每块屏各算一遍。
        private string _cachedText;
        private string _cachedSource;
        private bool _cachedTemplate;
        private string _cachedFormat;

        public string LoadedFrom;
        public string LoadError;

        public Config()
        {
            LoadedFrom = DefaultPath();
        }

        // ================= 强类型视图 =================

        public string Text
        {
            get { return GetStr("text", DefText); }
            set { _data["text"] = value; }
        }

        public string FontFamily
        {
            get { return GetStr("font_family", DefFontFamily); }
            set { _data["font_family"] = value; }
        }

        public int FontSize
        {
            get { return GetInt("font_size", DefFontSize, 8, 400); }
            set { _data["font_size"] = value; }
        }

        public bool Bold
        {
            get { return GetBool("bold", DefBold); }
            set { _data["bold"] = value; }
        }

        public bool Italic
        {
            get { return GetBool("italic", DefItalic); }
            set { _data["italic"] = value; }
        }

        public string Color
        {
            get { return GetStr("color", DefColor); }
            set { _data["color"] = value; }
        }

        public double Opacity
        {
            get { return GetDouble("opacity", DefOpacity, 0.01, 1.0); }
            set { _data["opacity"] = value; }
        }

        public int Angle
        {
            get { return GetInt("angle", DefAngle, -90, 90); }
            set { _data["angle"] = value; }
        }

        public int GapX
        {
            get { return GetInt("gap_x", DefGapX, 0, 2000); }
            set { _data["gap_x"] = value; }
        }

        public int GapY
        {
            get { return GetInt("gap_y", DefGapY, 0, 2000); }
            set { _data["gap_y"] = value; }
        }

        public double LineSpacing
        {
            get { return GetDouble("line_spacing", DefLineSpacing, 0.5, 3.0); }
            set { _data["line_spacing"] = value; }
        }

        public bool Enabled
        {
            get { return GetBool("enabled", DefEnabled); }
            set { _data["enabled"] = value; }
        }

        public bool ClickThrough
        {
            get { return GetBool("click_through", DefClickThrough); }
            set { _data["click_through"] = value; }
        }

        public bool Template
        {
            get { return GetBool("template", DefTemplate); }
            set { _data["template"] = value; }
        }

        public string TimeFormat
        {
            get { return GetStr("time_format", DefTimeFormat); }
            set { _data["time_format"] = value; }
        }

        public int RefreshSeconds
        {
            get { return GetInt("refresh_seconds", DefRefreshSeconds, 5, 3600); }
            set { _data["refresh_seconds"] = value; }
        }

        public bool AllMonitors
        {
            get { return GetBool("all_monitors", DefAllMonitors); }
            set { _data["all_monitors"] = value; }
        }

        public bool PhaseOffset
        {
            get { return GetBool("phase_offset", DefPhaseOffset); }
            set { _data["phase_offset"] = value; }
        }

        public bool Autostart
        {
            get { return GetBool("autostart", DefAutostart); }
            set { _data["autostart"] = value; }
        }

        // ================= 容错取值 =================
        // JavaScriptSerializer 把 JSON 数字读成 int / decimal / double 三种都可能，
        // 直接强转 (int) 会 InvalidCastException。所有取值都走这几个帮手。

        private static bool IsMissing(object v)
        {
            return v == null || v == DBNull.Value;
        }

        public static double ToDouble(object v, double fallback)
        {
            if (IsMissing(v)) return fallback;
            if (v is double) return (double)v;
            if (v is decimal) return (double)(decimal)v;
            if (v is int) return (int)v;
            if (v is long) return (long)v;
            if (v is float) return (float)v;
            if (v is bool) return ((bool)v) ? 1.0 : 0.0;
            if (v is string)
            {
                double d;
                double.TryParse((string)v, NumberStyles.Float, CultureInfo.InvariantCulture, out d);
                return d;
            }
            try { return Convert.ToDouble(v, CultureInfo.InvariantCulture); }
            catch (Exception) { return fallback; }
        }

        public static int ToInt(object v, int fallback)
        {
            if (IsMissing(v)) return fallback;
            if (v is int) return (int)v;
            if (v is long) return (int)(long)v;
            return (int)Math.Round(ToDouble(v, fallback));
        }

        public static bool ToBool(object v, bool fallback)
        {
            if (IsMissing(v)) return fallback;
            if (v is bool) return (bool)v;
            if (v is string)
            {
                string s = ((string)v).Trim().ToLowerInvariant();
                if (s == "true" || s == "1" || s == "yes" || s == "on") return true;
                if (s == "false" || s == "0" || s == "no" || s == "off") return false;
                return fallback;
            }
            if (v is int) return (int)v != 0;
            if (v is long) return (long)v != 0;
            return fallback;
        }

        private string GetStr(string key, string fallback)
        {
            object v;
            if (!_data.TryGetValue(key, out v) || IsMissing(v)) return fallback;
            if (v is string) return (string)v;
            return Convert.ToString(v, CultureInfo.InvariantCulture);
        }

        private int GetInt(string key, int fallback, int min, int max)
        {
            object v;
            if (!_data.TryGetValue(key, out v)) return fallback;
            int n = ToInt(v, fallback);
            if (n < min) n = min;
            if (n > max) n = max;
            return n;
        }

        private double GetDouble(string key, double fallback, double min, double max)
        {
            object v;
            if (!_data.TryGetValue(key, out v)) return fallback;
            double d = ToDouble(v, fallback);
            if (double.IsNaN(d) || double.IsInfinity(d)) d = fallback;
            if (d < min) d = min;
            if (d > max) d = max;
            return d;
        }

        private bool GetBool(string key, bool fallback)
        {
            object v;
            if (!_data.TryGetValue(key, out v)) return fallback;
            return ToBool(v, fallback);
        }

        // ================= 路径 =================

        /// <summary>
        /// 规格：exe 同级目录优先。目录不可写时回落 %APPDATA%\ScreenWatermark\config.json。
        /// 这里只做判定不做写入——真正的可写性在 Save 时才知道，所以 Save 里还会再兜一次。
        /// </summary>
        public static string DefaultPath()
        {
            string exeDir = null;
            try { exeDir = Path.GetDirectoryName(System.Windows.Forms.Application.ExecutablePath); }
            catch (Exception) { }

            if (!string.IsNullOrEmpty(exeDir))
            {
                try
                {
                    if (Directory.Exists(exeDir)) return Path.Combine(exeDir, "config.json");
                }
                catch (Exception) { }
            }

            return AppDataPath();
        }

        public static string AppDataPath()
        {
            string dir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                "ScreenWatermark");
            return Path.Combine(dir, "config.json");
        }

        // ================= 读 =================

        public static Config Load(string path, bool forceDefault)
        {
            Config cfg = new Config();
            if (string.IsNullOrEmpty(path)) path = DefaultPath();
            cfg.LoadedFrom = path;

            if (forceDefault || !File.Exists(path)) return cfg;

            string raw = null;
            try
            {
                // 无 BOM 读；带 BOM 的文件也能读进来，只是会多一个 \uFEFF 前缀，下面剥掉。
                raw = File.ReadAllText(path, new UTF8Encoding(false));
            }
            catch (Exception ex)
            {
                cfg.LoadError = "读取配置失败: " + ex.Message;
                return cfg;
            }

            try
            {
                cfg.MergeWith(
                    new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(raw));
            }
            catch (Exception ex)
            {
                // 解析失败不要崩，也绝对不要拿默认值把用户的原文件覆盖掉——先备份。
                cfg.LoadError = "配置解析失败: " + ex.Message;
                cfg.BackupBad(path);
            }
            return cfg;
        }

        private void BackupBad(string path)
        {
            try
            {
                string bad = Path.Combine(Path.GetDirectoryName(path), "config.bad.json");
                File.Copy(path, bad, true);
            }
            catch (Exception) { /* 备份失败也不能影响启动 */ }
        }

        /// <summary>
        /// 重置默认：把已知字段全丢掉，未知字段保留（别人的扩展不能因为一次"重置"就没了）。
        /// </summary>
        public void ResetToDefaults()
        {
            string[] known = new string[]
            {
                "text", "font_family", "font_size", "bold", "italic", "color", "opacity", "angle",
                "gap_x", "gap_y", "line_spacing", "enabled", "click_through", "template",
                "time_format", "refresh_seconds", "all_monitors", "phase_offset", "autostart"
            };
            for (int i = 0; i < known.Length; i++) _data.Remove(known[i]);
            _cachedSource = null;
            _cachedText = null;
        }

        private void MergeWith(Dictionary<string, object> parsed)
        {
            _data.Clear();
            if (parsed == null) return;
            foreach (KeyValuePair<string, object> kv in parsed)
            {
                if (kv.Key == null) continue;
                _data[kv.Key] = kv.Value;
            }
            _cachedSource = null; // 换了数据源，模板缓存作废
        }

        // ================= 写 =================

        /// <summary>
        /// 写回。未知字段因为一直在 _data 里，天然跟着出去。
        /// 返回 true 表示真的落盘了。
        /// </summary>
        public bool Save(out string usedPath, out string error)
        {
            usedPath = LoadedFrom;
            error = null;

            string json;
            try
            {
                // 已知字段先写一遍，保证顺序稳定、类型和 §2 表格一致。
                Dictionary<string, object> outData = new Dictionary<string, object>(StringComparer.Ordinal);
                outData["text"] = Text;
                outData["font_family"] = FontFamily;
                outData["font_size"] = FontSize;
                outData["bold"] = Bold;
                outData["italic"] = Italic;
                outData["color"] = Color;
                outData["opacity"] = Math.Round(Opacity, 4);
                outData["angle"] = Angle;
                outData["gap_x"] = GapX;
                outData["gap_y"] = GapY;
                outData["line_spacing"] = Math.Round(LineSpacing, 4);
                outData["enabled"] = Enabled;
                outData["click_through"] = ClickThrough;
                outData["template"] = Template;
                outData["time_format"] = TimeFormat;
                outData["refresh_seconds"] = RefreshSeconds;
                outData["all_monitors"] = AllMonitors;
                outData["phase_offset"] = PhaseOffset;
                outData["autostart"] = Autostart;

                // 把字典里我们不认识的键补回来，不删别人的字段。
                foreach (KeyValuePair<string, object> kv in _data)
                {
                    if (!outData.ContainsKey(kv.Key)) outData[kv.Key] = kv.Value;
                }

                json = new JavaScriptSerializer().Serialize(outData);
            }
            catch (Exception ex)
            {
                error = "序列化失败: " + ex.Message;
                return false;
            }

            if (TryWrite(LoadedFrom, json, out error)) return true;

            // exe 同级目录不可写（比如装在 Program Files）→ 回落 APPDATA，并记住新路径。
            string fallback = AppDataPath();
            if (string.Equals(fallback, LoadedFrom, StringComparison.OrdinalIgnoreCase)) return false;

            string err2;
            if (TryWrite(fallback, json, out err2))
            {
                LoadedFrom = fallback;
                usedPath = fallback;
                error = null;
                return true;
            }
            error = error + " / 回落目录也失败: " + err2;
            return false;
        }

        private static bool TryWrite(string path, string json, out string error)
        {
            error = null;
            try
            {
                string dir = Path.GetDirectoryName(path);
                if (!string.IsNullOrEmpty(dir) && !Directory.Exists(dir)) Directory.CreateDirectory(dir);
                // 显式 UTF8Encoding(false)：Python 版用 json.load 读，带 BOM 会直接报错。
                File.WriteAllText(path, json, new UTF8Encoding(false));
                return true;
            }
            catch (Exception ex)
            {
                error = ex.Message;
                return false;
            }
        }

        // ================= 模板变量 =================

        /// <summary>
        /// 拿到最终要画的文字。template=false 时原样返回（缓存，别每次重画都算）。
        /// </summary>
        public string ResolvedText()
        {
            string src = Text;
            if (!Template) return src;

            string fmt = TimeFormat;
            if (_cachedSource == src && _cachedTemplate && _cachedFormat == fmt && _cachedText != null)
                return _cachedText;

            _cachedText = ResolveTemplate(src, fmt, DateTime.Now);
            _cachedSource = src;
            _cachedTemplate = true;
            _cachedFormat = fmt;
            return _cachedText;
        }

        /// <summary>模板变量是不是每轮都在动（只有 {time} 会动，其余一轮进程里是常量）。</summary>
        public bool TemplateVaries()
        {
            return Template && Text.IndexOf("{time}", StringComparison.OrdinalIgnoreCase) >= 0;
        }

        public static string ResolveTemplate(string src, string timeFormat, DateTime now)
        {
            if (src == null) return string.Empty;
            if (timeFormat == null) timeFormat = DefTimeFormat;

            StringBuilder sb = new StringBuilder(src.Length + 32);
            int i = 0;
            while (i < src.Length)
            {
                char c = src[i];
                if (c == '{')
                {
                    if (i + 1 < src.Length && src[i + 1] == '{') { sb.Append('{'); i += 2; continue; }

                    string lower = src.Substring(i).ToLowerInvariant();
                    if (lower.StartsWith("{time}")) { sb.Append(Strftime(timeFormat, now)); i += 6; continue; }
                    if (lower.StartsWith("{date}")) { sb.Append(Strftime("%Y-%m-%d", now)); i += 6; continue; }
                    if (lower.StartsWith("{user}")) { sb.Append(Environment.UserName); i += 6; continue; }
                    if (lower.StartsWith("{host}")) { sb.Append(MachineName()); i += 6; continue; }
                    if (lower.StartsWith("{ip}")) { sb.Append(LocalIPv4()); i += 4; continue; }

                    sb.Append(c);
                    i++;
                    continue;
                }
                if (c == '}' && i + 1 < src.Length && src[i + 1] == '}')
                {
                    sb.Append('}');
                    i += 2;
                    continue;
                }
                sb.Append(c);
                i++;
            }
            return sb.ToString();
        }

        /// <summary>
        /// Python 的 strftime 子集。规格里的 time_format 是 strftime 格式串，
        /// 这边没法直接用 .NET 的格式串（%Y 和 yyyy 不是一回事），所以自己查表换。
        /// 认不出的 %x 原样吐出来，方便用户看出自己写错了。
        /// </summary>
        public static string Strftime(string fmt, DateTime t)
        {
            if (string.IsNullOrEmpty(fmt)) return string.Empty;

            StringBuilder sb = new StringBuilder(fmt.Length + 16);
            int i = 0;
            while (i < fmt.Length)
            {
                char c = fmt[i];
                if (c != '%' || i + 1 >= fmt.Length)
                {
                    sb.Append(c);
                    i++;
                    continue;
                }

                char d = fmt[i + 1];
                switch (d)
                {
                    case 'Y': sb.Append(t.Year.ToString("D4", CultureInfo.InvariantCulture)); i += 2; break;
                    case 'y': sb.Append((t.Year % 100).ToString("D2", CultureInfo.InvariantCulture)); i += 2; break;
                    case 'm': sb.Append(t.Month.ToString("D2", CultureInfo.InvariantCulture)); i += 2; break;
                    case 'd': sb.Append(t.Day.ToString("D2", CultureInfo.InvariantCulture)); i += 2; break;
                    case 'H': sb.Append(t.Hour.ToString("D2", CultureInfo.InvariantCulture)); i += 2; break;
                    case 'I': sb.Append(((t.Hour % 12 == 0) ? 12 : t.Hour % 12).ToString("D2", CultureInfo.InvariantCulture)); i += 2; break;
                    case 'M': sb.Append(t.Minute.ToString("D2", CultureInfo.InvariantCulture)); i += 2; break;
                    case 'S': sb.Append(t.Second.ToString("D2", CultureInfo.InvariantCulture)); i += 2; break;
                    case 'j': sb.Append(t.DayOfYear.ToString("D3", CultureInfo.InvariantCulture)); i += 2; break;
                    case 'p': sb.Append(t.Hour < 12 ? "AM" : "PM"); i += 2; break;
                    case 'b': sb.Append(t.ToString("MMM", CultureInfo.InvariantCulture)); i += 2; break;
                    case 'B': sb.Append(t.ToString("MMMM", CultureInfo.InvariantCulture)); i += 2; break;
                    case 'a': sb.Append(t.ToString("ddd", CultureInfo.InvariantCulture)); i += 2; break;
                    case 'A': sb.Append(t.ToString("dddd", CultureInfo.InvariantCulture)); i += 2; break;
                    case 'x': sb.Append(t.ToString("MM/dd/yy", CultureInfo.InvariantCulture)); i += 2; break;
                    case 'X': sb.Append(t.ToString("HH:mm:ss", CultureInfo.InvariantCulture)); i += 2; break;
                    case 'f': sb.Append(t.ToString("ffffff", CultureInfo.InvariantCulture)); i += 2; break;
                    case '%': sb.Append('%'); i += 2; break;
                    default:
                        // 认不出的转换符：原样保留 "%q"，用户能看出问题。
                        sb.Append('%');
                        sb.Append(d);
                        i += 2;
                        break;
                }
            }
            return sb.ToString();
        }

        private static string MachineName()
        {
            try
            {
                int cap = NativeMethods.MAX_COMPUTERNAME_LENGTH + 1;
                StringBuilder sb = new StringBuilder(cap);
                if (NativeMethods.GetComputerNameW(sb, ref cap)) return sb.ToString();
            }
            catch (Exception) { }
            try { return Environment.MachineName; }
            catch (Exception) { return string.Empty; }
        }

        /// <summary>
        /// 内网 IPv4。取不到就返回空串（规格如此），不要抛异常。
        /// 优先挑第一个不是回环、不是 APIPA(169.254) 的地址。
        /// </summary>
        public static string LocalIPv4()
        {
            string apipa = null;
            try
            {
                IPAddress[] addrs = Dns.GetHostAddresses(Dns.GetHostName());
                for (int i = 0; i < addrs.Length; i++)
                {
                    IPAddress a = addrs[i];
                    if (a.AddressFamily != AddressFamily.InterNetwork) continue;
                    if (IPAddress.IsLoopback(a)) continue;
                    string s = a.ToString();
                    if (s.StartsWith("169.254.", StringComparison.Ordinal))
                    {
                        if (apipa == null) apipa = s;
                        continue;
                    }
                    return s;
                }
            }
            catch (Exception) { }
            return apipa != null ? apipa : string.Empty;
        }

        /// <summary>
        /// "#RRGGBB" → Color。解析不出来就退回规格默认的灰，绝不抛。
        /// </summary>
        public System.Drawing.Color ParseColor()
        {
            return ParseColorHex(Color, System.Drawing.Color.FromArgb(0x80, 0x80, 0x80));
        }

        public static System.Drawing.Color ParseColorHex(string hex, System.Drawing.Color fallback)
        {
            if (string.IsNullOrEmpty(hex)) return fallback;
            string s = hex.Trim();
            if (s.StartsWith("#", StringComparison.Ordinal)) s = s.Substring(1);
            if (s.Length == 3)
            {
                s = new string(new char[] { s[0], s[0], s[1], s[1], s[2], s[2] });
            }
            if (s.Length != 6) return fallback;
            try
            {
                int r = int.Parse(s.Substring(0, 2), NumberStyles.HexNumber, CultureInfo.InvariantCulture);
                int g = int.Parse(s.Substring(2, 2), NumberStyles.HexNumber, CultureInfo.InvariantCulture);
                int b = int.Parse(s.Substring(4, 2), NumberStyles.HexNumber, CultureInfo.InvariantCulture);
                return System.Drawing.Color.FromArgb(r, g, b);
            }
            catch (Exception)
            {
                return fallback;
            }
        }

        public static string ToHex(System.Drawing.Color c)
        {
            return string.Format(CultureInfo.InvariantCulture, "#{0:X2}{1:X2}{2:X2}", c.R, c.G, c.B);
        }
    }
}
