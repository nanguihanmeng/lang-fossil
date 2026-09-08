"""离线 dead-package 快照数据库加载器.

Offline-first：快照随包分发，绝不访问网络。查找顺序：
``LANG_FOSSIL_DATA_DIR`` 环境变量覆盖 → 随包副本 → 仓库根 ``data/``
目录（源码检出场景）.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_ENV_OVERRIDE = "LANG_FOSSIL_DATA_DIR"  # 快照目录环境变量覆盖
_SNAPSHOT_NAME = "dead-packages.json"


class SnapshotError(ValueError):
    """快照文件存在但无法解析时抛出.

    继承 ValueError，使处理配置类错误的 CLI 错误边界（见
    :func:`lang_fossil.cli.app._load_engine`）能够一并处理.
    """


def locate_snapshot() -> Path | None:
    """定位 dead-package 快照文件.

    Returns:
        ``dead-packages.json`` 的路径；未找到时为 ``None``.
    """
    override = os.environ.get(_ENV_OVERRIDE)
    if override:
        candidate = Path(override) / _SNAPSHOT_NAME
        if candidate.is_file():
            return candidate

    packaged = Path(__file__).resolve().parents[1] / "data" / _SNAPSHOT_NAME
    if packaged.is_file():
        return packaged

    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "data" / _SNAPSHOT_NAME
        if candidate.is_file():
            return candidate
    return None


def load_snapshot(path: Path | None = None) -> dict[str, Any]:
    """加载并校验快照文档.

    Args:
        path: 显式快照路径；``None`` 使用 :func:`locate_snapshot`.

    Returns:
        解析后的快照字典（无快照时为空）.

    Raises:
        SnapshotError: 文件存在但不是合法 JSON/形状.
    """
    resolved = path or locate_snapshot()
    if resolved is None:
        return {}
    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SnapshotError(f"cannot read snapshot {resolved}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("packages"), list):
        raise SnapshotError(f"snapshot {resolved} must contain a 'packages' list")
    return data
