// Program.cs —— 进程入口。
// 这个文件只做三件事：确认只有一个实例、把 DPI 感知钉死、把 ApplicationContext 跑起来。
// 业务逻辑一律不写在这里，方便单独测。
using System;
using System.Threading;
using System.Windows.Forms;

namespace ScreenWatermark
{
    internal static class Program
    {
        public const string Version = "1.0.0";

        // 用 Global\ 前缀跨会话互斥：同一台机器上开两个水印进程只会互相打架。
        private const string MutexName = "Global\\ScreenWatermark_SingleInstance";

        [STAThread]
        private static void Main(string[] args)
        {
            // 配置要落在 exe 同级目录，命令行 --config 可以指到别处（方便调试）。
            string configPath = null;
            bool forceDefault = false;
            for (int i = 0; i < args.Length; i++)
            {
                string a = args[i];
                if (string.Equals(a, "--config", StringComparison.OrdinalIgnoreCase) && i + 1 < args.Length)
                {
                    configPath = args[++i];
                }
                else if (string.Equals(a, "--default", StringComparison.OrdinalIgnoreCase))
                {
                    forceDefault = true;
                }
                else if (string.Equals(a, "--dump-dpi", StringComparison.OrdinalIgnoreCase))
                {
                    // 纯诊断：把 DPI 实测状态写文件后立刻退出，不建任何窗口。
                    // 输出路径固定，方便测试脚本读。
                    try
                    {
                        EnsureDpiAwareness();
                        System.IO.File.WriteAllText(
                            System.IO.Path.Combine(
                                System.IO.Path.GetDirectoryName(Application.ExecutablePath),
                                "_dpi_report.txt"),
                            DpiReport(), new System.Text.UTF8Encoding(false));
                    }
                    catch (Exception) { }
                    return;
                }
                else if (string.Equals(a, "--dump-labels", StringComparison.OrdinalIgnoreCase))
                {
                    try
                    {
                        EnsureDpiAwareness();
                        System.IO.File.WriteAllText(
                            System.IO.Path.Combine(
                                System.IO.Path.GetDirectoryName(Application.ExecutablePath),
                                "_labels_report.txt"),
                            LabelMetricsReport(), new System.Text.UTF8Encoding(false));
                    }
                    catch (Exception) { }
                    return;
                }
                else if (string.Equals(a, "--dump-panel", StringComparison.OrdinalIgnoreCase))
                {
                    // 把设置面板的控件树（类型/文本/Bounds/Visible/父容器）+ 布局自检
                    // 写成文件后退出。手写坐标的布局出问题时，只有实际树能说明
                    // 是坐标算错、被同级控件盖住、还是被裁掉。
                    string report;
                    try
                    {
                        Config panelCfg = Config.Load(configPath, true);
                        using (SettingsForm f = new SettingsForm(panelCfg))
                        {
                            f.Show();
                            Application.DoEvents();
                            System.Threading.Thread.Sleep(400);
                            Application.DoEvents();
                            f.PerformLayout();

                            report = f.DumpControlTree();
                            string problems = f.LayoutProblems();
                            report += "\nlayout self-check: " +
                                (problems == null ? "OK (无重叠、无裁切)" : "\n" + problems);
                        }
                    }
                    catch (Exception ex)
                    {
                        report = "dump failed: " + ex.ToString();
                    }
                    try
                    {
                        System.IO.File.WriteAllText(
                            System.IO.Path.Combine(
                                System.IO.Path.GetDirectoryName(Application.ExecutablePath),
                                "_panel_tree.txt"),
                            report, new System.Text.UTF8Encoding(false));
                    }
                    catch (Exception) { }
                    return;
                }
                else if (string.Equals(a, "--dump-metrics", StringComparison.OrdinalIgnoreCase))
                {
                    // 把 §6 的三个量（text_width / text_height / cell）实测出来。
                    // 用来核对截图里量到的平铺周期：cell_w 应该等于 text_width + gap_x。
                    try
                    {
                        EnsureDpiAwareness();
                        System.IO.File.WriteAllText(
                            System.IO.Path.Combine(
                                System.IO.Path.GetDirectoryName(Application.ExecutablePath),
                                "_metrics_report.txt"),
                            MetricsReport(), new System.Text.UTF8Encoding(false));
                    }
                    catch (Exception) { }
                    return;
                }
                else if (string.Equals(a, "--version", StringComparison.OrdinalIgnoreCase) ||
                         string.Equals(a, "-v", StringComparison.OrdinalIgnoreCase))
                {
                    // winexe 没有控制台，但 ExitCode 里能看到；写文件太脏，直接弹窗又会烦人，
                    // 所以 --version 走 MessageBox，这是用户主动要的行为。
                    MessageBox.Show("ScreenWatermark " + Version + " (.NET Framework 4.8, x64)",
                        "ScreenWatermark", MessageBoxButtons.OK, MessageBoxIcon.Information);
                    return;
                }
            }

            // DPI 感知：manifest 已经声明了，这里再兜一层，防止有人把 manifest 剥掉再跑。
            EnsureDpiAwareness();

            bool createdNew;
            Mutex mutex;
            try
            {
                mutex = new Mutex(true, MutexName, out createdNew);
            }
            catch (UnauthorizedAccessException)
            {
                // 名字被别的会话占着（多用户同时登录），不让它变成致命错误，直接放行。
                createdNew = true;
                mutex = null;
            }

            if (!createdNew)
            {
                MessageBox.Show("ScreenWatermark 已经在运行了。\n\n用托盘图标或 Ctrl+Alt+S 打开设置面板。",
                    "ScreenWatermark", MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }

            try
            {
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);

                AppController controller = null;
                try
                {
                    controller = new AppController(configPath, forceDefault);
                }
                catch (Exception ex)
                {
                    // 启动阶段炸掉是致命的：必须让用户看见，不能静默退出（不然像是双击没反应）。
                    MessageBox.Show("ScreenWatermark 启动失败：\n\n" + ex.ToString(),
                        "ScreenWatermark 启动错误", MessageBoxButtons.OK, MessageBoxIcon.Error);
                    return;
                }

                Application.Run(controller);
            }
            finally
            {
                if (mutex != null)
                {
                    try { mutex.ReleaseMutex(); }
                    catch (ApplicationException) { /* 没持有时忽略 */ }
                    mutex.Close();
                }
            }
        }

