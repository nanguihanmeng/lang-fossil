"""Canonical JSON report writer.

The JSON document is the single source of truth: HTML reports embed it
verbatim (data/view separation) and the ``diff`` command consumes it.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from lang_fossil import __version__
from lang_fossil.core.models import ScanResult
from lang_fossil.core.stratigraphy import StratigraphyReport


def build_document(
    scan_result: ScanResult, report: StratigraphyReport, root: Path
) -> dict[str, Any]:
    """Assemble the canonical JSON document.

    Args:
        scan_result: Raw scan outcome.
        report: Aggregated stratigraphy report.
        root: Scan root directory.

    Returns:
        A JSON-serializable dict.
    """
    return {
        "tool": {"name": "lang-fossil", "version": __version__},
        "root": str(root),
        "summary": {
            "total_fossils": report.total_fossils,
            "unsafe_count": report.unsafe_count,
            "scanned_files": report.scanned_files,
            "scanned_lines": report.scanned_lines,
            "skipped_files": report.skipped_files,
            "fossil_index": round(report.fossil_index, 4),
            "clone_count": report.clone_count,
            "parse_error_count": len(report.parse_errors),
            "git_dated_fossils": report.git_dated_fossils,
            "active_fossils": report.active_fossils,
        },
        "stratigraphy": {
            "eras": [asdict(era) for era in report.eras],
            "by_rule": report.by_rule,
            "by_module": report.by_module,
            "by_severity": report.by_severity,
        },
        "fossils": [asdict(fossil) for fossil in scan_result.fossils],
        "clones": [asdict(clone) for clone in scan_result.clones],
        "parse_errors": list(report.parse_errors),
    }


def write_report(
    scan_result: ScanResult, report: StratigraphyReport, root: Path, output: Path
) -> Path:
    """Write the JSON report to disk.

    Args:
        scan_result: Raw scan outcome.
        report: Aggregated stratigraphy report.
        root: Scan root directory.
        output: Output file path.

    Returns:
        The written path.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    document = build_document(scan_result, report, root)
    output.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")
    return output
