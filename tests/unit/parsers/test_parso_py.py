"""Unit tests for the parso front end, including the Py2 release gate.

The Py2 cases double as the M0 PoC evidence required by the spec: parso
parses Python 2 corpora on a Python 3 interpreter (via the vendored
``grammar27.txt``; modern parso dropped the file, see ADR-0001).
"""

from __future__ import annotations

import pytest

from lang_fossil.parsers import parso_py
from lang_fossil.parsers.parso_py import ParsoPythonParser

parser = ParsoPythonParser()


def test_modern_python_parses_clean() -> None:
    """Modern syntax produces a tree with no errors."""
    result = parser.parse("def f(x: int) -> int:\n    return x + 1\n")
    assert result.tree is not None
    assert result.errors == ()
    assert result.grammar_version == "3.x"


@pytest.mark.parametrize(
    "source",
    [
        "print 'hello'\n",
        "raise ValueError, 'msg'\n",
        "x = `repr_me`\n",
        "exec 'code'\n",
    ],
)
def test_py2_syntax_parses_with_27_grammar(source: str) -> None:
    """Pure Py2 constructs parse via the vendored 2.7 grammar fallback."""
    result = parser.parse(source)
    assert result.tree is not None
    assert result.grammar_version == "2.7"
    assert result.errors == ()


def test_py2_print_statement_tree_type() -> None:
    """The py2 tree actually contains a print_stmt node (engine contract)."""
    result = parser.parse("print 'hello'\n")
    types = set()
    stack = [result.tree]
    while stack:
        node = stack.pop()
        types.add(getattr(node, "type", ""))
        stack.extend(getattr(node, "children", []))
    assert "print_stmt" in types


def test_unrecoverable_source_reports_errors() -> None:
    """Genuinely invalid code reports errors without raising."""
    result = parser.parse("def f(:\n")
    assert result.errors


def test_language_tag() -> None:
    """The parser advertises the python language."""
    assert parser.language == "python"


def test_missing_py2_grammar_degrades(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the vendored 2.7 grammar is unavailable, scanning still works."""
    monkeypatch.setattr(parso_py, "_load_py2_grammar", lambda: None)
    result = parser.parse("print 'x'\n")
    assert result.grammar_version == "3.x"
    assert result.errors  # modern grammar reported the py2 syntax problem


def test_default_grammar_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """An interpreter newer than parso's grammars falls back to the newest."""
    real_load = parso_py.parso.load_grammar

    def _reject_current(*args: object, **kwargs: object) -> object:
        if "path" not in kwargs:
            raise NotImplementedError("3.99 is currently not supported.")
        return real_load(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(parso_py.parso, "load_grammar", _reject_current)
    result = parser.parse("x = 1\n")
    assert result.tree is not None
    assert result.errors == ()


def test_no_grammar_at_all_degrades(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no loadable grammar the parser degrades instead of raising."""
    monkeypatch.setattr(parso_py, "_load_default_grammar", lambda: None)
    result = parser.parse("x = 1\n")
    assert result.tree is None
    assert "grammar unavailable" in result.errors[0]


def test_parser_failure_degrades(monkeypatch: pytest.MonkeyPatch) -> None:
    """A parser crash surfaces as an error entry, never an exception."""
    real = parso_py._load_default_grammar

    def _broken() -> object:
        grammar = real()
        assert grammar is not None

        class _Boom:
            def parse(self, source: str) -> object:
                raise ValueError("boom")

        return _Boom()

    monkeypatch.setattr(parso_py, "_load_default_grammar", _broken)
    result = parser.parse("x = 1\n")
    assert result.tree is None
    assert "parser failure" in result.errors[0]
