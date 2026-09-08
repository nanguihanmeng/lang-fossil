"""Integration tests: check command exit-code contract (CI gate)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from lang_fossil.cli.app import app

runner = CliRunner()


def test_check_passes_clean_repo(tmp_path: Path) -> None:
    """A clean repo exits 0 with a tight budget."""
    (tmp_path / "clean.py").write_text("x = 1\nprint('ok')\n", encoding="utf-8")
    result = runner.invoke(app, ["check", str(tmp_path), "--max-fi", "0.1", "--no-cache"])
    assert result.exit_code == 0


def test_check_fails_fossil_rich_repo(py_repo: Path) -> None:
    """A fossil-rich repo exits 1 when the index budget is exceeded."""
    result = runner.invoke(app, ["check", str(py_repo), "--max-fi", "0.1", "--no-cache"])
    assert result.exit_code == 1


def test_check_count_budget(py_repo: Path) -> None:
    """--max-fossils is enforced independently."""
    result = runner.invoke(app, ["check", str(py_repo), "--max-fossils", "1", "--no-cache"])
    assert result.exit_code == 1


def test_check_generous_budget_passes(py_repo: Path) -> None:
    """A generous budget passes despite fossils."""
    result = runner.invoke(app, ["check", str(py_repo), "--max-fi", "9999", "--no-cache"])
    assert result.exit_code == 0


def test_check_negative_fi_is_config_error(py_repo: Path) -> None:
    """Invalid thresholds are usage errors, not silent passes."""
    result = runner.invoke(app, ["check", str(py_repo), "--max-fi", "-1", "--no-cache"])
    assert result.exit_code != 0
