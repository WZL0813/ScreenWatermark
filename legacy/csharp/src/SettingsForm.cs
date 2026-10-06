// SettingsForm.cs —— 设置面板。DESIGN.md §5 列的 14 项一个不少。
//
// 两条硬要求写在行为里，不是写在注释里：
//   1. 实时预览勾上时，改任何控件立刻重画（不销毁重建窗口）；
//   2. 关掉面板不退出程序，水印继续挂着。
using System;
using System.ComponentModel;
using System.Drawing;
using System.Windows.Forms;

namespace ScreenWatermark
{
    internal sealed class SettingsForm : Form
    {
        private readonly Config _config;

        private TextBox _txtText;
        private NumericUpDown _numFontSize;
        private TrackBar _barOpacity;
        private Label _lblOpacityValue;
        private TrackBar _barAngle;
        private Label _lblAngleValue;
        private NumericUpDown _numGapX;
        private NumericUpDown _numGapY;
        private Button _btnColor;
        private ComboBox _cboFont;
        private CheckBox _chkBold;
        private CheckBox _chkItalic;
        private CheckBox _chkTemplate;
        private TextBox _txtTimeFormat;
        private CheckBox _chkLivePreview;
        private CheckBox _chkAllMonitors;
        private CheckBox _chkPhaseOffset;
        private CheckBox _chkClickThrough;
        private CheckBox _chkEnabled;
        private Button _btnApply;
        private Button _btnHide;
        private Button _btnSave;
        private Button _btnReset;

        // 从配置回填控件时把事件掐掉，否则回填会触发一遍实时预览，白费一次重画。
        private bool _suppress;
        private Timer _debounce;

        /// <summary>实时预览开启、且控件变化时调用。控制器负责重画水印。</summary>
        public Action OnPreview;
        /// <summary>「应用」：把控件值全部写进配置并重画。</summary>
        public Action OnApply;
        /// <summary>「保存配置」。</summary>
        public Action OnSave;
        /// <summary>「隐藏水印」按钮。</summary>
        public Action OnToggleVisible;
        /// <summary>「显示水印」勾选框，参数是想要的状态。</summary>
        public Action<bool> OnSetEnabled;

        public SettingsForm(Config config)
        {
            _config = config;

            Text = "ScreenWatermark 设置";
            FormBorderStyle = FormBorderStyle.FixedSingle;
            MaximizeBox = false;
            MinimizeBox = false;
            ShowInTaskbar = true;
            StartPosition = FormStartPosition.CenterScreen;
            // 高度要放得下最下面的提示行（y=546，高 44）—— 两行文字在 175% DPI 下
            // 需要 590 以上，560 会把提示行整块裁掉。宽度 700 是为了最右一列控件
            // （x=482 的勾选框）不被右边裁掉。
            ClientSize = new Size(1060, 604);
            Font = new Font("Microsoft YaHei UI", 9f);

            BuildControls();
            LoadFrom(_config);

            // 用户拖滑块时每一格都重画会卡；50ms 的合并窗口既够"立刻"又不抖。
            _debounce = new Timer();
            _debounce.Interval = 50;
            _debounce.Tick += delegate
            {
                _debounce.Stop();
                if (OnPreview != null) OnPreview();
            };
        }

        // ================= 控件搭建 =================
        // 手写坐标而不是 TableLayoutPanel：行数固定、就这一屏，手写更好对齐也更好改。

        // 各列的 x 坐标。全部来自 --dump-labels 的实测值：
        // 9pt 微软雅黑 UI 在 175% DPI 下，一个汉字 24px，四字标签 96px。
        // Label 自身左右各还有约 6px 内边距，所以"标签 x + 108"才是安全的下一个控件起点。
        private const int LabX1 = 12;      // 第一列标签
        private const int Col1 = 148;      // 第一列控件（LabX1 + 96 + 40 余量）
        private const int LabX2 = 324;     // 第二组标签
        private const int Col2 = 424;      // 第二组控件
        private const int LabX3 = 540;     // 第三组标签
        private const int Col3 = 664;      // 第三组控件（LabX3 + "模板与时间" 116px + 余量）
        private const int Col4 = 780;      // 最右侧一列
        private const int NumW = 70;       // 数值输入框统一宽度

