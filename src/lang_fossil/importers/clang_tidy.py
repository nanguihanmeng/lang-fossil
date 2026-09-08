"""clang-tidy 文本诊断导入器.

解析 clang-tidy 稳定的文本诊断格式（每行一条 finding），典型形状::

    src/main.cpp:12:3: warning: 'auto_ptr' is deprecated [deprecated-declarations]
    src/main.cpp:12:3: note: 'auto_ptr' has been explicitly marked deprecated here

note/remark 不是 finding（它们注释主诊断）；只有 ``error``/``warning``
记录成为 finding.
"""

from __future__ import annotations

import re
from pathlib import Path

from lang_fossil.importers import ExternalFinding, normalize_path

# 路径:行:列: severity: message [rule-name]
_DIAGNOSTIC_RE = re.compile(r"^(.+?):(\d+):(\d+):\s+(error|warning):\s*(.*?)(?:\s+\[([\w.-]+)\])?$")


def parse(content: str, root: Path) -> list[ExternalFinding]:
    """解析 clang-tidy 文本诊断为 finding.

    Args:
        content: clang-tidy 原始输出.
        root: 用于路径规范化的仓库根.

    Returns:
        规范化的 finding；不匹配诊断形状的行（如 note、构建日志）跳过.
    """
    findings: list[ExternalFinding] = []
    for line in content.splitlines():
        match = _DIAGNOSTIC_RE.match(line)
        if match is None:
            continue
        raw_path, raw_line, raw_column, severity, message, rule_id = match.groups()
        rule = rule_id or "clang-diagnostic"
        findings.append(
            ExternalFinding(
                tool="clang-tidy",
                rule_id=rule,
                path=normalize_path(raw_path, root),
                line=int(raw_line),
                column=max(0, int(raw_column) - 1),
                message=message.strip(),
                severity=severity,
            )
        )
    return findings
