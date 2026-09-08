"""eslint JSON 报告导入器.

解析 eslint 默认输出格式（按文件结果对象的数组）::

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

# eslint severity 整数 -> 规范化严重级.
_SEVERITY_BY_INT = {0: "info", 1: "warning", 2: "error"}


def parse(content: str, root: Path) -> list[ExternalFinding]:
    """解析 eslint JSON 报告文本为 finding.

    Args:
        content: eslint 原始输出.
        root: 用于路径规范化的仓库根.

    Returns:
        规范化的 finding；畸形顶层条目跳过，单条坏记录不中断导入.

    Raises:
        ValueError: 内容不是合法 JSON 或不是数组.
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
                continue  # 致命解析错误不带 ruleId，不算 finding
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
    """把报告字段强转为 int（0 基列号由调用方处理）."""
    return value if isinstance(value, int) else default


def _to_str(value: Any) -> str:
    """把 message 字段强转为 str."""
    return value if isinstance(value, str) else ""