        private void BuildControls()
        {
            const int gap = 38;
            // 滑块行行距必须 > 滑块高度(80) + 行内偏移(28)，否则滑块会盖住下一行。
            const int sliderGap = 114;
            const int sliderTop = 30;
            int y = 14;

            AddLabel("水印文本", LabX1, y + 3);
            _txtText = new TextBox();
            _txtText.Location = new Point(Col1, y);
            _txtText.Width = 388;
            _txtText.TextChanged += delegate { OnAnyChange(); };
            Controls.Add(_txtText);
            y += gap;

            AddLabel("字体大小", LabX1, y + 3);
            _numFontSize = new NumericUpDown();
            _numFontSize.Location = new Point(Col1, y);
            _numFontSize.Width = NumW;
            _numFontSize.Minimum = 8;
            _numFontSize.Maximum = 400;
            _numFontSize.ValueChanged += delegate { OnAnyChange(); };
            Controls.Add(_numFontSize);

            AddLabel("字体名称", LabX2, y + 3);
            _cboFont = new ComboBox();
            _cboFont.Location = new Point(Col2, y);
            _cboFont.Width = 252;
            _cboFont.DropDownStyle = ComboBoxStyle.DropDown; // 可下拉可选，也能手打字
            _cboFont.Items.AddRange(WatermarkRenderer.InstalledFamilies());
            _cboFont.TextChanged += delegate { OnAnyChange(); };
            _cboFont.SelectedIndexChanged += delegate { OnAnyChange(); };
            Controls.Add(_cboFont);
            y += gap;

            AddLabel("不透明度", LabX1, y + 4);
            _barOpacity = new TrackBar();
            _barOpacity.Location = new Point(Col1, y + sliderTop);
            _barOpacity.Width = 318;
            // 不要去写 _barOpacity.Height：WinForms 会把 TrackBar 顶回它的最小高度
            // （滑块 + 刻度，本机 175% DPI 下是 80px），设了也没用。
            // 既然改不了高度，就得让行距容得下它 —— 这就是 sliderGap 的理由。
            _barOpacity.Minimum = 1;
            _barOpacity.Maximum = 100;
            _barOpacity.TickFrequency = 10;
            _barOpacity.ValueChanged += delegate
            {
                _lblOpacityValue.Text = _barOpacity.Value.ToString() + "%";
                OnAnyChange();
            };
            Controls.Add(_barOpacity);
            _lblOpacityValue = new Label();
            _lblOpacityValue.AutoSize = true;
            _lblOpacityValue.Location = new Point(476, y + 3);
            Controls.Add(_lblOpacityValue);
            y += sliderGap;

            AddLabel("旋转角度", LabX1, y + 4);
            _barAngle = new TrackBar();
            _barAngle.Location = new Point(Col1, y + sliderTop);
            _barAngle.Width = 318;
            _barAngle.Minimum = -90;
            _barAngle.Maximum = 90;
            _barAngle.TickFrequency = 15;
            _barAngle.ValueChanged += delegate
            {
                _lblAngleValue.Text = _barAngle.Value.ToString() + "°";
                OnAnyChange();
            };
            Controls.Add(_barAngle);
            _lblAngleValue = new Label();
            _lblAngleValue.AutoSize = true;
            _lblAngleValue.Location = new Point(476, y + 3);
            Controls.Add(_lblAngleValue);
            y += sliderGap;

            AddLabel("水平间距", LabX1, y + 3);
            _numGapX = new NumericUpDown();
            _numGapX.Location = new Point(Col1, y);
            _numGapX.Width = NumW;
            _numGapX.Minimum = 0;
            _numGapX.Maximum = 2000;
            _numGapX.ValueChanged += delegate { OnAnyChange(); };
            Controls.Add(_numGapX);

            AddLabel("垂直间距", LabX2, y + 3);
            _numGapY = new NumericUpDown();
            _numGapY.Location = new Point(Col2, y);
            _numGapY.Width = NumW;
            _numGapY.Minimum = 0;
            _numGapY.Maximum = 2000;
            _numGapY.ValueChanged += delegate { OnAnyChange(); };
            Controls.Add(_numGapY);
            y += gap;

            AddLabel("行距倍数", LabX1, y + 6);
            _numLineSpacing = new NumericUpDown();
            _numLineSpacing.Location = new Point(Col1, y);
            _numLineSpacing.Width = NumW;
            _numLineSpacing.DecimalPlaces = 2;
            _numLineSpacing.Increment = 0.05m;
            _numLineSpacing.Minimum = 0.5m;
            _numLineSpacing.Maximum = 3.0m;
            _numLineSpacing.ValueChanged += delegate { OnAnyChange(); };
            Controls.Add(_numLineSpacing);

            AddLabel("文字颜色", LabX2, y + 3);
            _btnColor = new Button();
            _btnColor.Location = new Point(Col2, y - 2);
            _btnColor.Size = new Size(90, 26);
            _btnColor.FlatStyle = FlatStyle.Flat;
            _btnColor.Click += BtnColor_Click;
            Controls.Add(_btnColor);

            // 勾选框的 Text 需要文字宽 + 约 16px 的勾选图形，宽度按实测值给。
            _chkBold = MakeCheck("粗体", LabX3, y + 2, 84);
            _chkItalic = MakeCheck("斜体", LabX3 + 92, y + 2, 84);
            y += gap;

            _chkClickThrough = MakeCheck("鼠标穿透", Col1, y + 2, 118);
            _chkEnabled = MakeCheck("显示水印", Col1 + 158, y + 2, 118);
            AddLabel("模板与时间", LabX3, y + 3);
            _chkTemplate = MakeCheck("模板变量", Col3, y + 2, 118);
            y += gap;

            _chkLivePreview = MakeCheck("实时预览（改任何选项立刻重画）", Col1, y + 2, 340);
            _chkAllMonitors = MakeCheck("全部显示器", Col4, y + 2, 126);
            AddLabel("时间格式", LabX3, y + 3);
            _txtTimeFormat = new TextBox();
            _txtTimeFormat.Location = new Point(Col3, y);
            _txtTimeFormat.Width = 110;   // 右边缘 774，给"全部显示器"(x=780) 让出位置
            _txtTimeFormat.TextChanged += delegate { OnAnyChange(); };
            Controls.Add(_txtTimeFormat);
            y += gap;

            _chkPhaseOffset = MakeCheck("行错位（奇数行错开半格）", Col1, y + 2, 292);
            y += gap + 6;

            _btnApply = MakeButton("应用", LabX1, y, 110, BtnApply_Click);
            _btnHide = MakeButton("隐藏水印", LabX1 + 118, y, 110, delegate { Fire(OnToggleVisible); SyncEnabledCheckbox(); });
            _btnSave = MakeButton("保存配置", LabX1 + 236, y, 110, delegate { Fire(OnSave); });
            _btnReset = MakeButton("重置默认", LabX1 + 354, y, 110, BtnReset_Click);
            y += 44;

            _hint = new Label();
            _hint.Location = new Point(LabX1, y);
            _hint.AutoSize = false;
            _hint.Width = 1036;
            _hint.Height = 44;
            _hint.ForeColor = Color.FromArgb(0x55, 0x55, 0x55);
            Controls.Add(_hint);

            // 先放一份保守文案，真实的生效组合由控制器在注册完成后回填 ——
            // Ctrl+Alt+W/Q 在很多机器上被别的软件占了，会被降级成带 Shift 的版本。
            SetHotkeyInfo(null);
        }

