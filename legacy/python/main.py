"""入口：python main.py [--text "xxx"] [--config path] [--no-tray] [--check] [-v]

注意顺序：DPI 感知必须在 import tkinter 之前调用，否则 Tk 先按 96 DPI 建好解释器，
在多屏不同缩放的机器上坐标就全歪了。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 允许直接 `python main.py` 和 `python -m watermark` 两种用法
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from watermark import __version__  # noqa: E402
from watermark import win32  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ScreenWatermark",
        description="屏幕水印：点得穿的半透明文字层，录屏和截图都能追责。",
    )
    parser.add_argument("-v", "--version", action="version", version=f"ScreenWatermark {__version__} (Python)")
    parser.add_argument("--config", metavar="PATH", help="指定配置文件路径（默认脚本同级 config.json）")
    parser.add_argument("--text", metavar="TEXT", help="临时覆盖水印文字，不写回配置文件")
    parser.add_argument("--no-tray", action="store_true", help="不创建托盘图标，只跑水印（托盘被占用时好用）")
    parser.add_argument("--show-panel", action="store_true", help="启动时就把设置面板显示出来")
    parser.add_argument("--check", action="store_true", help="只打印显示器/字体/平铺参数，不开窗口")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # 一定要最早
    win32.set_dpi_awareness()

    from watermark import config as cfgmod

    try:
        cfg = cfgmod.load(Path(args.config) if args.config else None)
    except Exception as exc:  # 配置彻底读不了也要能起来
        print(f"[main] 载入配置失败({exc!r})，使用默认值", file=sys.stderr)
        cfg = cfgmod.Config()

    if args.text is not None:
        cfg.text = args.text
        cfg.text_override = True
    if args.check:
        from watermark import app as appmod

        try:
            appmod.diagnostic(cfg)
        except Exception as exc:
            print(f"[main] 自检失败: {exc!r}", file=sys.stderr)
            return 2
        return 0

    try:
        import tkinter  # noqa: F401
    except ImportError:
        print("[main] 找不到 tkinter，请安装带 Tk 的 Python（官方安装包默认带）", file=sys.stderr)
        return 2

    from watermark import app as appmod

    try:
        application = appmod.App(
            cfg,
            use_tray=not args.no_tray,
            # --show-panel 之前只解析了没用，面板永远藏着；这里真的把它接上
            start_hidden_panel=not args.show_panel,
        )
    except Exception as exc:
        # §9：致命错误才允许弹窗，其余走 stderr
        print(f"[main] 启动失败: {exc!r}", file=sys.stderr)
        return 1
    print(
        f"[main] ScreenWatermark {__version__} 已启动：显示器 {len(application.monitors)} 块，"
        f"配置 {cfg.path}",
        flush=True,
    )
    return application.run()


if __name__ == "__main__":
    raise SystemExit(main())
