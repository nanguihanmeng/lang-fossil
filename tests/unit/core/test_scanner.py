"""Unit tests for discovery + scan orchestration (mirrors core/scanner.py)."""

from __future__ import annotations

import subprocess  # noqa: S404 - test setup only, list args
from datetime import date
from pathlib import Path
from unittest import mock

from lang_fossil.config import (
    AmbiguousHeaderSettings,
    GitSettings,
    LangFossilSettings,
    ScanSettings,
)
from lang_fossil.core.engine import Engine
from lang_fossil.core.scanner import discover, scan, sniff_language


def test_sniff_language(tmp_path: Path) -> None:
    """Extensions map to languages; unknown ones return None."""
    assert sniff_language(Path("a.py")) == "python"
    assert sniff_language(Path("b.JS")) == "javascript"
    assert sniff_language(Path("c.mjs")) == "javascript"
    assert sniff_language(Path("d.rb")) is None


def test_discover_excludes_dirs(py_repo: Path) -> None:
    """Excluded directories (node_modules etc.) are skipped."""
    (py_repo / "legacy" / "node_modules").mkdir()
    (py_repo / "legacy" / "node_modules" / "dep.py").write_text("x = 1\n")
    settings = LangFossilSettings()
    entries, skipped = discover(py_repo, settings)
    paths = {entry.path for entry in entries}
    assert "legacy/old.py" in paths
    assert not any("node_modules" in p for p in paths)
    assert skipped >= 0


def test_discover_skips_binary(tmp_path: Path) -> None:
    """Files containing null bytes are skipped."""
    (tmp_path / "blob.py").write_bytes(b"x = 1\x00\x00")
    entries, skipped = discover(tmp_path, LangFossilSettings())
    assert entries == []
    assert skipped == 1


def test_discover_skips_unsupported(tmp_path: Path) -> None:
    """Unsupported extensions count as skipped."""
    (tmp_path / "notes.md").write_text("# hi\n", encoding="utf-8")
    (tmp_path / "code.py").write_text("x = 1\n", encoding="utf-8")
    entries, skipped = discover(tmp_path, LangFossilSettings())
    assert [entry.path for entry in entries] == ["code.py"]
    assert skipped == 1


def _write_header(repo: Path, name: str) -> None:
    """Write a minimal .h file (contents irrelevant to the policy)."""
    (repo / name).write_text("int f(void);\n", encoding="utf-8")


def test_headers_resolved_by_mode(tmp_path: Path) -> None:
    """Explicit mode c/cpp decides every ambiguous header."""
    settings_c = LangFossilSettings(
        scan=ScanSettings(ambiguous_headers=AmbiguousHeaderSettings(mode="c"))
    )
    (tmp_path / "a.h").write_text("int f(void);\n", encoding="utf-8")
    entries, _skipped = discover(tmp_path, settings_c)
    assert [entry.language for entry in entries] == ["c"]

    settings_cpp = LangFossilSettings(
        scan=ScanSettings(ambiguous_headers=AmbiguousHeaderSettings(mode="cpp"))
    )
    entries, _skipped = discover(tmp_path, settings_cpp)
    assert [entry.language for entry in entries] == ["cpp"]


def test_headers_auto_uses_sibling_majority(tmp_path: Path) -> None:
    """auto mode consults sibling .c/.cpp sources, defaulting to c."""
    c_dir = tmp_path / "c_only"
    cpp_dir = tmp_path / "cpp_only"
    c_dir.mkdir()
    cpp_dir.mkdir()
    (c_dir / "a.c").write_text("int f(void) { return 1; }\n", encoding="utf-8")
    (cpp_dir / "b.cpp").write_text("int g() { return 2; }\n", encoding="utf-8")
    (cpp_dir / "c.cc").write_text("int h() { return 3; }\n", encoding="utf-8")
    _write_header(c_dir, "a.h")
    _write_header(cpp_dir, "b.h")

    entries, skipped = discover(tmp_path, LangFossilSettings())
    by_path = {entry.path: entry.language for entry in entries}
    assert by_path == {
        "c_only/a.c": "c",
        "c_only/a.h": "c",
        "cpp_only/b.cpp": "cpp",
        "cpp_only/c.cc": "cpp",
        "cpp_only/b.h": "cpp",
    }
    assert skipped == 0


