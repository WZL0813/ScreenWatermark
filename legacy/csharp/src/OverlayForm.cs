// OverlayForm.cs —— 每块显示器一个的分层水印窗口。
//
// 为什么用 UpdateLayeredWindow 而不是 TransparencyKey：
// TransparencyKey 是"这个颜色直接抠掉"，抗锯齿边缘的半透明像素（灰 50%）既不是文字色
// 也不是背景色，会被判成实心，于是文字边缘出现一圈硬锯齿/白边。
// UpdateLayeredWindow + Format32bppPArgb 是逐像素 alpha，边缘的 30%/70% 能原样保留。
using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.Windows.Forms;

namespace ScreenWatermark
{
    internal class OverlayForm : Form
    {
        private readonly Screen _screen;
        private readonly int _dpi;

        private WatermarkTile _tile;
        private bool _clickThrough = true;
        private bool _clickThroughApplied = true;

        /// <summary>最近一次贴图是否成功。AppController 用它判断要不要报警。</summary>
        public bool LastUpdateOk = true;

        /// <summary>最近一次 UpdateLayeredWindow 的 Win32 错误码，0 表示没出错。</summary>
        public int LastUpdateError;

        public Screen ScreenInfo { get { return _screen; } }
        public int Dpi { get { return _dpi; } }

        public OverlayForm(Screen screen, int dpi)
        {
            _screen = screen;
            _dpi = dpi <= 0 ? 96 : dpi;

            // 规格 §8 明确要求这几个属性：无边框、不进任务栏、手动定位、置顶。
            FormBorderStyle = FormBorderStyle.None;
            ShowInTaskbar = false;
            StartPosition = FormStartPosition.Manual;
            TopMost = true;
            MinimizeBox = false;
            MaximizeBox = false;
            Text = "ScreenWatermark Overlay";
            // 别让 WinForms 自己去抢焦点/激活，样式位已经禁了，这里再配合一下。
            TabStop = false;

            Rectangle b = _screen.Bounds;
            // 先放到屏幕外：窗口创建和第一次 UpdateLayeredWindow 之间不能让人看见一个空洞。
            SetBounds(-32000, -32000, b.Width, b.Height);
        }

        protected override CreateParams CreateParams
        {
            get
            {
                CreateParams cp = base.CreateParams;

                // 分层 + 穿透 + 工具窗（不在 Alt+Tab / 任务栏）+ 不激活。
                // 0x08000000 就是 WS_EX_NOACTIVATE，规格要求带上。
                cp.ExStyle |= NativeMethods.WS_EX_LAYERED
                            | NativeMethods.WS_EX_TRANSPARENT
                            | NativeMethods.WS_EX_TOOLWINDOW
                            | NativeMethods.WS_EX_NOACTIVATE;

                // 保险：确保没有被继承来的 APPWINDOW 拉进任务栏。
                cp.ExStyle &= ~NativeMethods.WS_EX_APPWINDOW;
                cp.Style = NativeMethods.WS_POPUP | NativeMethods.WS_VISIBLE;
                return cp;
            }
        }

        /// <summary>
        /// 全屏覆盖窗口不需要重绘背景 —— 画面完全由 UpdateLayeredWindow 提供。
        /// 不重写的话 WinForms 会先刷一遍系统色，在分层窗口上表现为一次白闪。
        /// </summary>
        protected override void OnPaintBackground(PaintEventArgs e)
        {
            // 故意留空
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            // 同上：内容不走 WM_PAINT。
        }

        protected override void SetVisibleCore(bool value)
        {
            // WS_EX_NOACTIVATE 已经保证不抢焦点；这里再压一层。
            base.SetVisibleCore(value);
        }

        /// <summary>切换到指定屏幕（显示器插拔或配置变化后重建时用）。</summary>
        public void MoveTo(Rectangle bounds)
        {
            SetBounds(bounds.X, bounds.Y, bounds.Width, bounds.Height);
            IntPtr h = Handle;
            if (h != IntPtr.Zero)
            {
                NativeMethods.SetWindowPos(h, NativeMethods.HWND_TOPMOST, bounds.X, bounds.Y,
                    bounds.Width, bounds.Height,
                    NativeMethods.SWP_NOACTIVATE | NativeMethods.SWP_NOOWNERZORDER);
            }
        }

        /// <summary>
        /// 装上新的水印位图。旧的那张在这里就地 Dispose —— 内存只涨不掉的原因就在这。
        /// </summary>
        public void SetTile(WatermarkTile tile)
        {
            WatermarkTile old = _tile;
            _tile = tile;
            if (old != null && !ReferenceEquals(old, tile))
            {
                old.Dispose();
                GC.SuppressFinalize(old);
            }
            ApplyTile();
        }

