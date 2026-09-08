"""Unit tests for zombie API detection (mirrors core/zombie_api.py)."""

from __future__ import annotations

import pytest

from lang_fossil.core.zombie_api import ZombieApiDB, detect_zombie_apis
from lang_fossil.parsers.parso_py import ParsoPythonParser


def _fossil_ids(source: str) -> set[str]:
    """Helper: parse + detect rule ids for one snippet."""
    parse_result = ParsoPythonParser().parse(source)
    db = ZombieApiDB.load()
    return {f.rule_id for f in detect_zombie_apis("a.py", parse_result, db)}


def test_db_loads_bundled_snapshot(zombie_db: ZombieApiDB) -> None:
    """The bundled snapshot must index distutils at minimum."""
    assert zombie_db.entry_count > 0


def test_removed_module_import(zombie_db: ZombieApiDB) -> None:
    """Importing distutils yields a ZA fossil with replacement hint."""
    parse_result = ParsoPythonParser().parse("import distutils\n")
    fossils = detect_zombie_apis("a.py", parse_result, zombie_db)
    assert any(f.rule_id == "ZA-distutils" for f in fossils)
    distutils = next(f for f in fossils if f.rule_id == "ZA-distutils")
    assert "3.12" in distutils.message
    assert distutils.severity == "error"


def test_removed_submodule_import(zombie_db: ZombieApiDB) -> None:
    """Submodule imports of a removed package are flagged too."""
    assert "ZA-distutils" in _fossil_ids("import distutils.util\n")


def test_lib2to3_removal_detected(zombie_db: ZombieApiDB) -> None:
    """lib2to3 (removed in 3.13) is covered by the snapshot."""
    assert "ZA-lib2to3" in _fossil_ids("import lib2to3\n")


def test_removed_module_from_import(zombie_db: ZombieApiDB) -> None:
    """from imp import ... is detected as well."""
    parse_result = ParsoPythonParser().parse("from imp import find_module\n")
    fossils = detect_zombie_apis("a.py", parse_result, zombie_db)
    assert any(f.rule_id == "ZA-imp" for f in fossils)


def test_relative_import_skipped(zombie_db: ZombieApiDB) -> None:
    """Relative imports have no stable root and produce no fossils."""
    assert _fossil_ids("from . import sibling\n") == set()


def test_alias_and_multi_import(zombie_db: ZombieApiDB) -> None:
    """Aliased and comma-separated imports are both recognized."""
    assert "ZA-imp" in _fossil_ids("import imp as legacy\n")
    assert {"ZA-imp"} <= _fossil_ids("import os, imp\n")


def test_attribute_chain_detection(zombie_db: ZombieApiDB) -> None:
    """asyncio.get_event_loop() matches the attribute-level entry."""
    source = "import asyncio\n\nasync def main():\n    asyncio.get_event_loop()\n"
    parse_result = ParsoPythonParser().parse(source)
    fossils = detect_zombie_apis("a.py", parse_result, zombie_db)
    assert any(f.rule_id == "ZA-asyncio.get_event_loop" for f in fossils)


def test_attribute_bare_name_after_import(zombie_db: ZombieApiDB) -> None:
    """Bare attribute use is caught when the module root is imported."""
    source = "from asyncio import get_event_loop\n\nget_event_loop()\n"
    assert "ZA-asyncio.get_event_loop" in _fossil_ids(source)


def test_no_false_positive_on_live_apis(zombie_db: ZombieApiDB) -> None:
    """Modern importlib usage must be clean."""
    parse_result = ParsoPythonParser().parse("import importlib\nimportlib.metadata\n")
    fossils = detect_zombie_apis("a.py", parse_result, zombie_db)
    assert fossils == []


def test_tree_none_degrades(zombie_db: ZombieApiDB) -> None:
    """No tree -> no fossils, no exception."""
    from lang_fossil.core.models import ParseResult

    result = ParseResult(tree=None, errors=(), language="python", grammar_version="3.x")
    assert detect_zombie_apis("a.py", result, zombie_db) == []


def test_dotted_attribute_entries_rejected() -> None:
    """A dotted attribute would silently never match; reject it at load."""
    with pytest.raises(ValueError, match="dotted attribute"):
        ZombieApiDB(
            {
                "snapshot_version": "test",
                "packages": [{"module": "turtle", "attribute": "RawTurtle.pen"}],
            }
        )


def test_single_name_attribute_detected(zombie_db: ZombieApiDB) -> None:
    """The snapshot's attribute-level entries (single names) match."""
    parse_result = ParsoPythonParser().parse("import inspect\ninspect.getargspec(fn)\n")
    fossils = detect_zombie_apis("a.py", parse_result, zombie_db)
    assert any(f.rule_id == "ZA-inspect.getargspec" for f in fossils)


def test_snapshot_error(tmp_path, monkeypatch) -> None:
    """A corrupt snapshot raises SnapshotError."""
    from lang_fossil.infra.offline_db import SnapshotError, load_snapshot

    bad = tmp_path / "dead-packages.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(SnapshotError):
        load_snapshot(bad)