def test_headers_overrides_beat_mode(tmp_path: Path) -> None:
    """Glob overrides take precedence over the mode."""
    policy = AmbiguousHeaderSettings(
        mode="cpp",
        overrides={"legacy/*.h": "c"},
    )
    settings = LangFossilSettings(scan=ScanSettings(ambiguous_headers=policy))
    (tmp_path / "legacy").mkdir()
    (tmp_path / "modern").mkdir()
    (tmp_path / "legacy" / "a.c").write_text("int f(void) { return 1; }\n", encoding="utf-8")
    _write_header(tmp_path / "legacy", "a.h")
    _write_header(tmp_path / "modern", "b.h")

    entries, _skipped = discover(tmp_path, settings)
    by_path = {entry.path: entry.language for entry in entries}
    assert by_path == {"legacy/a.c": "c", "legacy/a.h": "c", "modern/b.h": "cpp"}


def test_discover_sample_ratio_zero(tmp_path: Path) -> None:
    """sample_ratio=0.0 skips everything deterministically."""
    for i in range(5):
        (tmp_path / f"m{i}.py").write_text("x = 1\n", encoding="utf-8")
    settings = LangFossilSettings(scan=ScanSettings(sample_ratio=0.0))
    entries, skipped = discover(tmp_path, settings)
    assert entries == []
    assert skipped == 5


def test_discover_single_file(tmp_path: Path) -> None:
    """Scanning a single file (not a directory) works."""
    (tmp_path / "solo.py").write_text("x = 1\n", encoding="utf-8")
    entries, _skipped = discover(tmp_path / "solo.py", LangFossilSettings())
    assert [entry.path for entry in entries] == ["solo.py"]


def test_scan_end_to_end(py_repo: Path) -> None:
    """A full scan finds paleozoic fossils and no modern ones."""
    settings = LangFossilSettings()
    from lang_fossil.core.engine import Engine
    from lang_fossil.core.zombie_api import ZombieApiDB
    from lang_fossil.rules.registry import RuleRegistry

    engine = Engine(RuleRegistry.load_builtin(), ZombieApiDB.load())
    result = scan(py_repo, settings, engine)
    rule_hits = {f.rule_id for f in result.fossils}
    assert {"PF001", "PF003", "PF004", "PF007"} <= rule_hits
    modern = [f for f in result.fossils if f.path.startswith("modern/")]
    assert modern == []
    assert result.scanned_files == 2
    assert result.scanned_lines > 0


def test_scan_collects_parse_errors(tmp_path: Path) -> None:
    """Syntax errors surface through the errors channel, not exceptions."""
    (tmp_path / "broken.py").write_text("def f(:\n", encoding="utf-8")
    settings = LangFossilSettings()
    from lang_fossil.core.engine import Engine
    from lang_fossil.core.zombie_api import ZombieApiDB
    from lang_fossil.rules.registry import RuleRegistry

    engine = Engine(RuleRegistry.load_builtin(), ZombieApiDB.load())
    result = scan(tmp_path, settings, engine)
    assert result.parse_errors


def test_scan_parallel_workers(py_repo: Path) -> None:
    """workers>1 uses the thread pool and still finds the fossils."""
    settings = LangFossilSettings(scan=ScanSettings(workers=4))
    from lang_fossil.core.engine import Engine
    from lang_fossil.core.zombie_api import ZombieApiDB
    from lang_fossil.rules.registry import RuleRegistry

    engine = Engine(RuleRegistry.load_builtin(), ZombieApiDB.load())
    result = scan(py_repo, settings, engine)
    assert {"PF001", "PF004"} <= {f.rule_id for f in result.fossils}


