"""Importers: parse external linter reports into unified findings.

lang-fossil does not run clang-tidy / PMD / eslint itself. It *consumes*
their output and annotates each finding with archaeology metadata (era,
category, provenance) via :mod:`lang_fossil.core.annotate`.

Each importer is a pure function mapping one report file to a list of
:class:`ExternalFinding` records with normalized repository-relative paths.
Supported machine-readable formats (see ``docs/rules-guide.md``):

- eslint: JSON (default CLI output)
- clang-tidy: textual diagnostics (``file:line:col: severity: msg [rule]``)
- PMD: XML report (``-f xml``)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SUPPORTED_TOOLS = ("eslint", "clang-tidy", "pmd")


@dataclass(frozen=True)
class ExternalFinding:
    """One finding from an external linter report.

    Attributes:
        tool: Source tool (``eslint`` / ``clang-tidy`` / ``pmd``).
        rule_id: Tool rule identifier (e.g. ``no-var``).
        path: Repository-relative file path (posix separators).
        line: 1-based line number.
        column: 0-based column (best-effort; 0 when the tool reports none).
        message: Finding description.
        severity: Normalized severity (``error`` / ``warning`` / ``info``).
    """

    tool: str
    rule_id: str
    path: str
    line: int
    column: int = 0
    message: str = ""
    severity: str = "warning"


def normalize_path(raw: str, root: Path) -> str:
    """Normalize a report path to a posix, root-relative path.

    Absolute paths are relativized against ``root`` when possible; already
    relative paths are used as-is (posix separators).

    Args:
        raw: Path as written by the external tool.
        root: Repository root used for relativization.

    Returns:
        The normalized repository-relative posix path.
    """
    path = Path(raw)
    if path.is_absolute():
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            return path.as_posix()
    return path.as_posix()


def parse_report(tool: str, content: str, root: Path) -> list[ExternalFinding]:
    """Dispatch a report text to the importer for ``tool``.

    Args:
        tool: One of :data:`SUPPORTED_TOOLS`.
        content: Raw report text.
        root: Repository root for path normalization.

    Returns:
        Normalized external findings.

    Raises:
        ValueError: If ``tool`` is unsupported or the report is malformed.
    """
    if tool == "eslint":
        from lang_fossil.importers import eslint

        return eslint.parse(content, root)
    if tool == "clang-tidy":
        from lang_fossil.importers import clang_tidy

        return clang_tidy.parse(content, root)
    if tool == "pmd":
        from lang_fossil.importers import pmd

        return pmd.parse(content, root)
    raise ValueError(f"unsupported linter tool {tool!r}; use one of {SUPPORTED_TOOLS}")
