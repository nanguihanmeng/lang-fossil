"""Unit tests for external linter report importers (mirrors importers/*)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lang_fossil.importers import SUPPORTED_TOOLS, parse_report
from lang_fossil.importers.clang_tidy import parse as parse_clang_tidy
from lang_fossil.importers.eslint import parse as parse_eslint
from lang_fossil.importers.pmd import parse as parse_pmd


def test_eslint_parse(tmp_path: Path) -> None:
    """eslint JSON findings import with normalized paths and columns."""
    target = tmp_path / "app.js"
    target.write_text("x = 1\n", encoding="utf-8")
    payload = [
        {
            "filePath": str(target),
            "messages": [
                {
                    "ruleId": "no-var",
                    "severity": 2,
                    "line": 3,
                    "column": 2,
                    "message": "Unexpected var.",
                }
            ],
        }
    ]
    findings = parse_eslint(json.dumps(payload), tmp_path)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.tool == "eslint"
    assert finding.rule_id == "no-var"
    assert finding.path == "app.js"
    assert finding.line == 3
    assert finding.column == 1  # 1-based input -> 0-based storage
    assert finding.severity == "error"


def test_eslint_skips_fatal_parse_messages(tmp_path: Path) -> None:
    """Messages without a ruleId (parse fatals) are not findings."""
    payload = [
        {"filePath": str(tmp_path / "a.js"), "messages": [{"fatal": True, "message": "bad"}]}
    ]
    assert parse_eslint(json.dumps(payload), tmp_path) == []


def test_eslint_invalid_json(tmp_path: Path) -> None:
    """Malformed eslint JSON raises a ValueError."""
    with pytest.raises(ValueError, match="invalid eslint JSON"):
        parse_eslint("{nope", tmp_path)


def test_clang_tidy_text_parse(tmp_path: Path) -> None:
    """clang-tidy textual diagnostics import; notes are skipped."""
    content = (
        "src/main.cpp:12:3: warning: 'auto_ptr' is deprecated "
        "[deprecated-declarations]\n"
        "src/main.cpp:12:3: note: 'auto_ptr' has been marked deprecated here\n"
        "src/other.cpp:1:1: error: something broke [clang-diagnostic-error]\n"
    )
    findings = parse_clang_tidy(content, tmp_path)
    assert len(findings) == 2
    assert findings[0].rule_id == "deprecated-declarations"
    assert findings[0].path == "src/main.cpp"
    assert findings[0].line == 12
    assert findings[0].column == 2
    assert findings[0].severity == "warning"
    assert findings[1].severity == "error"


def test_pmd_xml_parse(tmp_path: Path) -> None:
    """PMD XML imports violations with priority->severity mapping."""
    target = tmp_path / "src" / "Foo.java"
    target.parent.mkdir(parents=True)
    target.write_text("class Foo {}\n", encoding="utf-8")
    xml = (
        f'<pmd version="6.55.0">'
        f'<file name="{target}">'
        '<violation beginline="5" begincolumn="3" priority="1" rule="AvoidVector">'
        "use ArrayList</violation>"
        "</file>"
        "</pmd>"
    )
    findings = parse_pmd(xml, tmp_path)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule_id == "AvoidVector"
    assert finding.path == "src/Foo.java"
    assert finding.line == 5
    assert finding.column == 2
    assert finding.severity == "error"
    assert finding.message == "use ArrayList"


def test_pmd_invalid_xml(tmp_path: Path) -> None:
    """Malformed PMD XML raises a ValueError."""
    with pytest.raises(ValueError, match="invalid PMD XML"):
        parse_pmd("<pmd><broken", tmp_path)


def test_parse_report_dispatch(tmp_path: Path) -> None:
    """parse_report dispatches to the right importer by tool name."""
    findings = parse_report("eslint", json.dumps([{"filePath": "a.js", "messages": []}]), tmp_path)
    assert findings == []
    assert SUPPORTED_TOOLS == ("eslint", "clang-tidy", "pmd")
    with pytest.raises(ValueError, match="unsupported linter tool"):
        parse_report("shellcheck", "", tmp_path)