def test_scan_unreadable_file_degrades(tmp_path: Path) -> None:
    """An unreadable file yields an LF-IO info fossil, not a crash."""
    locked = tmp_path / "locked.py"
    locked.write_text("x = 1\n", encoding="utf-8")
    real_open = Path.open

    def _deny(self: Path, *args: object, **kwargs: object) -> object:
        if self.name == "locked.py" and "rb" not in args:
            raise OSError("locked")
        return real_open(self, *args, **kwargs)  # type: ignore[arg-type]

    from lang_fossil.core.engine import Engine
    from lang_fossil.core.zombie_api import ZombieApiDB
    from lang_fossil.rules.registry import RuleRegistry

    with mock.patch.object(Path, "open", _deny):
        engine = Engine(RuleRegistry.load_builtin(), ZombieApiDB.load())
        result = scan(tmp_path, LangFossilSettings(), engine)
    assert any(f.rule_id == "LF-IO" for f in result.fossils)


def test_cache_hit_reattaches_current_path(tmp_path: Path) -> None:
    """A content cache hit reports the *current* path, not the first one."""
    from lang_fossil.core.engine import Engine
    from lang_fossil.core.zombie_api import ZombieApiDB
    from lang_fossil.infra.cache import ScanCache
    from lang_fossil.rules.registry import RuleRegistry

    body = "print 'hello'\n"
    repo1 = tmp_path / "repo1"
    repo1.mkdir()
    (repo1 / "a.py").write_text(body, encoding="utf-8")

    engine = Engine(RuleRegistry.load_builtin(), ZombieApiDB.load())
    db_path = tmp_path / "cache.db"

    cache = ScanCache(db_path)
    first = scan(repo1, LangFossilSettings(), engine, cache)
    cache.close()
    assert {f.path for f in first.fossils} == {"a.py"}

    # Same content under a different path must not leak repo1's path.
    repo2 = tmp_path / "repo2"
    repo2.mkdir()
    (repo2 / "b.py").write_text(body, encoding="utf-8")
    cache = ScanCache(db_path)
    second = scan(repo2, LangFossilSettings(), engine, cache)
    cache.close()
    assert {f.path for f in second.fossils} == {"b.py"}


def test_cache_hit_preserves_parse_errors(tmp_path: Path) -> None:
    """Parse errors recorded on a miss survive a later cache hit."""
    from lang_fossil.core.engine import Engine
    from lang_fossil.core.zombie_api import ZombieApiDB
    from lang_fossil.infra.cache import ScanCache
    from lang_fossil.rules.registry import RuleRegistry

    broken = tmp_path / "broken.py"
    broken.write_text("def f(:\n", encoding="utf-8")

    engine = Engine(RuleRegistry.load_builtin(), ZombieApiDB.load())
    db_path = tmp_path / "cache.db"
    cache = ScanCache(db_path)
    first = scan(tmp_path, LangFossilSettings(), engine, cache)
    cache.close()
    assert first.parse_errors

    cache = ScanCache(db_path)
    second = scan(tmp_path, LangFossilSettings(), engine, cache)
    cache.close()
    assert second.parse_errors == first.parse_errors


def test_scan_without_git_leaves_years_none(py_repo: Path, engine: Engine) -> None:
    """Default (git disabled) scans keep last_commit_year None."""
    result = scan(py_repo, LangFossilSettings(), engine)
    assert result.fossils
    assert all(fossil.last_commit_year is None for fossil in result.fossils)


def test_scan_git_enabled_dates_fossils(tmp_path: Path, engine: Engine) -> None:
    """With git dating enabled, fossils carry their file's commit year."""
    (tmp_path / "legacy").mkdir()
    (tmp_path / "legacy" / "old.py").write_text(
        "print 'hello'\nfor i in xrange(3):\n    print i\n", encoding="utf-8"
    )
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=False)  # noqa: S603
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=False)  # noqa: S603
    subprocess.run(  # noqa: S603
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
        cwd=tmp_path,
        check=False,
    )
    settings = LangFossilSettings(git=GitSettings(enabled=True))
    result = scan(tmp_path, settings, engine)
    assert result.fossils
    assert all(fossil.last_commit_year == date.today().year for fossil in result.fossils)