        /// <summary>
        /// 建一个勾选框。宽度交给 WinForms 自己量（AutoSize）。
        ///
        /// 为什么不用固定宽度：175% DPI 下一个汉字比按 96 DPI 估出来的宽，
        /// 手算的宽度会差十几个像素，症状是勾选框文字被截尾（"全部显示器"变成"全部显示"），
        /// 而几何自检只看控件框、看不出框里文字被截 —— 这种只能靠 AutoSize 根治。
        /// width 参数保留只为兼容调用点，实际由 AutoSize 决定。
        /// </summary>
        private CheckBox MakeCheck(string text, int x, int y, int width)
        {
            CheckBox c = new CheckBox();
            c.Text = text;
            c.Location = new Point(x, y);
            c.AutoSize = true;
            c.CheckedChanged += delegate { OnAnyChange(); };
            Controls.Add(c);
            return c;
        }

        /// <summary>
        /// 面板布局自检。返回 null 表示干净。
        ///
        /// 为什么要有这个：面板是手写绝对坐标的，而且滑块（TrackBar）在 WinForms 里
        /// 高度被强制到 80px、改不动。这类布局一旦有重叠，症状是"某些控件整块不见"
        /// —— 而且 DrawToBitmap 还能把它们画出来，靠肉眼看自检图会被骗过去。
        /// 所以每次显示面板都做一次几何自检，有问题就写日志，别让同类问题再漏。
        /// </summary>
        public string LayoutProblems()
        {
            System.Text.StringBuilder sb = new System.Text.StringBuilder();
            Rectangle client = ClientRectangle;

            for (int i = 0; i < Controls.Count; i++)
            {
                Control a = Controls[i];
                if (!a.Visible) continue;
                if (!client.Contains(a.Bounds))
                {
                    sb.Append(string.Format("被裁: {0} '{1}' bounds={2} 超出客户区 {3}\n",
                        a.GetType().Name, a.Text, a.Bounds, client));
                }
                for (int k = i + 1; k < Controls.Count; k++)
                {
                    Control b = Controls[k];
                    if (!b.Visible) continue;
                    Rectangle hit = Rectangle.Intersect(a.Bounds, b.Bounds);
                    // 阈值 2px：抗锯齿描边/焦点框这种 1px 级的擦边不算问题。
                    if (hit.Width > 2 && hit.Height > 2)
                    {
                        sb.Append(string.Format("重叠: {0}@{1} 与 {2}@{3} 相交 {4}x{5}\n",
                            a.GetType().Name, a.Bounds, b.GetType().Name, b.Bounds,
                            hit.Width, hit.Height));
                    }
                }
            }
            return sb.Length == 0 ? null : sb.ToString();
        }

