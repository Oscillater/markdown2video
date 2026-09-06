"""Run 目录制：每次执行一个独立目录，永不覆盖、永不删除。

run_id = 本地时间戳 + 短随机后缀：时间戳保证字典序即可排序（同一 run 根
目录下列出即按时间排序），随机后缀保证同秒内多次 run 也全局唯一。产物
的归属与失效判断只靠 run_id 和命名，不做任何自动清理（用户拍板：产物
只增不删）。
"""
from __future__ import annotations

import re
import secrets
from datetime import datetime
from pathlib import Path

RUN_ID_PATTERN = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")


def new_run_id(now: datetime | None = None) -> str:
    """生成可排序、全局唯一的 run id：YYYYMMDD-HHMMSS-xxxxxx。"""
    timestamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    return f"{timestamp}-{secrets.token_hex(3)}"


def create_run_dir(runs_root: Path, run_id: str) -> Path:
    """在 runs_root 下创建 run 目录；已存在即抛错（绝不覆盖旧 run）。"""
    if not RUN_ID_PATTERN.match(run_id):
        raise ValueError(f"Invalid run id: {run_id!r}")
    run_dir = Path(runs_root) / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir
