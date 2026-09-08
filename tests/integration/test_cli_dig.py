"""Integration tests: the dig command over a real directory tree."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from lang_fossil.cli.app import app

runner = CliRunner()


def test_dig_table_runs(py_repo: Path) -> None:
    """dig prints the stratigraphy table without writing files."""
    result = runner.invoke(app, ["dig", str(py_repo)])
    assert result.exit_code == 0
    assert "stratigraphy" in result.output.lower()


def test_dig_json_report(py_repo: Path, tmp_path: Path) -> None:
    """dig --format json writes the canonical document."""
    out = tmp_path / "report.json"
    result = runner.invoke(
        app, ["dig", str(py_repo), "--format", "json", "--output", str(out), "--no-cache"]
    )
    assert result.exit_code == 0
    document = json.loads(out.read_text(encoding="utf-8"))
    assert document["summary"]["total_fossils"] >= 1


def test_dig_html_report(py_repo: Path, tmp_path: Path) -> None:
    """dig --format html writes a self-contained page."""
    out = tmp_path / "report.html"
    result = runner.invoke(
        app, ["dig", str(py_repo), "--format", "html", "--output", str(out), "--no-cache"]
    )
    assert result.exit_code == 0
    html = out.read_text(encoding="utf-8")
    assert "lf-data" in html


def test_dig_sarif_report(py_repo: Path, tmp_path: Path) -> None:
    """dig --format sarif writes SARIF 2.1.0."""
    out = tmp_path / "report.sarif"
    result = runner.invoke(
        app, ["dig", str(py_repo), "--format", "sarif", "--output", str(out), "--no-cache"]
    )
    assert result.exit_code == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["version"] == "2.1.0"


def test_dig_unknown_format_fails(py_repo: Path, tmp_path: Path) -> None:
    """An unknown format is a usage error (exit 64)."""
    result = runner.invoke(app, ["dig", str(py_repo), "--format", "pdf", "--no-cache"])
    assert result.exit_code == 64


def test_rules_command(builtin_registry, monkeypatch) -> None:
    """rules lists builtin rules with provenance."""
    monkeypatch.setenv("COLUMNS", "200")  # rich truncates headers on 80-col capture
    result = runner.invoke(app, ["rules"])
    assert result.exit_code == 0
    assert "PF001" in result.output
    assert "provenance" in result.output.lower()


def test_diff_command(py_repo: Path, tmp_path: Path) -> None:
    """diff reports introduced/resolved fossils between two reports."""
    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    runner.invoke(app, ["dig", str(py_repo), "--format", "json", "-o", str(old), "--no-cache"])
    (py_repo / "legacy" / "extra.py").write_text("import sets\n", encoding="utf-8")
    runner.invoke(app, ["dig", str(py_repo), "--format", "json", "-o", str(new), "--no-cache"])
    result = runner.invoke(app, ["diff", str(old), str(new)])
    assert result.exit_code == 0
    assert "introduced: 1" in result.output


def test_fix_dry_run(py_repo: Path) -> None:
    """fix prints external commands in dry-run mode."""
    result = runner.invoke(app, ["fix", str(py_repo)])
    assert result.exit_code == 0


def test_version_flag() -> None:
    """--version prints the package version."""
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "lang-fossil" in result.output