        /// <summary>周游整棵 Controls 树并输出每个控件的类型 / 文本 / Bounds / Visible / 父容器。</summary>
        ///
        /// 为什么需要这个：面板布局是手写坐标的，"某个控件没出现"这种问题光看源码
        /// 看不出来 —— 可能是坐标算错、可能是被同级控件盖住、可能是超出 ClientSize
        /// 被裁掉，也可能压根忘了 Controls.Add。把实际树打出来才能一次定位。
        /// </summary>
        public string DumpControlTree()
        {
            System.Text.StringBuilder sb = new System.Text.StringBuilder();
            sb.Append("ClientSize = ").Append(ClientSize.Width).Append("x").Append(ClientSize.Height).Append('\n');
            sb.Append("AutoScaleMode = ").Append(AutoScaleMode.ToString())
              .Append("  AutoScaleDimensions = ").Append(AutoScaleDimensions.ToString()).Append('\n');
            sb.Append("Font = ").Append(Font.Name).Append(' ').Append(Font.SizeInPoints).Append("pt\n");
            sb.Append('\n');

            int count = 0;
            int clipped = 0;
            int overlapping = 0;
            DumpInto(sb, this, 0, ref count, ref clipped, ref overlapping);

            sb.Append('\n').Append("totals: controls=").Append(count)
              .Append("  clipped(超出 ClientSize)=").Append(clipped)
              .Append("  overlapping(同级互相压住)=").Append(overlapping).Append('\n');
            return sb.ToString();
        }

