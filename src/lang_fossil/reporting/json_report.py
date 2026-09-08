"""规范 JSON 报告写入器.

JSON 文档是唯一事实源：HTML 报告原样内嵌（数据/视图分离），``diff``
命令反向消费它.
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
    """组装规范的 JSON 文档.

    Args:
        scan_result: 原始扫描产物.
        report: 聚合的地层报告.
        root: 扫描根目录.

    Returns:
        可 JSON 序列化的字典.
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
    """把 JSON 报告写入磁盘.

    Args:
        scan_result: 原始扫描产物.
        report: 聚合的地层报告.
        root: 扫描根目录.
        output: 输出文件路径.

    Returns:
        写入的路径.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    document = build_document(scan_result, report, root)
    output.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")
    return output