        /// <summary>
        /// 按可用性从新到旧尝试：PerMonitorV2 最佳，其次 PerMonitor，
        /// 最后顺带提一下系统 DPI。全部失败也无所谓，manifest 已经生效了。
        /// </summary>
        private static void EnsureDpiAwareness()
        {
            try
            {
                // DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
                if (NativeMethods.SetProcessDpiAwarenessContext(new IntPtr(-4))) return;
            }
            catch (Exception) { }
            try
            {
                NativeMethods.SetProcessDpiAwareness(2); // PROCESS_PER_MONITOR_DPI_AWARE
            }
            catch (Exception) { }
        }

        /// <summary>
        /// 量一下设置面板左列那几个中文标签在真实字体/DPI 下到底要多少像素。
        /// 为什么要专门量：Windows 会给 AutoSize 的 Label 报一个取整后的宽度，
        /// 我按"每字 21px 估"得出的结论和实际不符，导致"旋转角度"最后一个字被截。
        /// 直接问 TextRenderer 才是最省事的办法。
        /// </summary>
        public static string LabelMetricsReport()
        {
            System.Text.StringBuilder sb = new System.Text.StringBuilder();
            using (System.Drawing.Font f = new System.Drawing.Font("Microsoft YaHei UI", 9f))
            {
                sb.Append("font = ").Append(f.Name).Append(' ').Append(f.SizeInPoints).Append("pt")
                  .Append("  height=").Append(f.Height).Append('\n');
                string[] labels = new string[]
                {
                    "水印文本", "字体大小", "不透明度", "旋转角度", "水平间距", "垂直间距",
                    "行距倍数", "文字颜色", "字体名称", "时间格式", "启用模板变量", "全部显示器",
                    "粗体", "斜体", "鼠标穿透", "显示水印", "实时预览（改任何选项立刻重画）",
                    "行错位（奇数行错开半格）", "隐藏水印", "保存配置", "重置默认", "应用"
                };
                for (int i = 0; i < labels.Length; i++)
                {
                    System.Drawing.Size gdi = System.Windows.Forms.TextRenderer.MeasureText(
                        labels[i], f, new System.Drawing.Size(int.MaxValue, int.MaxValue),
                        System.Windows.Forms.TextFormatFlags.NoPadding);
                    System.Drawing.Size gdiPad = System.Windows.Forms.TextRenderer.MeasureText(
                        labels[i], f);
                    System.Drawing.SizeF gdip = new System.Drawing.SizeF(0, 0);
                    using (System.Drawing.Bitmap b = new System.Drawing.Bitmap(1, 1))
                    using (System.Drawing.Graphics g = System.Drawing.Graphics.FromImage(b))
                    {
                        gdip = g.MeasureString(labels[i], f);
                    }
                    sb.Append(string.Format("{0,-8} chars={1}  GDI(NoPadding)={2}x{3}  GDI={4}x{5}  GDI+={6:F0}x{7:F0}\n",
                        labels[i], labels[i].Length, gdi.Width, gdi.Height,
                        gdiPad.Width, gdiPad.Height, gdip.Width, gdip.Height));
                }
            }
            return sb.ToString();
        }

