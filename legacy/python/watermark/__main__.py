"""支持 `python -m watermark`。行为与 `python main.py` 完全一致。"""

from __future__ import annotations

import sys
from pathlib import Path

# 包被当成模块执行时，包目录自己不在 sys.path 上，得手动补一次才能 import main
_PACKAGE_DIR = Path(__file__).resolve().parent
if str(_PACKAGE_DIR) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_DIR))

from main import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
