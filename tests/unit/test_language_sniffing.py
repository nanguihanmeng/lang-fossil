"""Unit tests for extension-based language sniffing."""

from __future__ import annotations

from pathlib import Path

from lang_fossil.core.language import HEADER_AMBIGUOUS, sniff_language


def test_sniff_known_extensions() -> None:
    """Python, JS, C-family and Java extensions map to languages."""
    assert sniff_language(Path("a.py")) == "python"
    assert sniff_language(Path("b.pyw")) == "python"
    assert sniff_language(Path("c.js")) == "javascript"
    assert sniff_language(Path("d.mjs")) == "javascript"
    assert sniff_language(Path("e.cjs")) == "javascript"
    assert sniff_language(Path("f.jsx")) == "javascript"
    assert sniff_language(Path("g.c")) == "c"
    assert sniff_language(Path("h.cpp")) == "cpp"
    assert sniff_language(Path("i.cc")) == "cpp"
    assert sniff_language(Path("j.cxx")) == "cpp"
    assert sniff_language(Path("k.hpp")) == "cpp"
    assert sniff_language(Path("l.hh")) == "cpp"
    assert sniff_language(Path("m.hxx")) == "cpp"
    assert sniff_language(Path("n.cs")) == "csharp"
    assert sniff_language(Path("o.java")) == "java"


def test_header_extension_is_ambiguous() -> None:
    """.h is marked ambiguous; unsupported extensions map to None."""
    assert sniff_language(Path("u.h")) == HEADER_AMBIGUOUS
    assert sniff_language(Path("v.rb")) is None
    assert sniff_language(Path("w.txt")) is None
