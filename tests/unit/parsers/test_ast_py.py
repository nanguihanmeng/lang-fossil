"""Unit tests for the stdlib ast fast path (mirrors parsers/ast_py.py)."""

from __future__ import annotations

from lang_fossil.parsers.ast_py import AstPythonParser, walk_names

parser = AstPythonParser()


def test_clean_parse() -> None:
    """Modern code parses with zero errors."""
    result = parser.parse("x = 1\n")
    assert result.tree is not None
    assert result.errors == ()


def test_syntax_error_degrades() -> None:
    """Syntax errors degrade into the errors channel."""
    result = parser.parse("def f(:\n")
    assert result.tree is None
    assert result.errors


def test_walk_names() -> None:
    """Names and attributes are collected with positions."""
    result = parser.parse("import os\n\nos.path.join(a)\n")
    names = walk_names(result.tree)
    flat = [name for name, _line, _col in names]
    assert "os" in flat
    assert "join" in flat
