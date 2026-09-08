"""Contract tests for the Parser protocol (mirrors parsers/base.py)."""

from __future__ import annotations

from lang_fossil.core.models import ParseResult
from lang_fossil.parsers.ast_py import AstPythonParser
from lang_fossil.parsers.base import Parser
from lang_fossil.parsers.js_heuristic import JsHeuristicParser
from lang_fossil.parsers.parso_py import ParsoPythonParser


def test_all_parsers_satisfy_protocol() -> None:
    """Every front end is runtime-checkable against the Parser protocol."""
    parsers = [ParsoPythonParser(), AstPythonParser(), JsHeuristicParser()]
    for parser in parsers:
        assert isinstance(parser, Parser)
        assert parser.language in {"python", "javascript"}


def test_protocol_never_raises_contract() -> None:
    """Implementations return ParseResult instead of raising on bad input."""
    for parser in (ParsoPythonParser(), AstPythonParser(), JsHeuristicParser()):
        result = parser.parse("\x00 broken \x00", path="t")
        assert isinstance(result, ParseResult)
