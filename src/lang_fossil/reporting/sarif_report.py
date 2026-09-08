"""SARIF 2.1.0 报告写入器，用于 CI 平台集成."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lang_fossil import __version__
from lang_fossil.core.models import ScanResult
from lang_fossil.core.stratigraphy import StratigraphyReport

# 严重级 -> SARIF level 映射.
_SEVERITY_TO_SARIF = {"error": "error", "warning": "warning", "info": "note"}


def write_report(
    scan_result: ScanResult, report: StratigraphyReport, root: Path, output: Path
) -> Path:
    """把 SARIF 2.1.0 报告写入磁盘.

    Args:
        scan_result: 原始扫描产物.
        report: 聚合的地层报告（规则元数据来源）.
        root: 扫描根目录（用于构造 URI）.
        output: 输出文件路径.

    Returns:
        写入的路径.
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
