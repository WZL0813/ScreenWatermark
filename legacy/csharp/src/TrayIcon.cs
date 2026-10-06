// TrayIcon.cs —— 托盘图标 + 右键菜单。
//
// 为什么要单独一个类：WinForms 的 NotifyIcon 必须挂在消息循环活着的线程上，
// 由 AppController 统一管生命周期，托盘自己不该知道配置长什么样。
using System;
using System.Drawing;
using System.Windows.Forms;

namespace ScreenWatermark
{
    internal sealed class TrayIcon : IDisposable
    {
        private readonly NotifyIcon _icon;
        private readonly ContextMenuStrip _menu;
        private readonly ToolStripMenuItem _itemToggle;
        private readonly ToolStripMenuItem _itemSettings;
        private readonly ToolStripMenuItem _itemReload;
        private readonly ToolStripMenuItem _itemAutostart;
        private readonly ToolStripMenuItem _itemExit;

        public Action OnToggleVisible;
        public Action OnOpenSettings;
        public Action OnReloadConfig;
        public Action<bool> OnToggleAutostart;
        public Action OnExit;

        public TrayIcon()
        {
            _menu = new ContextMenuStrip();
            _menu.ShowImageMargin = false;

            _itemToggle = new ToolStripMenuItem("隐藏水印");
            _itemToggle.Click += delegate { Fire(OnToggleVisible); };

            _itemSettings = new ToolStripMenuItem("设置…");
            _itemSettings.Click += delegate { Fire(OnOpenSettings); };

            _itemReload = new ToolStripMenuItem("重新载入配置");
            _itemReload.Click += delegate { Fire(OnReloadConfig); };

            _itemAutostart = new ToolStripMenuItem("开机自启");
            _itemAutostart.CheckOnClick = false; // 勾选状态由配置决定，不让菜单自己翻
            _itemAutostart.Click += delegate
            {
                bool want = !_itemAutostart.Checked;
                if (OnToggleAutostart != null) OnToggleAutostart(want);
            };

            _itemExit = new ToolStripMenuItem("退出");
            _itemExit.Click += delegate { Fire(OnExit); };

            // 分隔线：把"危险操作"和日常开关分开，少点误触。
            _menu.Items.Add(_itemToggle);
            _menu.Items.Add(_itemSettings);
            _menu.Items.Add(_itemReload);
            _menu.Items.Add(new ToolStripSeparator());
            _menu.Items.Add(_itemAutostart);
            _menu.Items.Add(new ToolStripSeparator());
            _menu.Items.Add(_itemExit);

            _icon = new NotifyIcon();
            _icon.Icon = LoadAppIcon();
            _icon.Text = "ScreenWatermark · 已启用";
            _icon.ContextMenuStrip = _menu;
            _icon.Visible = true;
            _icon.DoubleClick += delegate { Fire(OnOpenSettings); };
        }

        private static void Fire(Action a)
        {
            if (a != null) a();
        }

        /// <summary>
        /// 用 /win32icon 挂上去的图标取回自身图标；取不到就退回系统默认图标，
        /// 反正托盘不能没有图标（NotifyIcon.Icon 为 null 时图标区是空的，用户会以为程序没起来）。
        /// </summary>
        private static Icon LoadAppIcon()
        {
            try
            {
                Icon ic = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
                if (ic != null) return ic;
            }
            catch (Exception) { }
            try
            {
                string ico = System.IO.Path.Combine(
                    System.IO.Path.GetDirectoryName(Application.ExecutablePath), "res\\app.ico");
                if (System.IO.File.Exists(ico)) return new Icon(ico);
            }
            catch (Exception) { }
            return SystemIcons.Application;
        }

        public void UpdateState(bool enabled, bool autostart)
        {
            if (_icon == null) return;
            _icon.Text = enabled ? "ScreenWatermark · 已启用" : "ScreenWatermark · 已隐藏";
            _itemToggle.Text = enabled ? "隐藏水印" : "显示水印";
            _itemAutostart.Checked = autostart;
        }

        public void ShowBalloon(string title, string text)
        {
            try
            {
                _icon.BalloonTipTitle = title;
                _icon.BalloonTipText = text;
                _icon.ShowBalloonTip(3000);
            }
            catch (Exception) { }
        }

        public void Dispose()
        {
            if (_icon != null)
            {
                // 不先 Visible=false 的话，进程退出后托盘里会留个幽灵图标，鼠标划过去才消失。
                _icon.Visible = false;
                _icon.Dispose();
            }
            if (_menu != null) _menu.Dispose();
        }
    }
}
