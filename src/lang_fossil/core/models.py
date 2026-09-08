"""Domain models for lang-fossil.

Domain objects are frozen dataclasses (see PRD section 5.1); configuration
models use pydantic (see :mod:`lang_fossil.config`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Reserved era / rule identifiers. These strings carry aggregation semantics
# (unsafe findings form their own stratum; meta findings are tool-level), so
# they live in one place to keep every comparison on the same spelling.
ERA_UNSAFE = "unsafe"
ERA_META = "meta"
RULE_ID_META = "LF-IO"


@dataclass(frozen=True)
class Fossil:
    """A single detected legacy artifact.

    Attributes:
        rule_id: Identifier of the rule that produced this fossil.
        path: Repository-relative path of the file containing it.
        line: 1-based line number.
        column: 0-based column number.
        message: Human-readable description.
        era: Language era label (e.g. ``paleozoic``, ``mesozoic``).
        provenance: Where the rule originated (e.g. ``pyupgrade``, ``internal``).
        severity: One of ``info``, ``warning``, ``error``.
        fix_hint: Optional suggestion bridging to an external fixer.
        last_commit_year: Year of the file's last commit from optional git
            enrichment; ``None`` when git dating is off, the file is not in a
            repository, or the commit year is unknown.
    """

    rule_id: str
    path: str
    line: int
    column: int
    message: str
    era: str
    provenance: str
    severity: str = "warning"
    fix_hint: str | None = None
    # Optional git enrichment; None when dating is off/unknown. Kept at the end
    # with a default so stale cached payloads (which lack the key) still load.
    last_commit_year: int | None = None


@dataclass(frozen=True)
class ParseResult:
    """Outcome of parsing one file; parsing failures degrade, never abort.

    Attributes:
        tree: The parsed tree (parser-specific), or ``None`` on hard failure.
        errors: Non-fatal parse/syntax errors collected during parsing.
        language: Sniffed language (``python`` or ``javascript``).
        grammar_version: Grammar version used by the parser (e.g. ``"2.7"``),
            or ``"n/a"`` for heuristic parsers.
        heuristic: True when the parse (or language) is regex-heuristic only.
    """

    tree: object | None
    errors: tuple[str, ...]
    language: str
    grammar_version: str
    heuristic: bool = False


@dataclass(frozen=True)
class FileEntry:
    """A file selected for scanning."""

    path: str
    language: str


@dataclass(frozen=True)
class CloneMatch:
    """A cross-file code clone detected by fingerprinting.

    Attributes:
        path_a / line_a: First occurrence location.
        path_b / line_b: Second occurrence location.
        fingerprint: Shared k-gram hash.
        token_count: Length of the duplicated token sequence.
    """

    path_a: str
    line_a: int
    path_b: str
    line_b: int
    fingerprint: str
    token_count: int


@dataclass(frozen=True)
class ScanResult:
    """Aggregated result of a full scan."""

    fossils: tuple[Fossil, ...]
    scanned_files: int
    scanned_lines: int
    skipped_files: int
    parse_errors: tuple[str, ...]
    clones: tuple[CloneMatch, ...] = field(default_factory=tuple)
