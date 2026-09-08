"""Language sniffing shared by discovery, rule packs and ``--fix`` bridging.

Classification is extension-based. The C/C++ ``.h`` extension is ambiguous and
is resolved by *configuration*, not by content scoring: the scan settings
carry an ``ambiguous_headers`` policy (``mode`` plus glob ``overrides``), and
the discovery stage resolves each header against it (see
:mod:`lang_fossil.core.scanner`).
"""

from __future__ import annotations

from pathlib import Path

# Canonical language identifiers. Keep in sync with RuleSpec.language and the
# scanner ``parsers`` registry.
SUPPORTED_LANGUAGES = ("python", "javascript", "c", "cpp", "csharp", "java")

# Languages served by a generic line-based parser (HeuristicParser). Python is
# excluded: it has a real tree front end (parso/ast). Derived from the single
# SUPPORTED_LANGUAGES list so a new language cannot be forgotten in the
# scanner's parser registry.
HEURISTIC_LANGUAGES = tuple(lang for lang in SUPPORTED_LANGUAGES if lang != "python")

# Marker for the ambiguous C/C++ header extension; resolved by config policy.
HEADER_AMBIGUOUS = "c_header"

_LANG_BY_EXT = {
    ".py": "python",
    ".pyw": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".c": "c",
    ".h": HEADER_AMBIGUOUS,  # resolved by the ambiguous_headers policy
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".hxx": "cpp",
    ".cs": "csharp",
    ".java": "java",
}


def sniff_language(path: Path) -> str | None:
    """Sniff the language of a file from its extension.

    Args:
        path: Candidate file path.

    Returns:
        A language identifier, ``HEADER_AMBIGUOUS`` for C/C++ headers that
        need configuration-based resolution, or ``None`` for unsupported
        files.
    """
    return _LANG_BY_EXT.get(path.suffix.lower())


__all__ = [
    "HEADER_AMBIGUOUS",
    "HEURISTIC_LANGUAGES",
    "SUPPORTED_LANGUAGES",
    "sniff_language",
]
