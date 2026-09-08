"""Unit tests for the rule engine (mirrors src/lang_fossil/core/engine.py)."""

from __future__ import annotations

import pytest

from lang_fossil.core.engine import Engine
from lang_fossil.parsers.parso_py import ParsoPythonParser

pytestmark = pytest.mark.usefixtures("engine")


def _run(engine: Engine, source: str):
    """Helper: parse + match a Python snippet."""
    parse_result = ParsoPythonParser().parse(source)
    return engine.run("<test>", source, parse_result)


def test_print_statement_hits_py2_grammar(builtin_registry) -> None:
    """PF001 must fire through the py2 grammar fallback."""
    engine = Engine(builtin_registry)
    fossil_ids = {f.rule_id for f in _run(engine, "print 'hi'\n")}
    assert "PF001" in fossil_ids


def test_xrange_and_has_key(engine) -> None:
    """PF003/PF004 hit attribute and name rules."""
    ids = {f.rule_id for f in _run(engine, "d.has_key(k) and xrange(3)\n")}
    assert {"PF003", "PF004"} <= ids


def test_ur_string_prefix(engine) -> None:
    """PF002 hits the ur-prefix string rule."""
    ids = {f.rule_id for f in _run(engine, 'x = ur"text"\n')}
    assert "PF002" in ids


def test_import_rule_matches(engine) -> None:
    """import-kind rules fire on the imported module name."""
    ids = {f.rule_id for f in _run(engine, "import sets\n")}
    assert "PF006" in ids


def test_modern_code_is_clean(engine) -> None:
    """Modern Python must produce no builtin-rule fossils."""
    source = "import sys\nprint(sys.version)\nif k in d:\n    pass\n"
    ids = {f.rule_id for f in _run(engine, source)}
    assert not ids


def test_heuristic_raise_comma(engine) -> None:
    """PF008 is line-based and works even without a usable tree."""
    ids = {f.rule_id for f in _run(engine, "raise ValueError, 'x'\n")}
    assert "PF008" in ids


def test_parse_failure_degrades(engine) -> None:
    """A tree-less parse result only runs line rules, never raises."""
    from lang_fossil.core.models import ParseResult

    result = ParseResult(tree=None, errors=(), language="python", grammar_version="3.x")
    fossils = engine.run("<t>", "raise E, msg\n", result)
    assert {f.rule_id for f in fossils} == {"PF008"}


def test_js_regex_rules(builtin_registry) -> None:
    """JS rules run in heuristic mode on raw lines."""
    from lang_fossil.parsers.js_heuristic import JsHeuristicParser

    engine = Engine(builtin_registry)
    source = "var x = 1;\nwith (o) { y = 2; }\neval('1+1');\n"
    parse_result = JsHeuristicParser().parse(source)
    ids = {f.rule_id for f in engine.run("a.js", source, parse_result)}
    assert {"JS001", "JS002", "JS004"} <= ids


def test_rules_digest_stable(engine) -> None:
    """The digest is deterministic across engine instances."""
    import hashlib

    from lang_fossil.core.zombie_api import ZombieApiDB
    from lang_fossil.rules.registry import RuleRegistry

    other = Engine(RuleRegistry.load_builtin(), ZombieApiDB.load())
    assert engine.rules_digest() == other.rules_digest()
    assert len(engine.rules_digest()) == len(hashlib.sha256(b"").hexdigest()[:16])


def test_rules_digest_incorporates_snapshot_version(builtin_registry) -> None:
    """A snapshot data update must invalidate cached scan results."""
    from lang_fossil.core.zombie_api import ZombieApiDB

    old = Engine(builtin_registry, ZombieApiDB({"snapshot_version": "2026.01", "packages": []}))
    new = Engine(builtin_registry, ZombieApiDB({"snapshot_version": "2026.09", "packages": []}))
    assert old.rules_digest() != new.rules_digest()
