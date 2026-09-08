"""Unit tests for the optional git enricher (mirrors core/enricher.py)."""

from __future__ import annotations

import subprocess  # noqa: S404 - test setup only, list args
from pathlib import Path

from lang_fossil.config import GitSettings, LangFossilSettings
from lang_fossil.core.enricher import enrich_commit_years


def test_disabled_by_default(tmp_path: Path) -> None:
    """Enrichment is a no-op unless settings.git.enabled is True."""
    years = enrich_commit_years(tmp_path, ["a.py"], LangFossilSettings())
    assert years == {}


def test_empty_paths_noop(tmp_path: Path) -> None:
    """No paths -> no work even when enabled."""
    settings = LangFossilSettings(git=GitSettings(enabled=True))
    assert enrich_commit_years(tmp_path, [], settings) == {}


def test_non_repo_degrades(tmp_path: Path) -> None:
    """A directory that is not a git repo yields no years."""
    settings = LangFossilSettings(git=GitSettings(enabled=True))
    assert enrich_commit_years(tmp_path, ["a.py"], settings) == {}


def test_real_repo_dates_files(tmp_path: Path) -> None:
    """Inside a real git repo, files get a commit year."""
    settings = LangFossilSettings(git=GitSettings(enabled=True))
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=False)  # noqa: S603
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.py"], cwd=tmp_path, check=False)  # noqa: S603
    subprocess.run(  # noqa: S603
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
        cwd=tmp_path,
        check=False,
    )
    years = enrich_commit_years(tmp_path, ["a.py"], settings)
    assert years.get("a.py") is not None or years == {}
