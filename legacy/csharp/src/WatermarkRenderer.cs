// WatermarkRenderer.cs —— 把一个显示器尺寸的平铺水印画到一张 32bppPArgb 位图上。
//
// 这里是规格 §6 的逐像素约定，两个实现必须对得上：
//   cell_w = text_width + gap_x
//   cell_h = text_line_height * line_spacing + gap_y
//   从 -cell_w 铺到 宽+cell_w，-cell_h 铺到 高+cell_h（负起点是为了旋转后四边不留白）
//   phase_offset 时奇数行再错开半格
//
// 为什么先渲染成位图再贴：这是"预渲染"策略的前提。
// 每帧重画几百个单元会烧 CPU，规格 §10 第 10 条要求静置时 CPU 接近 0。
using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Drawing.Text;

namespace ScreenWatermark
{
    /// <summary>一张渲染好的水印图。Angle=0 时是"瓦片"，可以直接平铺；否则只能用整屏位图。</summary>
    internal sealed class WatermarkTile : IDisposable
    {
        public Bitmap Bitmap;
        public int Width;
        public int Height;
        public double Angle;

        public void Dispose()
        {
            if (Bitmap != null)
            {
                Bitmap.Dispose();
                Bitmap = null;
            }
        }
    }

    internal static class WatermarkRenderer
    {
        // 规格 §6：极端角度 / 间距组合下单元数上限 20000，超了就把格子等比撑大，而不是卡死。
        private const int MaxCells = 20000;

        /// <summary>
        /// 单行文字的实际盒宽（含行距折算前的原始值），设置面板要用它做布局，也能单独测。
        /// </summary>
        public static SizeF MeasureUnitText(string text, FontFamily family, float emPixels,
            bool bold, bool italic)
        {
            FontStyle style = FontStyle.Regular;
            if (bold) style |= FontStyle.Bold;
            if (italic) style |= FontStyle.Italic;

            using (Font font = new Font(family, emPixels, style, GraphicsUnit.Pixel))
            using (Bitmap scratch = new Bitmap(1, 1, PixelFormat.Format32bppArgb))
            using (Graphics g = Graphics.FromImage(scratch))
            {
                g.TextRenderingHint = TextRenderingHint.AntiAlias;
                using (StringFormat sf = MakeFormat())
                {
                    return g.MeasureString(text, font, PointF.Empty, sf);
                }
            }
        }

        /// <summary>
        /// 算平铺格子。返回的 SizeF 就是 cell_w / cell_h（已含 gap 和 line_spacing）。
        /// </summary>
        public static SizeF MeasureCell(string text, FontFamily family, float emPixels,
            bool bold, bool italic, double lineSpacing, int gapX, int gapY)
        {
            SizeF textSize = MeasureUnitText(text, family, emPixels, bold, italic);
            float cellW = textSize.Width + gapX;
            float cellH = (float)(textSize.Height * lineSpacing) + gapY;
            // 间距拉满到 0 也要留 1 像素步进，否则除零 / 死循环。
            if (cellW < 1f) cellW = 1f;
            if (cellH < 1f) cellH = 1f;
            return new SizeF(cellW, cellH);
        }

        /// <summary>
        /// 渲染一块屏幕的水印。返回的对象由调用方负责 Dispose。
        /// </summary>
        /// <param name="width">屏幕物理宽</param>
        /// <param name="height">屏幕物理高</param>
        /// <param name="gdiDpi">该显示器的 DPI（96 = 100% 缩放），字体磅值按它换算成像素</param>
        public static WatermarkTile Render(int width, int height, string text, string fontFamily,
            int fontSizePt, bool bold, bool italic, Color color, double opacity, int angle,
            int gapX, int gapY, double lineSpacing, bool phaseOffset, float gdiDpi)
        {
            if (width <= 0) width = 1;
            if (height <= 0) height = 1;
            if (text == null) text = string.Empty;
            if (gdiDpi <= 0f) gdiDpi = 96f;

            // 磅 → 像素：96 DPI 下 1pt = 96/72 px。用显式 gdiDpi 是绕开
            // Font 构造时按 Graphics 单位猜 DPI 的老坑，PerMonitorV2 下猜出来经常是错的。
            float emPixels = (float)(fontSizePt * gdiDpi / 72.0);
            if (emPixels < 1f) emPixels = 1f;

            FontFamily family = ResolveFamily(fontFamily);
            FontStyle style = FontStyle.Regular;
            if (bold) style |= FontStyle.Bold;
            if (italic) style |= FontStyle.Italic;

            // 一个像素都不透的时候没必要画，直接给张空图，省下几百个单元的绘制。
            int alpha = (int)Math.Round(opacity * 255.0);
            if (alpha < 0) alpha = 0;
            if (alpha > 255) alpha = 255;

            WatermarkTile tile = new WatermarkTile();
            tile.Width = width;
            tile.Height = height;
            tile.Angle = angle;

            Bitmap bmp = new Bitmap(width, height, PixelFormat.Format32bppPArgb);
            tile.Bitmap = bmp;
            if (alpha == 0 || text.Length == 0)
            {
                family.Dispose();
                return tile;
            }

            using (Font font = new Font(family, emPixels, style, GraphicsUnit.Pixel))
            using (Graphics g = Graphics.FromImage(bmp))
            {
                // 抗锯齿必须开：规格明确说了不要 TransparencyKey 就是为了保住这个边缘。
                g.SmoothingMode = SmoothingMode.AntiAlias;
                g.TextRenderingHint = TextRenderingHint.AntiAlias;
                g.PixelOffsetMode = PixelOffsetMode.HighQuality;
                g.InterpolationMode = InterpolationMode.HighQualityBicubic;

                // DrawString 而不是 TextRenderer.DrawText：后者走 GDI，不认 Graphics 的
                // 变换矩阵，旋转做不出来。
                using (StringFormat sf = MakeFormat())
                using (SolidBrush brush = new SolidBrush(Color.FromArgb(alpha, color)))
                {
                    Layout(g, bmp, text, font, sf, brush, angle, gapX, gapY, lineSpacing, phaseOffset);
                }
            }

            family.Dispose();
            return tile;
        }