        /// <summary>
        /// 把 DPI 相关的实际状态报出来。
        ///
        /// 为什么需要这个：manifest 里写了 PerMonitorV2，但 manifest 也可能被系统忽略，
        /// 而"被忽略"的表现是 Screen.AllScreens 悄悄返回逻辑像素（1440x960 而不是
        /// 物理的 2520x1680），水印比屏幕小一圈却不会报任何错。这种事只能靠实测数字发现。
        /// </summary>
        public static string DpiReport()
        {
            System.Text.StringBuilder sb = new System.Text.StringBuilder();
            int awareness = -1;
            try { NativeMethods.GetProcessDpiAwareness(IntPtr.Zero, out awareness); }
            catch (Exception) { }
            string name;
            if (awareness == 0) name = "UNAWARE(0)";
            else if (awareness == 1) name = "SYSTEM_AWARE(1)";
            else if (awareness == 2) name = "PER_MONITOR_AWARE(2)";
            else name = "unknown(" + awareness + ")";

            sb.Append("process_dpi_awareness=").Append(name).Append('\n');
            try { sb.Append("system_dpi=").Append(NativeMethods.GetDpiForSystem()).Append('\n'); }
            catch (Exception) { }
            try
            {
                System.Drawing.Rectangle b = Screen.PrimaryScreen.Bounds;
                sb.Append("primary_bounds=").Append(b.Width).Append('x').Append(b.Height).Append('\n');
                sb.Append("all_screens=").Append(Screen.AllScreens.Length).Append('\n');
            }
            catch (Exception) { }
            return sb.ToString();
        }

        /// <summary>
        /// 按 §6 的公式把格子尺寸实测一遍并报出来。
        /// 存在的意义：截图自相关只能看到"周期多少像素"，不能说明这个周期是不是
        /// text_width + gap_x 算出来的。两个数对上了，平铺算法才算被证明。
        /// </summary>
        public static string MetricsReport()
        {
            Config c = Config.Load(null, true);
            System.Text.StringBuilder sb = new System.Text.StringBuilder();
            string[] dpiList = new string[] { "96", "168" };
            for (int i = 0; i < dpiList.Length; i++)
            {
                float dpi = float.Parse(dpiList[i], System.Globalization.CultureInfo.InvariantCulture);
                sb.Append("--- gdiDpi=").Append(dpiList[i]).Append(" ---\n");

                string[] families = new string[] { c.FontFamily, "Consolas" };
                for (int f = 0; f < families.Length; f++)
                {
                    System.Drawing.FontFamily fam = WatermarkRenderer.ResolveFamily(families[f]);
                    System.Drawing.SizeF text = WatermarkRenderer.MeasureUnitText(
                        c.ResolvedText(), fam, c.FontSize * dpi / 72f, c.Bold, c.Italic);
                    System.Drawing.SizeF cell = WatermarkRenderer.MeasureCell(
                        c.ResolvedText(), fam, c.FontSize * dpi / 72f, c.Bold, c.Italic,
                        c.LineSpacing, c.GapX, c.GapY);

                    sb.Append("font=").Append(fam.Name)
                      .Append(" size=").Append(c.FontSize).Append("pt")
                      .Append(" em=").Append((c.FontSize * dpi / 72f).ToString("F1"))
                      .Append('\n');
                    sb.Append("  text_width  = ").Append(text.Width.ToString("F1")).Append('\n');
                    sb.Append("  text_height = ").Append(text.Height.ToString("F1")).Append('\n');
                    sb.Append("  cell_w      = text_width + gap_x = ")
                      .Append(text.Width.ToString("F1")).Append(" + ").Append(c.GapX)
                      .Append(" = ").Append(cell.Width.ToString("F1")).Append('\n');
                    sb.Append("  cell_h      = text_height * line_spacing + gap_y = ")
                      .Append(text.Height.ToString("F1")).Append(" * ").Append(c.LineSpacing.ToString("F2"))
                      .Append(" + ").Append(c.GapY).Append(" = ").Append(cell.Height.ToString("F1")).Append('\n');
                }
            }
            return sb.ToString();
        }
    }
}
