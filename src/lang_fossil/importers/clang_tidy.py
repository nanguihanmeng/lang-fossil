"""clang-tidy text diagnostic importer.

Parses clang-tidy's stable textual diagnostic format (one finding per
line). The typical shape is::

    src/main.cpp:12:3: warning: 'auto_ptr' is deprecated [deprecated-declarations]
    src/main.cpp:12:3: note: 'auto_ptr' has been explicitly marked deprecated here

Notes/remarks are not findings (they annotate the main diagnostic); only
``error``/``warning`` records become findings.
"""

from __future__ import annotations

import re
from pathlib import Path

from lang_fossil.importers import ExternalFinding, normalize_path

# path:line:col: severity: message [rule-name]
_DIAGNOSTIC_RE = re.compile(r"^(.+?):(\d+):(\d+):\s+(error|warning):\s*(.*?)(?:\s+\[([\w.-]+)\])?$")


def parse(content: str, root: Path) -> list[ExternalFinding]:
    """Parse clang-tidy textual diagnostics into findings.

    Args:
        content: Raw clang-tidy output.
        root: Repository root for path normalization.

    Returns:
        Normalized findings; lines that do not match the diagnostic shape
        (e.g. notes, build logs) are skipped.
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
