"""Generic regex-level front end for languages without an AST parser.

JavaScript and the C/C++/C#/Java family are matched with heuristic line rules
only: no structural parse is attempted. Results are flagged ``heuristic=True``
so downstream consumers can annotate confidence (see ``ParseResult``).
"""

from __future__ import annotations

from lang_fossil.core.models import ParseResult

_BINARY_SNIFF_LEN = 1024


class HeuristicParser:
    """Regex-level parser (no AST) for a given heuristic language.

    Args:
        language: The language tag reported on every parse result (e.g.
            ``javascript``, ``c``, ``cpp``, ``csharp``, ``java``).
    """

    def __init__(self, language: str) -> None:
        """Bind this parser to one language."""
        self.language = language

    def parse(self, source: str, *, path: str = "<source>") -> ParseResult:
        """Treat source as plain lines; no structural parse is attempted.

        Args:
            source: Raw source text.
            path: Path used in diagnostics only.

        Returns:
            Parse result with ``tree=None`` and ``heuristic=True``; a null
            byte in the sniff window marks the file as binary and yields an
            error entry.
        """
        if "\x00" in source[:_BINARY_SNIFF_LEN]:
            return ParseResult(
                tree=None,
                errors=("binary content skipped",),
                language=self.language,
                grammar_version="n/a",
                heuristic=True,
            )
        return ParseResult(
            tree=None,
            errors=(),
            language=self.language,
            grammar_version="n/a",
            heuristic=True,
        )
