"""Golden language corpus regression (release gate, marked ``golden``).

C / C++ / C# / Java legacy corpora must hit their snapshot rule sets, modern
companion files must stay clean, and no file may report parse errors.
"""

from __future__ import annotations

import pathlib

import pytest

from lang_fossil.config import LangFossilSettings
from lang_fossil.core.engine import Engine
from lang_fossil.core.scanner import scan
from lang_fossil.core.zombie_api import ZombieApiDB
from lang_fossil.rules.registry import RuleRegistry

pytestmark = pytest.mark.golden

# repo name -> (expected legacy rule ids, modern file basenames that must be clean)
_LANGUAGE_CORPORA = {
    "c_legacy_repo": ({"CF001", "CF002", "CF003", "CF004"}, {"modern.c"}),
    "cpp_legacy_repo": ({"CXX001", "CXX002", "CXX003", "CXX004"}, {"modern.cpp"}),
    "csharp_legacy_repo": ({"CS001", "CS002", "CS003", "CS004"}, {"Modern.cs"}),
    "java_legacy_repo": ({"JV001", "JV002", "JV003", "JV004", "JV005", "JV006"}, {"Modern.java"}),
}


@pytest.fixture(scope="module")
def engine() -> Engine:
    """Full engine (builtin rules + zombie DB)."""
    return Engine(RuleRegistry.load_builtin(), ZombieApiDB.load())


def test_language_corpora(request: pytest.FixtureRequest, engine: Engine) -> None:
    """Legacy files hit the expected rules; modern files stay clean."""
    corpus_root = pathlib.Path(request.path).parent / "corpus"
    for repo, (expected, modern_files) in _LANGUAGE_CORPORA.items():
        result = scan(corpus_root / repo, LangFossilSettings(), engine)
        hits = {f.rule_id for f in result.fossils}
        missing = expected - hits
        assert not missing, f"{repo}: missing rules {missing}"
        assert result.parse_errors == (), f"{repo}: unexpected parse errors"
        flagged_modern = {f.path.rsplit("/", 1)[-1] for f in result.fossils} & modern_files
        assert not flagged_modern, f"{repo}: modern files flagged: {flagged_modern}"
