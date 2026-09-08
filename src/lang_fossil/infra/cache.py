"""sqlite3 实现的内容哈希扫描缓存.

缓存键为 ``sha256(源码 + 规则摘要 + 僵尸快照版本)``。存储载荷同时捆绑
化石字典**与**解析错误，缓存命中可复现首跑的完整结果。相同内容改名后
也能命中——缓存载荷在关键处不含路径：路径由调用方在读取时重贴到
*当前* ``path``.
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
    """小型的 sqlite3 键/值缓存，按文件缓存扫描结果."""

    def __init__(self, path: Path, enabled: bool = True) -> None:
        """打开（并惰性创建）缓存数据库.

        Args:
            path: 数据库文件路径；父目录会自动创建.
            enabled: False 时缓存降级为空操作.
        """
        self._enabled = enabled
        self._conn: sqlite3.Connection | None = None
        # ponytail: 单连接 + 锁；扫描线程池的 worker 共享该缓存。只有当
        # 缓存吞吐出现在 profile 里才需要按 worker 分片.
        self._lock = threading.Lock()
        if not enabled:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # check_same_thread=False：扫描 worker 共享此连接.
            self._conn = sqlite3.connect(path, check_same_thread=False)
            self._conn.execute(_SCHEMA)
            self._conn.commit()
        except sqlite3.Error:
            # 缓存尽力而为：绝不因它破坏扫描.
            self._conn = None

    @staticmethod
    def make_key(source: str, rules_digest: str) -> str:
        """由内容与生效规则集计算缓存键.

        Args:
            source: 文件完整源码文本.
            rules_digest: 生效规则集的稳定摘要.

        Returns:
            可用作缓存键的十六进制摘要.
        """
        return hashlib.sha256(source.encode("utf-8", "replace") + rules_digest.encode()).hexdigest()

    def _fetch_raw(self, key: str) -> str | None:
        """读取某键的原始 JSON 载荷.

        Args:
            key: :meth:`make_key` 生成的缓存键.

        Returns:
            存储的 JSON 字符串；未命中或任何缓存错误返回 ``None``.
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
        """获取缓存的载荷.

        Args:
            key: :meth:`make_key` 生成的缓存键.

        Returns:
            含 ``fossils``（列表）与 ``errors``（序列）的映射；未命中或
            任何缓存错误返回 ``None``.
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
        if isinstance(data, list):  # 旧版载荷：裸化石列表，无错误信息
            return {"fossils": data, "errors": ()}
        return None

    def put(self, key: str, fossils: list[dict[str, Any]], errors: Any = ()) -> None:
        """存储化石载荷（尽力而为，忽略错误）.

        Args:
            key: :meth:`make_key` 生成的缓存键.
            fossils: 可 JSON 序列化的化石字典列表.
            errors: 需在缓存命中时复现的源码解析错误.
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
        """关闭数据库连接（若已打开）."""
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
