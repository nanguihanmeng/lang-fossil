"""Integration tests: the annotate command over an external linter report."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from lang_fossil.cli.app import app

runner = CliRunner()


def test_annotate_table_runs(tmp_path: Path) -> None:
    """annotate prints a table of labelled findings."""
    report, root = _write_repo_and_report(tmp_path)
    result = runner.invoke(app, ["annotate", str(root), str(report), "--tool", "eslint"])
    assert result.exit_code == 0
    assert "annotated: 2" in result.output  # both findings labelled
    assert "unannotated: 0" in result.output


def test_annotate_json_report(tmp_path: Path, monkeypatch) -> None:
    """annotate --format json writes labels and summary aggregates."""
    report, root = _write_repo_and_report(tmp_path)
    out = tmp_path / "annotations.json"
    monkeypatch.setenv("COLUMNS", "200")
    result = runner.invoke(
        app,
        [
            "annotate",
            str(root),
            str(report),
            "--tool",
            "eslint",
            "--format",
            "json",
            "--output",
            str(out),
        ],
    )
    assert result.exit_code == 0
    document = json.loads(out.read_text(encoding="utf-8"))
    assert document["linter"] == "eslint"
    assert document["summary"]["annotated"] >= 1
    records = document["annotations"]
    assert any(record["rule_id"] == "no-var" for record in records)
    labels = [record["label"] for record in records]
    assert any(label is not None and label["rule_id"] == "JS002" for label in labels)


def test_annotate_bad_tool_fails(tmp_path: Path) -> None:
    """An unsupported --tool is a config error (exit 2)."""
    report, root = _write_repo_and_report(tmp_path)
    result = runner.invoke(app, ["annotate", str(root), str(report), "--tool", "shellcheck"])
    assert result.exit_code == 2


def _write_repo_and_report(tmp_path: Path) -> tuple[Path, Path]:
    """Write a JS repo plus an eslint report referencing it."""
    repo = tmp_path / "app"
    repo.mkdir()
    target = repo / "app.js"
    target.write_text("var x = 1\nvar y = document.all\n", encoding="utf-8")
    report = tmp_path / "eslint.json"
    payload = [
        {
            "filePath": str(target),
            "messages": [
                {
                    "ruleId": "no-var",
                    "severity": 2,
                    "line": 1,
                    "column": 1,
                    "message": "Unexpected var, use let or const instead.",
                },
                {
                    "ruleId": "no-unused-vars",
                    "severity": 1,
                    "line": 2,
                    "column": 1,
                    "message": "'y' is assigned a value but never used.",
                },
            ],
        }
    ]
    report.write_text(json.dumps(payload), encoding="utf-8")
    return report, repo
