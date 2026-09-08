"""PMD XML 报告导入器.

解析 PMD 的 XML 报告（``pmd -f xml``）::

    <pmd version="6.x">
      <file name="/repo/src/Foo.java">
        <violation beginline="5" begincolumn="3" rule="..." ruleset="..."
                   priority="2">message</violation>
      </file>
    </pmd>

priority（1 最高）规范化为严重级：1-2 -> error，3 -> warning，4-5 -> info.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from lang_fossil.importers import ExternalFinding, normalize_path

# priority -> severity 映射.
_SEVERITY_BY_PRIORITY = {1: "error", 2: "error", 3: "warning", 4: "info", 5: "info"}


def parse(content: str, root: Path) -> list[ExternalFinding]:
    """解析 PMD XML 报告文本为 finding.

    Args:
        content: PMD XML 原始输出.
        root: 用于路径规范化的仓库根.

    Returns:
        规范化的 finding.

    Raises:
        ValueError: 内容不是良构 XML.
    """
    try:
        # stdlib ElementTree 不抓取外部实体；实体膨胀最坏只造成本地 DoS
        # （报告由开发者提供）。若未来接入不可信来源，换用 defusedxml.
        document = ET.fromstring(content)  # noqa: S314
    except ET.ParseError as exc:
        raise ValueError(f"invalid PMD XML: {exc}") from exc

    findings: list[ExternalFinding] = []
    for file_node in document.findall(".//file"):
        file_path = file_node.get("name")
        if not file_path:
            continue
        path = normalize_path(file_path, root)
        for violation in file_node.findall("violation"):
            rule_id = violation.get("rule")
            if not rule_id:
                continue
            line = _to_int(violation.get("beginline"), 1)
            column = max(0, _to_int(violation.get("begincolumn"), 1) - 1)
            priority = _to_int(violation.get("priority"), 3)
            findings.append(
                ExternalFinding(
                    tool="pmd",
                    rule_id=rule_id,
                    path=path,
                    line=line,
                    column=column,
                    message=(violation.text or "").strip(),
                    severity=_SEVERITY_BY_PRIORITY.get(priority, "warning"),
                )
            )
    return findings


def _to_int(raw: str | None, default: int) -> int:
    """把 XML 属性解析为 int，失败回退 ``default``."""
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default
