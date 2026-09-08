"""PMD XML report importer.

Parses PMD's XML report (``pmd -f xml``)::

    <pmd version="6.x">
      <file name="/repo/src/Foo.java">
        <violation beginline="5" begincolumn="3" rule="... " ruleset="..."
                   priority="2">message</violation>
      </file>
    </pmd>

Priority (1 highest) is normalized to severity: 1-2 -> error, 3 -> warning,
4-5 -> info.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from lang_fossil.importers import ExternalFinding, normalize_path

_SEVERITY_BY_PRIORITY = {1: "error", 2: "error", 3: "warning", 4: "info", 5: "info"}


def parse(content: str, root: Path) -> list[ExternalFinding]:
    """Parse PMD XML report text into findings.

    Args:
        content: Raw PMD XML output.
        root: Repository root for path normalization.

    Returns:
        Normalized findings.

    Raises:
        ValueError: If the content is not well-formed XML.
    """
    try:
        # stdlib ElementTree does not fetch external entities; a billion-laughs
        # payload is a local DoS only (report is dev-provided). Switch to
        # defusedxml if reports ever come from untrusted sources.
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
    """Parse an XML attribute as int, falling back to ``default``."""
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default
