"""Content-hash scan cache backed by sqlite3.

Cache keys are ``sha256(source + rules digest + zombie snapshot version)``.
The stored payload bundles fossil dicts *and* the source parse errors, so a
cache hit reproduces the full first-run result. Identical content under a
renamed path hits the cache, which is correct because the cache payload is
pathless where it matters: paths are re-attached to the *current* ``path`` at
retrieval time by the caller.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS results (
    key TEXT PRIMARY KEY,
    fossils TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""


class ScanCache:
    """Small sqlite3-backed key/value cache for per-file scan results."""

    def __init__(self, path: Path, enabled: bool = True) -> None:
        """Open (and lazily create) the cache database.

        Args:
            path: Database file path; parent directories are created.
            enabled: When False the cache degrades to a no-op.
        """
        self._enabled = enabled
        self._conn: sqlite3.Connection | None = None
        # ponytail: one shared connection + lock; workers hit the cache from
        # the scan thread pool. Shard per worker only if cache throughput
        # ever shows up in a profile.
        self._lock = threading.Lock()
        if not enabled:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # check_same_thread=False: scan workers share this connection.
            self._conn = sqlite3.connect(path, check_same_thread=False)
            self._conn.execute(_SCHEMA)
            self._conn.commit()
        except sqlite3.Error:
            # Cache is best-effort: never let it break a scan.
            self._conn = None

    @staticmethod
    def make_key(source: str, rules_digest: str) -> str:
        """Compute a cache key from content and the active rule set.

        Args:
            source: Full source text of the file.
            rules_digest: Stable digest of the loaded rule set.

        Returns:
            Hex digest usable as a cache key.
        """
        return hashlib.sha256(source.encode("utf-8", "replace") + rules_digest.encode()).hexdigest()

    def _fetch_raw(self, key: str) -> str | None:
        """Read the raw JSON payload for a key.

        Args:
            key: Cache key from :meth:`make_key`.

        Returns:
            The stored JSON string, or ``None`` on a miss or any cache error.
        """
        if self._conn is None:
            return None
        try:
            with self._lock:
                row = self._conn.execute(
                    "SELECT fossils FROM results WHERE key = ?", (key,)
                ).fetchone()
        except sqlite3.Error:
            return None
        return row[0] if row is not None else None

    def get(self, key: str) -> dict[str, Any] | None:
        """Fetch the cached payload.

        Args:
            key: Cache key from :meth:`make_key`.

        Returns:
            A mapping with ``fossils`` (list) and ``errors`` (sequence), or
            ``None`` on a miss or any cache error.
        """
        raw = self._fetch_raw(key)
        if raw is None:
            return None
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return None
        if isinstance(data, dict) and "fossils" in data:
            return data
        if isinstance(data, list):  # legacy payload: bare fossil list, no errors
            return {"fossils": data, "errors": ()}
        return None

    def put(self, key: str, fossils: list[dict[str, Any]], errors: Any = ()) -> None:
        """Store a fossil payload (best-effort, errors ignored).

        Args:
            key: Cache key from :meth:`make_key`.
            fossils: JSON-serializable fossil dicts.
            errors: Source parse errors to reproduce on a cache hit.
        """
        if self._conn is None:
            return
        payload = {"fossils": fossils, "errors": list(errors)}
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT OR REPLACE INTO results (key, fossils) VALUES (?, ?)",
                    (key, json.dumps(payload)),
                )
                self._conn.commit()
        except (sqlite3.Error, TypeError):
            pass

    def close(self) -> None:
        """Close the database connection if open."""
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