        private void DumpInto(System.Text.StringBuilder sb, Control parent, int depth,
            ref int count, ref int clipped, ref int overlapping)
        {
            if (depth > 4) return; // 面板只有一层，防呆

            // 用 ClientRectangle 而不是 Bounds：客户区才是真正能画东西的地方。
            Rectangle client = ClientRectangle;
            Control[] siblings = new Control[parent.Controls.Count];
            for (int i = 0; i < parent.Controls.Count; i++) siblings[i] = parent.Controls[i];

            for (int i = 0; i < parent.Controls.Count; i++)
            {
                Control c = parent.Controls[i];
                count++;

                string text = c.Text;
                if (text == null) text = "";
                text = text.Replace("\r", " ").Replace("\n", " ").Trim();
                if (text.Length > 26) text = text.Substring(0, 26) + "..";

                Rectangle b = c.Bounds;
                bool inClient = client.Contains(b);
                if (!inClient) clipped++;

                // 同级重叠检测：两个可见控件的矩形相交就算。
                // 手写绝对坐标的面板里，重叠是头号杀手 —— 后画的会整块盖住先画的，
                // 屏幕上表现为"控件不见了"，而 Controls 集合里它明明还在。
                // 阈值与 LayoutProblems 一致：1~2px 的擦边是抗锯齿/焦点框造成的，
                // 不算问题，否则日志全是噪声。
                string coverNote = "";
                bool covered = false;
                for (int k = 0; k < siblings.Length; k++)
                {
                    if (k == i) continue;
                    Control o = siblings[k];
                    if (!o.Visible || !c.Visible) continue;
                    Rectangle hit = Rectangle.Intersect(b, o.Bounds);
                    if (hit.Width > 2 && hit.Height > 2)
                    {
                        covered = true;
                        coverNote += string.Format(" [与 {0}@{1},{2},{3}x{4} 重叠 {5}x{6}]",
                            o.GetType().Name, o.Bounds.X, o.Bounds.Y, o.Bounds.Width, o.Bounds.Height,
                            hit.Width, hit.Height);
                    }
                }
                if (covered) overlapping++;

                sb.Append(new string(' ', depth * 2));
                sb.Append(string.Format("{0,-16} bounds=({1,4},{2,4} {3,4}x{4,3}) vis={5,-5} en={6,-5} ",
                    c.GetType().Name, b.X, b.Y, b.Width, b.Height,
                    c.Visible ? "True" : "False", c.Enabled ? "True" : "False"));
                if (!inClient) sb.Append("[CLIPPED] ");
                if (covered) sb.Append("[OVERLAP]");
                sb.Append("text='").Append(text).Append('\'');
                sb.Append("  parent=").Append(parent.GetType().Name);
                sb.Append(coverNote);
                sb.Append('\n');

                if (c.Controls.Count > 0) DumpInto(sb, c, depth + 1, ref count, ref clipped, ref overlapping);
            }
        }

        /// <summary>
        /// 刷新底部提示行（规格 §4 要求的第 14 项）。info 为 null 时显示默认说法。
        /// 必须写"实际生效"的组合：用户按 Ctrl+Alt+W 没反应时，得能在这行看到原因。
        /// </summary>
        public void SetHotkeyInfo(string info)
        {
            if (_hint == null) return;
            string line1;
            if (string.IsNullOrEmpty(info))
            {
                line1 = "快捷键：Ctrl+Alt+W 开关水印 · Ctrl+Alt+S 开关本面板 · Ctrl+Alt+Q 退出程序";
            }
            else
            {
                line1 = "当前生效的快捷键：" + info;
            }
            _hint.Text = line1 + "\r\n" +
                         "关掉本面板不会退出程序，水印继续挂着；退出请用托盘菜单或上面的退出快捷键。";
        }

