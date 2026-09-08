"""Parser protocol shared by all language front ends.

Parsers never raise on syntax errors: they degrade (PRD "降级而非中断") and
report problems through :attr:`ParseResult.errors`. Implementations live in
``parso_py``, ``ast_py``, and ``js_heuristic``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from lang_fossil.core.models import ParseResult


@runtime_checkable
class Parser(Protocol):
    """Protocol implemented by every language front end."""

    language: str

    def parse(self, source: str, *, path: str = "<source>") -> ParseResult:
        """Parse source code into a :class:`ParseResult`.

        Args:
            source: Raw source text.
            path: Path used in diagnostics only.

        Returns:
            A parse result; ``tree`` is ``None`` when parsing failed outright.
        """
        ...  # pragma: no cover - protocol glue