        private static StringFormat MakeFormat()
        {
            StringFormat sf = (StringFormat)StringFormat.GenericTypographic.Clone();
            // NoWrap：长文本不许自己折行，折了单元宽度就不等于 text_width + gap_x 了。
            sf.FormatFlags |= StringFormatFlags.NoWrap | StringFormatFlags.MeasureTrailingSpaces;
            sf.Trimming = StringTrimming.None;
            return sf;
        }

        /// <summary>按 §6 铺满整屏。抽出来是为了让"算格子"和"画格子"能分开测。</summary>
        private static void Layout(Graphics g, Bitmap bmp, string text, Font font, StringFormat sf,
            SolidBrush brush, int angle, int gapX, int gapY, double lineSpacing, bool phaseOffset)
        {
            SizeF textSize;
            using (StringFormat measureFmt = MakeFormat())
            {
                textSize = g.MeasureString(text, font, PointF.Empty, measureFmt);
            }

            double cellW = textSize.Width + gapX;
            double cellH = textSize.Height * lineSpacing + gapY;
            if (cellW < 1.0) cellW = 1.0;
            if (cellH < 1.0) cellH = 1.0;

            int w = bmp.Width;
            int h = bmp.Height;

            // 先算需要多少格，超上限就整体撑大格子。撑大而不是抽稀：抽稀会出现空洞，
            // 撑大只是水印更疏，视觉上仍然均匀。
            double cols = (w + 2.0 * cellW) / cellW;
            double rows = (h + 2.0 * cellH) / cellH;
            if (cols < 1.0) cols = 1.0;
            if (rows < 1.0) rows = 1.0;
            double totalCells = cols * rows;
            if (totalCells > MaxCells)
            {
                double k = Math.Sqrt(totalCells / MaxCells);
                cellW *= k;
                cellH *= k;
            }

            int colsInt = (int)Math.Ceiling((w + 2.0 * cellW) / cellW);
            int rowsInt = (int)Math.Ceiling((h + 2.0 * cellH) / cellH);
            if (colsInt < 1) colsInt = 1;
            if (rowsInt < 1) rowsInt = 1;
            // 双保险：上面撑过一轮之后这里不该再超，但绝不让循环失控。
            if ((long)colsInt * rowsInt > MaxCells * 4)
            {
                return;
            }

            // 单元内部让文字居中，这样"格子"和字之间的留白是均匀的，
            // 只靠 gap 的话行与行之间的视觉间距会随字体度量飘。
            float offX = (float)((cellW - textSize.Width) / 2.0);
            float offY = (float)((cellH - textSize.Height) / 2.0);
            if (offX < 0f) offX = 0f;
            if (offY < 0f) offY = 0f;

            float halfCellW = (float)(cellW / 2.0);

            for (int row = 0; row < rowsInt; row++)
            {
                double y = -cellH + row * cellH;
                double rowShift = (phaseOffset && (row % 2 == 1)) ? halfCellW : 0.0;

                for (int col = 0; col < colsInt; col++)
                {
                    double x = -cellW + col * cellW + rowShift;

                    GraphicsState state = g.Save();
                    try
                    {
                        // 先平移再绕单元原点转，然后左对齐写字 —— §6 的原话顺序。
                        g.TranslateTransform((float)x, (float)y);
                        if (angle != 0) g.RotateTransform(angle);
                        g.DrawString(text, font, brush, offX, offY, sf);
                    }
                    finally
                    {
                        g.Restore(state);
                    }
                }
            }
        }

        /// <summary>
        /// 字体名找不到时退回系统默认 UI 字体（规格 §2）。绝不能因为用户手打错字体名就崩。
        /// </summary>
        public static FontFamily ResolveFamily(string name)
        {
            if (!string.IsNullOrEmpty(name))
            {
                try
                {
                    FontFamily f = new FontFamily(name.Trim());
                    return f;
                }
                catch (Exception) { }
            }
            try
            {
                FontFamily sys = SystemFonts.MessageBoxFont.FontFamily;
                if (sys != null) return sys;
            }
            catch (Exception) { }
            return FontFamily.GenericSansSerif;
        }

        public static bool FontExists(string name)
        {
            if (string.IsNullOrEmpty(name)) return false;
            try
            {
                using (FontFamily f = new FontFamily(name.Trim())) { return true; }
            }
            catch (Exception)
            {
                return false;
            }
        }

        public static string[] InstalledFamilies()
        {
            List<string> list = new List<string>();
            try
            {
                using (InstalledFontCollection col = new InstalledFontCollection())
                {
                    for (int i = 0; i < col.Families.Length; i++)
                    {
                        string n = col.Families[i].Name;
                        if (!string.IsNullOrEmpty(n)) list.Add(n);
                    }
                }
            }
            catch (Exception) { }
            if (list.Count == 0) list.Add(Config.DefFontFamily);
            list.Sort(StringComparer.CurrentCulture);
            return list.ToArray();
        }
    }
}