        private Label _hint;
        private NumericUpDown _numLineSpacing;

        private void AddLabel(string text, int x, int y)
        {
            Label l = new Label();
            l.Text = text;
            // AutoSize=true：让标签按文字自己决定宽度。
            // 之前是 AutoSize=false + 固定宽度，结果中文标签在 175% DPI 下需要的宽度
            // 比我估的大（"旋转角度""水平间距"的最后一个字被 Label 自己截掉了，
            // 不是被别的控件压住 —— 定位这个坑花了不少时间）。实测四字标签 96px。
            l.AutoSize = true;
            l.Location = new Point(x, y);
            // 高度留够一行：TrackBar 在 175% DPI 下是 80px 高，而滑动行只比它高
            // 8px，标签比滑块晚画就会把滑块顶部盖掉一条。显式定高让溢出量可预测。
            l.Height = 20;
            Controls.Add(l);
        }

        private Button MakeButton(string text, int x, int y, int w, EventHandler handler)
        {
            Button b = new Button();
            b.Text = text;
            b.Location = new Point(x, y);
            b.Size = new Size(w, 30);
            b.Click += handler;
            Controls.Add(b);
            return b;
        }

        // ================= 配置 ←→ 控件 =================

        private void LoadFrom(Config c)
        {
            _suppress = true;
            try
            {
                _txtText.Text = c.Text;
                _numFontSize.Value = Clamp(c.FontSize, 8, 400);
                _cboFont.Text = c.FontFamily;
                _barOpacity.Value = Clamp((int)Math.Round(c.Opacity * 100.0), 1, 100);
                _lblOpacityValue.Text = _barOpacity.Value.ToString() + "%";
                _barAngle.Value = Clamp(c.Angle, -90, 90);
                _lblAngleValue.Text = _barAngle.Value.ToString() + "°";
                _numGapX.Value = Clamp(c.GapX, 0, 2000);
                _numGapY.Value = Clamp(c.GapY, 0, 2000);
                _numLineSpacing.Value = ClampDecimal((decimal)c.LineSpacing, 0.5m, 3.0m);
                _chkBold.Checked = c.Bold;
                _chkItalic.Checked = c.Italic;
                _chkClickThrough.Checked = c.ClickThrough;
                _chkEnabled.Checked = c.Enabled;
                _chkTemplate.Checked = c.Template;
                _txtTimeFormat.Text = c.TimeFormat;
                _chkAllMonitors.Checked = c.AllMonitors;
                _chkPhaseOffset.Checked = c.PhaseOffset;
                UpdateColorButton(Config.ParseColorHex(c.Color, Color.FromArgb(0x80, 0x80, 0x80)));
            }
            finally
            {
                _suppress = false;
            }
        }

        // 返回 int 而不是 decimal：NumericUpDown.Value / TrackBar.Value 都吃 decimal，
        // 但 Clamp 的调用点全是整数，返回 int 才能让 int 变量也能直接接。
        private static int Clamp(int v, int min, int max)
        {
            if (v < min) return min;
            if (v > max) return max;
            return v;
        }

        private static decimal ClampDecimal(decimal v, decimal min, decimal max)
        {
            if (v < min) return min;
            if (v > max) return max;
            return v;
        }

