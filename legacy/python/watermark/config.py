"""配置的读写与模板变量。

字段集合严格照 DESIGN.md §2；这里的 _DEFAULTS 就是"缺字段补齐"的真相来源。
写回时故意保留未知字段：这样以后 C++ 版加了新开关，Python 版跑一圈不会把它抹掉。
"""

from __future__ import annotations

import dataclasses
import getpass
import json
import os
import re
import socket
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# 环境变量名，用来把"配置文件实际落在哪"告诉测试脚本或用户
ENV_CONFIG_PATH = "SCREENWATERMARK_CONFIG"

# 与 §2 的字段顺序保持一致，方便人肉 diff 两个实现写出的文件
_DEFAULTS: dict[str, Any] = {
    "text": "内部资料 请勿外传",
    "font_family": "Microsoft YaHei",
    "font_size": 30,
    "bold": True,
    "italic": False,
    "color": "#808080",
    "opacity": 0.15,
    "angle": -30,
    "gap_x": 150,
    "gap_y": 120,
    "line_spacing": 1.2,
    "enabled": True,
    "click_through": True,
    "template": False,
    "time_format": "%Y-%m-%d %H:%M",
    "refresh_seconds": 30,
    "all_monitors": True,
    "phase_offset": True,
    "autostart": False,
}

# 已知字段的类型与取值范围。范围之外的值会被夹回来而不是丢弃，避免手改配置后整份被重置
_LIMITS: dict[str, tuple[float, float]] = {
    "font_size": (8, 400),
    "opacity": (0.01, 1.0),
    "angle": (-90, 90),
    "gap_x": (0, 2000),
    "gap_y": (0, 2000),
    "line_spacing": (0.5, 3.0),
    "refresh_seconds": (5, 3600),
}

_COLOR_RE = re.compile(r"^#([0-9a-fA-F]{6})$")


