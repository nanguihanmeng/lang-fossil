"""eslint JSON report importer.

Parses the default eslint output format (an array of per-file result
objects)::

    [
      {
        "filePath": "/repo/src/app.js",
        "messages": [
          {"ruleId": "no-var", "severity": 2, "line": 3, "column": 2,
           "message": "Unexpected var, use let or const instead."}
        ]
      }
    ]
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lang_fossil.importers import ExternalFinding, normalize_path

_SEVERITY_BY_INT = {0: "info", 1: "warning", 2: "error"}


def parse(content: str, root: Path) -> list[ExternalFinding]:
    """Parse eslint JSON report text into findings.

    Args:
        content: Raw eslint output.
        root: Repository root for path normalization.

    Returns:
        Normalized findings; malformed top-level entries are skipped so one
        bad record never aborts the import.

    Raises:
        ValueError: If the content is not valid JSON or not an array.
    """
    try:
        results = json.loads(content)
    except ValueError as exc:
        raise ValueError(f"invalid eslint JSON: {exc}") from exc
    if not isinstance(results, list):
        raise ValueError("eslint report must be a JSON array of file results")

    findings: list[ExternalFinding] = []
    for file_result in results:
        if not isinstance(file_result, dict):
            continue
        file_path = file_result.get("filePath")
        if not isinstance(file_path, str):
            continue
        path = normalize_path(file_path, root)
        for message in file_result.get("messages", []):
            if not isinstance(message, dict):
                continue
            rule_id = message.get("ruleId")
            if not isinstance(rule_id, str):
                continue  # fatal parse errors carry no rule id; not findings
            findings.append(
                ExternalFinding(
                    tool="eslint",
                    rule_id=rule_id,
                    path=path,
                    line=_to_int(message.get("line"), 1),
                    column=max(0, _to_int(message.get("column"), 1) - 1),
                    message=_to_str(message.get("message")),
                    severity=_SEVERITY_BY_INT.get(_to_int(message.get("severity"), 1), "warning"),
                )
            )
    return findings


def _to_int(value: Any, default: int) -> int:
    """Coerce a report field to int (0-based column handled by caller)."""
    return value if isinstance(value, int) else default


def _to_str(value: Any) -> str:
    """Coerce a message field to str."""
    return value if isinstance(value, str) else ""