        /// <summary>控件 → 配置。OnApply / 实时预览都走这里。</summary>
        public void WriteToConfig(Config c)
        {
            c.Text = _txtText.Text;
            c.FontSize = (int)_numFontSize.Value;
            if (!string.IsNullOrEmpty(_cboFont.Text)) c.FontFamily = _cboFont.Text;
            c.Opacity = Math.Round(_barOpacity.Value / 100.0, 4);
            c.Angle = _barAngle.Value;
            c.GapX = (int)_numGapX.Value;
            c.GapY = (int)_numGapY.Value;
            c.LineSpacing = (double)_numLineSpacing.Value;
            c.Bold = _chkBold.Checked;
            c.Italic = _chkItalic.Checked;
            c.ClickThrough = _chkClickThrough.Checked;
            c.Template = _chkTemplate.Checked;
            if (!string.IsNullOrEmpty(_txtTimeFormat.Text)) c.TimeFormat = _txtTimeFormat.Text;
            c.AllMonitors = _chkAllMonitors.Checked;
            c.PhaseOffset = _chkPhaseOffset.Checked;
            // Enabled 故意不在这里写：它由"显示水印"勾选框 / 快捷键 / 托盘三条路共同决定，
            // 混进来会互相覆盖（面板每次回填都会把它按磁盘上的旧值翻回去）。
        }

        /// <summary>外部（快捷键 / 托盘）改了显示状态后，把勾选框同步回来。</summary>
        public void SyncEnabledCheckbox()
        {
            _suppress = true;
            try { _chkEnabled.Checked = _config.Enabled; }
            finally { _suppress = false; }
        }

        public void SyncAll()
        {
            LoadFrom(_config);
        }

        // ================= 事件 =================

        /// <summary>控件变动统一入口：实时预览开着才重画，并且走 50ms 合并。</summary>
        private void OnAnyChange()
        {
            if (_suppress) return;
            if (!_chkLivePreview.Checked) return;
            _debounce.Stop();
            _debounce.Start();
        }

        private void BtnApply_Click(object sender, EventArgs e)
        {
            Fire(OnApply);
        }

        private void BtnReset_Click(object sender, EventArgs e)
        {
            _config.ResetToDefaults();
            LoadFrom(_config);
            Fire(OnApply);
            Fire(OnSave);
        }

        private void BtnColor_Click(object sender, EventArgs e)
        {
            using (ColorDialog dlg = new ColorDialog())
            {
                dlg.FullOpen = true;
                dlg.AnyColor = true;
                dlg.Color = Config.ParseColorHex(_config.Color, Color.FromArgb(0x80, 0x80, 0x80));
                if (dlg.ShowDialog(this) == DialogResult.OK)
                {
                    _config.Color = Config.ToHex(dlg.Color);
                    UpdateColorButton(dlg.Color);
                    OnAnyChange();
                }
            }
        }

        private void UpdateColorButton(Color c)
        {
            _btnColor.BackColor = c;
            _btnColor.Text = Config.ToHex(c);
            // 深色底要换白字，不然按钮上的十六进制看不见。
            int luma = (c.R * 299 + c.G * 587 + c.B * 114) / 1000;
            _btnColor.ForeColor = luma < 128 ? Color.White : Color.Black;
        }

        private static void Fire(Action a)
        {
            if (a != null) a();
        }

        /// <summary>
        /// 每次显示都跑一次布局自检。面板是手写绝对坐标 + 80px 高的不可缩滑块，
        /// 一旦有重叠就会出现"控件整块不见"，而且自检位图还会骗人（DrawToBitmap
        /// 逐个控件画，不经过真实 z 序）。所以把检查放在显示路径上，有问题立刻进日志。
        /// </summary>
        protected override void OnShown(EventArgs e)
        {
            base.OnShown(e);
            PerformLayout();
            string problems = LayoutProblems();
            if (problems != null)
            {
                Log.Warn("设置面板布局自检发现问题：\n" + problems);
            }
        }

        /// <summary>
        /// 关掉面板不退出程序（规格 §4）。这里 Cancel 掉关闭，只 Hide。
        /// 真正的退出只有托盘菜单和 Ctrl+Alt+Q 两条路。
        /// </summary>
        protected override void OnFormClosing(FormClosingEventArgs e)
        {
            if (e.CloseReason == CloseReason.UserClosing)
            {
                e.Cancel = true;
                Hide();
                return;
            }
            base.OnFormClosing(e);
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing && _debounce != null)
            {
                _debounce.Dispose();
                _debounce = null;
            }
            base.Dispose(disposing);
        }
    }
}
