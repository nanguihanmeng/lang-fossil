"""Loader for the offline dead-package snapshot database.

Offline-first: the snapshot ships with the package; no network access is
ever performed. Lookup order: ``LANG_FOSSIL_DATA_DIR`` env override, the
packaged copy, then a repo-root ``data/`` directory (source checkouts).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_ENV_OVERRIDE = "LANG_FOSSIL_DATA_DIR"
_SNAPSHOT_NAME = "dead-packages.json"


class SnapshotError(ValueError):
    """Raised when a snapshot file exists but cannot be parsed.

    Subclasses ValueError so CLI error boundaries that translate config-ish
    failures (see :func:`lang_fossil.cli.app._load_engine`) handle it.
    """


def locate_snapshot() -> Path | None:
    """Locate the dead-package snapshot file.

    Returns:
        Path to ``dead-packages.json``, or ``None`` if not found.
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
    """Load and validate the snapshot document.

    Args:
        path: Explicit snapshot path; ``None`` uses :func:`locate_snapshot`.

    Returns:
        The parsed snapshot dict (possibly empty when no snapshot exists).

    Raises:
        SnapshotError: If the file exists but is not valid JSON/shape.
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
