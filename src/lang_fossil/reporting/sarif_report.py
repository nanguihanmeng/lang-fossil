"""SARIF 2.1.0 report writer for CI platform integration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lang_fossil import __version__
from lang_fossil.core.models import ScanResult
from lang_fossil.core.stratigraphy import StratigraphyReport

_SEVERITY_TO_SARIF = {"error": "error", "warning": "warning", "info": "note"}


def write_report(
    scan_result: ScanResult, report: StratigraphyReport, root: Path, output: Path
) -> Path:
    """Write a SARIF 2.1.0 report to disk.

    Args:
        scan_result: Raw scan outcome.
        report: Aggregated stratigraphy report (rule metadata source).
        root: Scan root directory (used to build URIs).
        output: Output file path.

    Returns:
        The written path.
    """
    rules: dict[str, dict[str, Any]] = {}
    results = []
    for fossil in scan_result.fossils:
        if fossil.rule_id not in rules:
            rules[fossil.rule_id] = {
                "id": fossil.rule_id,
                "shortDescription": {"text": fossil.message},
                "properties": {"era": fossil.era, "provenance": fossil.provenance},
            }
        results.append(
            {
                "ruleId": fossil.rule_id,
                "level": _SEVERITY_TO_SARIF.get(fossil.severity, "warning"),
                "message": {"text": fossil.message},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {
                                "uri": fossil.path,
                                "uriBaseId": "%SRCROOT%",
                            },
                            "region": {
                                "startLine": fossil.line,
                                "startColumn": fossil.column + 1,
                            },
                        }
                    }
                ],
            }
        )

    document = {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "lang-fossil",
                        "version": __version__,
                        "informationUri": "https://github.com/lang-fossil/lang-fossil",
                        "rules": sorted(rules.values(), key=lambda r: r["id"]),
                    }
                },
                "originalUriBaseIds": {"%SRCROOT%": {"uri": root.resolve().as_uri() + "/"}},
                "results": results,
            }
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")
    return output