def app_dir() -> Path:
    """脚本/打包后的 exe 所在目录。PyInstaller 单文件模式下 __file__ 指向临时解包目录，不能用。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _dir_writable(path: Path) -> bool:
    """真去写一个探针文件，而不是看 os.access：Windows 上 access 对只读目录经常撒谎。"""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-probe"
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def default_config_path() -> Path:
    """§2：优先脚本同级；同级不可写（比如装在 Program Files）才回落 APPDATA。"""
    primary = app_dir()
    if _dir_writable(primary):
        return primary / "config.json"
    fallback = Path(os.environ.get("APPDATA", Path.home())) / "ScreenWatermark"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback / "config.json"


@dataclass
class Config:
    # 19 个字段全部来自 DESIGN.md §2
    text: str = "内部资料 请勿外传"
    font_family: str = "Microsoft YaHei"
    font_size: int = 30
    bold: bool = True
    italic: bool = False
    color: str = "#808080"
    opacity: float = 0.15
    angle: int = -30
    gap_x: int = 150
    gap_y: int = 120
    line_spacing: float = 1.2
    enabled: bool = True
    click_through: bool = True
    template: bool = False
    time_format: str = "%Y-%m-%d %H:%M"
    refresh_seconds: int = 30
    all_monitors: bool = True
    phase_offset: bool = True
    autostart: bool = False

    # 非持久化字段：--text 临时覆盖（写回磁盘时跳过）
    text_override: bool = False

    # 原始 JSON 里我们不认识的键，写回时原样带上
    unknown: dict[str, Any] = field(default_factory=dict)
    # 这份配置是从哪个文件来的
    path: Path | None = None


def _coerce(name: str, value: Any) -> Any:
    """按字段类型清洗单个值。任何异常都退回默认值，配置脏了也不该崩。"""
    default = _DEFAULTS[name]
    kind = type(default)
    try:
        if kind is bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return bool(value)
            if isinstance(value, str):
                return value.strip().lower() in ("1", "true", "yes", "on")
            return default
        if kind is int:
            # 布尔是 int 的子类，配置里写 true 不该变成 1
            if isinstance(value, bool):
                return default
            ivalue = int(float(value))
            lo, hi = _LIMITS[name]
            return max(int(lo), min(int(hi), ivalue))
        if kind is float:
            fvalue = float(value)
            lo, hi = _LIMITS[name]
            return max(float(lo), min(float(hi), fvalue))
        if kind is str:
            if isinstance(value, (dict, list)):
                return default
            return str(value)
    except (TypeError, ValueError):
        return default
    return default


def _clean_color(value: Any) -> str:
    if isinstance(value, str) and _COLOR_RE.match(value.strip()):
        return value.strip().upper()
    return _DEFAULTS["color"]


def from_mapping(raw: dict[str, Any], path: Path | None) -> Config:
    cfg = Config(path=path)
    for name, default in _DEFAULTS.items():
        if name not in raw:
            continue
        value = raw[name]
        setattr(cfg, name, _clean_color(value) if name == "color" else _coerce(name, value))
    cfg.unknown = {k: v for k, v in raw.items() if k not in _DEFAULTS}
    return cfg


def to_mapping(cfg: Config) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for name in _DEFAULTS:
        if name == "color":
            data[name] = _clean_color(getattr(cfg, name))
            continue
        value = getattr(cfg, name)
        # 浮点写成整齐的小数：0.15 而不是 0.15000000000000002
        if name in ("opacity", "line_spacing"):
            value = round(float(value), 4)
        data[name] = value
    data.update(cfg.unknown)
    return data


def _backup_bad_file(path: Path) -> Path:
    """坏文件不要删：改名成 config.bad.json，用户还能自己抢救内容。"""
    bad = path.with_name("config.bad.json")
    try:
        if bad.exists():
            bad.unlink()
        path.replace(bad)
    except OSError as exc:  # 备份失败也不能挡住启动
        print(f"[config] 备份坏配置失败: {exc}", file=sys.stderr)
    return bad


def load(path: Path | None = None) -> Config:
    target = Path(path) if path else default_config_path()
    if not target.exists():
        cfg = Config(path=target)
        save(cfg)  # 首次运行直接落盘，用户找得到文件
        return cfg
    try:
        raw_bytes = target.read_bytes()
        # 容忍 UTF-8 BOM：别的实现/记事本可能塞进来
        text = raw_bytes.decode("utf-8-sig")
        raw = json.loads(text)
        if not isinstance(raw, dict):
            raise ValueError("配置根节点不是对象")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[config] 解析失败({exc})，已备份为 config.bad.json 并使用默认值", file=sys.stderr)
        _backup_bad_file(target)
        cfg = Config(path=target)
        save(cfg)
        return cfg
    cfg = from_mapping(raw, target)
    return cfg


def save(cfg: Config, path: Path | None = None) -> Path:
    """UTF-8 无 BOM 写出；半截文件比没文件更糟，所以先写 .tmp 再 replace。"""
    target = Path(path) if path else (cfg.path or default_config_path())
    data = to_mapping(cfg)
    tmp = target.with_name(target.name + ".tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # ensure_ascii=False 让中文原样存；换行统一 LF，跨实现好读
        payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(payload)
        os.replace(tmp, target)
    except OSError as exc:
        print(f"[config] 保存失败 {target}: {exc}", file=sys.stderr)
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        # 同级目录写不了就回落 APPDATA，保证"保存配置"这个动作有结果
        if path is None and target != default_config_path():
            return save(cfg, default_config_path())
        raise
    cfg.path = target
    os.environ[ENV_CONFIG_PATH] = str(target)
    return target


def reset_to_defaults(cfg: Config) -> Config:
    """保留路径，其余回默认值；未知字段也清掉，因为"重置默认"就该干净。"""
    fresh = Config(path=cfg.path)
    return fresh


def primary_ipv4() -> str:
    """拿本机内网 IPv4。连一个外部地址只为让系统挑出口网卡，不会真发包。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return str(sock.getsockname()[0])
    except OSError:
        return ""
    finally:
        sock.close()


def _current_user() -> str:
    try:
        return getpass.getuser()
    except (OSError, KeyError, ImportError):
        return os.environ.get("USERNAME", "")


def _current_host() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return os.environ.get("COMPUTERNAME", "")


def expand_template(text: str, cfg: Config, now: datetime | None = None) -> str:
    """§3 的变量替换。`{{`/`}}` 是字面量大括号，所以先做转义占位再还原。"""
    if not cfg.template:
        return text
    moment = now or datetime.now()
    # 用不可能出现在文本里的私有区字符当占位符，避免和用户文本打架
    open_mark, close_mark = "\ue000", "\ue001"
    out = text.replace("{{", open_mark).replace("}}", close_mark)
    out = out.replace("{date}", moment.strftime("%Y-%m-%d"))
    out = out.replace("{time}", _strftime_safe(cfg.time_format, moment))
    out = out.replace("{user}", _current_user())
    out = out.replace("{host}", _current_host())
    out = out.replace("{ip}", primary_ipv4())
    out = out.replace(open_mark, "{").replace(close_mark, "}")
    return out


def _strftime_safe(fmt: str, moment: datetime) -> str:
    """time_format 是用户随手填的，非法格式符不能让定时器抛异常。"""
    try:
        return moment.strftime(fmt)
    except (ValueError, TypeError):
        return moment.strftime(_DEFAULTS["time_format"])


def has_time_variable(cfg: Config) -> bool:
    """只有真的会变的变量才值得起定时器；否则静置时零 CPU。"""
    return cfg.template and ("{time}" in cfg.text or "{date}" in cfg.text)


def as_dict(cfg: Config) -> dict[str, Any]:
    return dataclasses.asdict(cfg)
