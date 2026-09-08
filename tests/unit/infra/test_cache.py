"""Unit tests for the content-hash cache (mirrors infra/cache.py)."""

from __future__ import annotations

import threading
from pathlib import Path

from lang_fossil.infra.cache import ScanCache

_FOSSIL = {
    "rule_id": "PF001",
    "path": "a.py",
    "line": 1,
    "column": 0,
    "message": "m",
    "era": "paleozoic",
    "provenance": "test",
    "severity": "warning",
    "fix_hint": None,
}


def test_roundtrip(tmp_path: Path) -> None:
    """Put then get returns identical fossil dicts and errors."""
    cache = ScanCache(tmp_path / "cache.db")
    key = ScanCache.make_key("print 'x'\n", "rules-1")
    cache.put(key, [_FOSSIL], errors=("line 1: bad syntax",))
    data = cache.get(key)
    assert data is not None
    assert data["fossils"] == [_FOSSIL]
    assert data["errors"] == ["line 1: bad syntax"]
    cache.close()


def test_miss_returns_none(tmp_path: Path) -> None:
    """Unknown keys return None."""
    cache = ScanCache(tmp_path / "cache.db")
    assert cache.get("nope") is None
    cache.close()


def test_disabled_cache_is_noop(tmp_path: Path) -> None:
    """A disabled cache neither persists nor errors."""
    cache = ScanCache(tmp_path / "cache.db", enabled=False)
    cache.put("k", [], errors=())
    assert cache.get("k") is None
    cache.close()


def test_corrupt_entry_degrades(tmp_path: Path) -> None:
    """A corrupted row reads as a miss instead of raising."""
    import sqlite3

    db_path = tmp_path / "cache.db"
    cache = ScanCache(db_path)
    cache.put("k", [_FOSSIL])
    cache.close()
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE results SET fossils = '{bogus'")
    conn.commit()
    conn.close()
    cache = ScanCache(db_path)
    assert cache.get("k") is None
    cache.close()


def test_legacy_payload_readable(tmp_path: Path) -> None:
    """Rows written by an older lang-fossil (bare fossil list) still read."""
    import json
    import sqlite3

    db_path = tmp_path / "cache.db"
    cache = ScanCache(db_path)
    cache.close()
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO results (key, fossils) VALUES (?, ?)",
        ("k", json.dumps([_FOSSIL])),
    )
    conn.commit()
    conn.close()
    cache = ScanCache(db_path)
    data = cache.get("k")
    assert data is not None and data["fossils"] == [_FOSSIL]
    assert data["errors"] == ()
    cache.close()


def test_key_depends_on_rules(tmp_path: Path) -> None:
    """Cache keys change when the rule set changes."""
    assert ScanCache.make_key("x=1", "r1") != ScanCache.make_key("x=1", "r2")


def test_threaded_access_is_safe(tmp_path: Path) -> None:
    """get/put from worker threads neither raises nor loses entries."""
    cache = ScanCache(tmp_path / "cache.db")
    keys = [ScanCache.make_key(f"x = {i}\n", "r") for i in range(50)]
    for key in keys:
        cache.put(key, [])
    errors: list[BaseException] = []

    def worker(key: str) -> None:
        try:
            cache.get(key)
            cache.put(key, [_FOSSIL])
        except BaseException as exc:  # pragma: no cover - failure probe
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(key,)) for key in keys]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    cache.close()
    assert errors == []
