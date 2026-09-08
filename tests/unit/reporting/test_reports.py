"""Unit tests for report writers (mirrors reporting/*)."""

from __future__ import annotations

import json
from pathlib import Path

from lang_fossil.core.models import Fossil, ScanResult
from lang_fossil.core.stratigraphy import build_report
from lang_fossil.reporting.html_report import write_report as write_html
from lang_fossil.reporting.json_report import build_document, write_report
from lang_fossil.reporting.sarif_report import write_report as write_sarif


def _scan_result() -> ScanResult:
    """A scan result with one fossil for report tests."""
    fossil = Fossil(
        rule_id="PF001",
        path="legacy/old.py",
        line=3,
        column=0,
        message="print statement",
        era="paleozoic",
        provenance="internal",
        severity="error",
    )
    return ScanResult((fossil,), 1, 10, 0, ())


def _embedded_json(html: str) -> str:
    """Return the raw text of the ``lf-data`` JSON script block."""
    marker = 'id="lf-data">'
    start = html.index(marker) + len(marker)
    end = html.index("</script>", start)
    return html[start:end]


def test_json_document_shape(tmp_path: Path) -> None:
    """The JSON document carries summary, stratigraphy and fossils."""
    result = _scan_result()
    report = build_report(result)
    document = build_document(result, report, tmp_path)
    assert document["tool"]["name"] == "lang-fossil"
    assert document["summary"]["total_fossils"] == 1
    assert document["summary"]["git_dated_fossils"] == 0
    assert document["summary"]["active_fossils"] == 0
    assert document["fossils"][0]["rule_id"] == "PF001"
    assert document["fossils"][0]["last_commit_year"] is None
    assert document["stratigraphy"]["eras"][0]["era"] == "paleozoic"


def test_json_report_written(tmp_path: Path) -> None:
    """write_report produces valid JSON on disk."""
    result = _scan_result()
    out = write_report(result, build_report(result), tmp_path, tmp_path / "r.json")
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["summary"]["fossil_index"] == 100.0


def test_sarif_report_valid(tmp_path: Path) -> None:
    """SARIF 2.1.0 output has rules and results with locations."""
    result = _scan_result()
    out = write_sarif(result, build_report(result), tmp_path, tmp_path / "r.sarif")
    data = json.loads(out.read_text(encoding="utf-8"))
    run = data["runs"][0]
    assert data["version"] == "2.1.0"
    assert run["tool"]["driver"]["rules"][0]["id"] == "PF001"
    location = run["results"][0]["locations"][0]["physicalLocation"]
    assert location["region"]["startLine"] == 3


def test_html_report_embeds_data(tmp_path: Path) -> None:
    """The default HTML report embeds parseable canonical JSON in-script."""
    result = _scan_result()
    out = write_html(result, build_report(result), tmp_path, tmp_path / "r.html")
    html = out.read_text(encoding="utf-8")
    assert '<script type="application/json" id="lf-data">' in html
    assert "pf001" in html.lower()
    assert "print statement" in html
    assert "active legacy fossils" in html
    # Autoescape must not corrupt the embedded JSON (quotes stay quotes).
    data = json.loads(_embedded_json(html))
    assert data["fossils"][0]["path"] == "legacy/old.py"
    assert "&quot;" not in _embedded_json(html)


def test_html_shell_mode(tmp_path: Path) -> None:
    """--no-embed writes a shell page plus a sibling JSON data file."""
    result = _scan_result()
    out = write_html(result, build_report(result), tmp_path, tmp_path / "r.html", embed_data=False)
    assert out.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")
    assert (tmp_path / "r.json").is_file()