        /// <summary>把当前位图贴到窗口上。改尺寸 / 改 DPI 之后也要调一次。</summary>
        public void ApplyTile()
        {
            if (!IsHandleCreated) return;
            if (_tile == null || _tile.Bitmap == null) return;

            IntPtr screenDc = IntPtr.Zero;
            IntPtr memDc = IntPtr.Zero;
            IntPtr hBitmap = IntPtr.Zero;
            IntPtr oldBitmap = IntPtr.Zero;

            try
            {
                screenDc = NativeMethods.GetDC(IntPtr.Zero);
                if (screenDc == IntPtr.Zero) return;

                memDc = NativeMethods.CreateCompatibleDC(screenDc);
                if (memDc == IntPtr.Zero) return;

                // GetHbitmap 拿到的是 GDI 侧的一份拷贝，premultiplied alpha 由 32bppPArgb 保证。
                // 用完必须 DeleteObject，否则每次重画泄露一张全屏 GDI 位图（几 MB × 每次参数变动）。
                hBitmap = _tile.Bitmap.GetHbitmap(Color.FromArgb(0));
                if (hBitmap == IntPtr.Zero) return;

                oldBitmap = NativeMethods.SelectObject(memDc, hBitmap);

                Rectangle bounds = _screen.Bounds;

                NativeMethods.SIZE size = new NativeMethods.SIZE(_tile.Width, _tile.Height);
                NativeMethods.POINT src = new NativeMethods.POINT(0, 0);
                NativeMethods.POINT dst = new NativeMethods.POINT(bounds.X, bounds.Y);

                NativeMethods.BLENDFUNCTION blend = new NativeMethods.BLENDFUNCTION();
                blend.BlendOp = NativeMethods.AC_SRC_OVER;
                blend.BlendFlags = 0;
                blend.SourceConstantAlpha = 255; // 整体不透明度已经烘焙进文字颜色的 alpha，这里必须 255
                blend.AlphaFormat = NativeMethods.AC_SRC_ALPHA;

                bool ok = NativeMethods.UpdateLayeredWindow(Handle, screenDc, ref dst, ref size,
                    memDc, ref src, 0, ref blend, NativeMethods.ULW_ALPHA);

                LastUpdateOk = ok;
                LastUpdateError = ok ? 0 : System.Runtime.InteropServices.Marshal.GetLastWin32Error();
            }
            catch (Exception)
            {
                LastUpdateOk = false;
                LastUpdateError = -1;
            }
            finally
            {
                if (memDc != IntPtr.Zero && oldBitmap != IntPtr.Zero)
                    NativeMethods.SelectObject(memDc, oldBitmap);
                if (memDc != IntPtr.Zero) NativeMethods.DeleteDC(memDc);
                if (hBitmap != IntPtr.Zero) NativeMethods.DeleteObject(hBitmap);
                if (screenDc != IntPtr.Zero) NativeMethods.ReleaseDC(IntPtr.Zero, screenDc);
            }
        }

        /// <summary>
        /// click_through=false 时把 WS_EX_TRANSPARENT 摘掉，窗口才会真的挡鼠标（规格 §2 说这是调试用）。
        /// 注意：这是双刃剑——挡住之后桌面就点不动了，所以设置面板才要能关掉。
        /// </summary>
        public void SetClickThrough(bool clickThrough)
        {
            _clickThrough = clickThrough;
            ApplyClickThrough();
        }

        private void ApplyClickThrough()
        {
            if (!IsHandleCreated) return;
            if (_clickThrough == _clickThroughApplied) return;

            try
            {
                long ex = NativeMethods.GetWindowLongPtr(Handle, NativeMethods.GWL_EXSTYLE);
                if (_clickThrough) ex |= NativeMethods.WS_EX_TRANSPARENT;
                else ex &= ~(long)NativeMethods.WS_EX_TRANSPARENT;
                NativeMethods.SetWindowLongPtr(Handle, NativeMethods.GWL_EXSTYLE, ex);
                _clickThroughApplied = _clickThrough;
            }
            catch (Exception)
            {
                // 改不了就保持原样：穿透总比挡住桌面安全。
            }
        }

        /// <summary>每 3 秒被控制器叫一次，重新顶到最前面，防止被别的置顶窗口盖住。</summary>
        public void RefreshTopmost()
        {
            if (!IsHandleCreated) return;
            NativeMethods.SetWindowPos(Handle, NativeMethods.HWND_TOPMOST, 0, 0, 0, 0,
                NativeMethods.SWP_NOMOVE | NativeMethods.SWP_NOSIZE | NativeMethods.SWP_NOACTIVATE
                | NativeMethods.SWP_NOOWNERZORDER);
        }

        protected override void OnHandleCreated(EventArgs e)
        {
            base.OnHandleCreated(e);
            _clickThroughApplied = _clickThrough;
            ApplyClickThrough();
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing && _tile != null)
            {
                _tile.Dispose();
                _tile = null;
            }
            base.Dispose(disposing);
        }
    }
}
