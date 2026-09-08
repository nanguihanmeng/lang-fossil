"""Unit tests for the C/C++/C#/Java builtin rule packs (heuristic matching)."""

from __future__ import annotations

import pytest

from lang_fossil.core.engine import Engine
from lang_fossil.parsers.heuristic import HeuristicParser
from lang_fossil.rules.registry import RuleRegistry

_PARSERS = {lang: HeuristicParser(lang).parse for lang in ("c", "cpp", "csharp", "java")}
_EXT = {"c": "x.c", "cpp": "x.cpp", "csharp": "x.cs", "java": "x.java"}


def _hits(builtin_registry: RuleRegistry, language: str, source: str) -> set[str]:
    """Parse a heuristic-language snippet and return matched rule ids."""
    engine = Engine(builtin_registry)
    parse_result = _PARSERS[language](source)
    return {f.rule_id for f in engine.run(_EXT[language], source, parse_result)}


@pytest.mark.parametrize(
    "language,source,expected",
    [
        ("c", "char buf[8];\ngets(buf);\n", {"CF001"}),
        ("c", 'sprintf(dst, "%d", n);\n', {"CF002"}),
        ("c", "strcpy(dst, src);\n", {"CF003"}),
        ("c", "register int i = 0;\n", {"CF004"}),
        ("cpp", "#include <iostream.h>\n", {"CXX001"}),
        ("cpp", "std::auto_ptr<int> p;\n", {"CXX002"}),
        ("cpp", "void f() throw() {}\n", {"CXX003"}),
        ("cpp", "register int x;\n", {"CXX004"}),
        ("cpp", "std::ptr_fun(f);\n", {"CXX005"}),
        ("csharp", "var list = new ArrayList();\n", {"CS001"}),
        ("csharp", "var map = new Hashtable();\n", {"CS002"}),
        ("csharp", "var s = new Stack();\n", {"CS003"}),
        ("csharp", "var f = new BinaryFormatter();\n", {"CS004"}),
        ("java", "Vector<String> v = new Vector<>();\n", {"JV001"}),
        ("java", "Hashtable<String, String> t;\n", {"JV002"}),
        ("java", "StringBuffer sb = new StringBuffer();\n", {"JV003"}),
        ("java", "Thread.stop(ex);\n", {"JV004"}),
        ("java", "protected void finalize() { }\n", {"JV005"}),
        ("java", "Integer i = new Integer(1);\n", {"JV006"}),
    ],
)
def test_legacy_rules_hit(
    builtin_registry: RuleRegistry, language: str, source: str, expected
) -> None:
    """Each new builtin rule fires on its canonical legacy snippet."""
    assert expected <= _hits(builtin_registry, language, source)


def test_c_modern_code_is_clean(builtin_registry: RuleRegistry) -> None:
    """Modern C idioms (fgets/snprintf/bounded copy) produce no C fossils."""
    source = (
        "#include <stdio.h>\n"
        "int main(void) {\n"
        "    char b[8];\n"
        "    if (fgets(b, sizeof b, stdin)) {\n"
        '        printf("%s", b);\n'
        "    }\n"
        "    return 0;\n"
        "}\n"
    )
    assert _hits(builtin_registry, "c", source) == set()


def test_csharp_modern_generics_are_clean(builtin_registry: RuleRegistry) -> None:
    """Generic collections (List/Dictionary/Stack<T>) are not flagged."""
    source = (
        "using System.Collections.Generic;\n"
        "var list = new List<string>();\n"
        "var map = new Dictionary<string, int>();\n"
        "var stack = new Stack<int>();\n"
    )
    assert _hits(builtin_registry, "csharp", source) == set()


def test_java_modern_apis_are_clean(builtin_registry: RuleRegistry) -> None:
    """Modern Java collections/StringBuilder are not flagged."""
    source = (
        "ArrayList<String> list = new ArrayList<>();\n"
        "HashMap<String, Integer> map = new HashMap<>();\n"
        "StringBuilder sb = new StringBuilder();\n"
    )
    assert _hits(builtin_registry, "java", source) == set()


def test_category_maps_to_era(builtin_registry: RuleRegistry) -> None:
    """Unsafe findings carry era 'unsafe'; fossils carry their dated era."""
    engine = Engine(builtin_registry)

    def eras(language: str, source: str) -> dict[str, str]:
        parse_result = _PARSERS[language](source)
        fossils = engine.run(_EXT[language], source, parse_result)
        return {f.rule_id: f.era for f in fossils}

    c_eras = eras("c", 'gets(buf);\nsprintf(d, "%s", s);\nstrcpy(d, s);\nregister int i;\n')
    assert c_eras["CF001"] == "c11"  # removed fossil, dated
    assert c_eras["CF002"] == "unsafe"  # still-legal bad practice, never dated
    assert c_eras["CF003"] == "unsafe"
    assert c_eras["CF004"] == "unsafe"

    cpp_eras = eras("cpp", "std::auto_ptr<int> p;\n")
    assert cpp_eras["CXX002"] == "cpp17"

    java_eras = eras("java", "Vector<String> v;\nThread.stop(ex);\n")
    assert java_eras["JV001"] == "unsafe"
    assert java_eras["JV004"] == "java-legacy"
