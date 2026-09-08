"""Heuristic JavaScript front end (thin wrapper over :class:`HeuristicParser`).

Kept as a distinct class so existing imports and the JS-specific docstring
semantics stay stable; behaviour is identical to the generic heuristic parser.
"""

from __future__ import annotations

from lang_fossil.parsers.heuristic import HeuristicParser


class JsHeuristicParser(HeuristicParser):
    """Regex-level JS "parser" (no AST)."""

    def __init__(self) -> None:
        """Bind the parser to the JavaScript language."""
        super().__init__("javascript")
