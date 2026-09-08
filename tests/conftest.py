"""Shared pytest fixtures for the lang-fossil test suite."""

from __future__ import annotations

from pathlib import Path

import pytest

from lang_fossil.core.engine import Engine
from lang_fossil.core.zombie_api import ZombieApiDB
from lang_fossil.rules.registry import RuleRegistry


@pytest.fixture(scope="session")
def builtin_registry() -> RuleRegistry:
    """Load the builtin rule registry once per session."""
    return RuleRegistry.load_builtin()


@pytest.fixture(scope="session")
def zombie_db() -> ZombieApiDB:
    """Load the bundled offline zombie API snapshot once per session."""
    return ZombieApiDB.load()


@pytest.fixture()
def engine(builtin_registry: RuleRegistry, zombie_db: ZombieApiDB) -> Engine:
    """An engine wired with builtin rules and the zombie DB."""
    return Engine(builtin_registry, zombie_db)


@pytest.fixture()
def py_repo(tmp_path: Path) -> Path:
    """A small synthetic repo with paleozoic and modern Python files."""
    (tmp_path / "legacy").mkdir()
    (tmp_path / "modern").mkdir()
    (tmp_path / "legacy" / "old.py").write_text(
        "import cPickle\n"
        "print 'hello'\n"
        "d = {}\n"
        "if d.has_key('k'):\n"
        "    for i in xrange(10):\n"
        "        print i\n",
        encoding="utf-8",
    )
    (tmp_path / "modern" / "new.py").write_text(
        "import pickle\n\nprint('hello')\n\n\ndef main() -> None:\n"
        "    for i in range(10):\n        print(i)\n",
        encoding="utf-8",
    )
    return tmp_path
