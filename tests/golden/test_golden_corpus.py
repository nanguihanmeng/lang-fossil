"""Golden corpus regression (release gate, marked ``golden``).

Spec section 4.2: the pure-Py2 corpus MUST parse and hit the expected rule
set; the mixed-era corpus additionally exercises zombie detection and clone
fingerprints. Expected hits are snapshotted inline: any diff is a release
blocker.
"""

from __future__ import annotations

import pathlib

import pytest

from lang_fossil.config import LangFossilSettings
from lang_fossil.core.engine import Engine
from lang_fossil.core.scanner import scan
from lang_fossil.core.stratigraphy import build_report
from lang_fossil.core.zombie_api import ZombieApiDB
from lang_fossil.rules.registry import RuleRegistry

pytestmark = pytest.mark.golden


def _corpus_root(request: pytest.FixtureRequest) -> pathlib.Path:
    """Resolve tests/golden/corpus from this file's location."""
    return pathlib.Path(request.path).parent / "corpus"


@pytest.fixture(scope="module")
def engine() -> Engine:
    """Full engine (builtin rules + zombie DB)."""
    return Engine(RuleRegistry.load_builtin(), ZombieApiDB.load())


def _scan_dir(root, engine: Engine):
    """Scan a corpus directory."""
    import pathlib

    return scan(pathlib.Path(root), LangFossilSettings(), engine)


def test_py2_repo_parses_and_hits(request, engine: Engine) -> None:
    """Pure Py2 corpus: parso parses it and the snapshot matches."""
    root = _corpus_root(request) / "py2_syntax_repo"
    result = _scan_dir(root, engine)
    assert result.scanned_files == 1
    hits = {f.rule_id for f in result.fossils}
    expected = {"PF001", "PF003", "PF004", "PF006", "PF007", "PF008"}
    assert expected <= hits, f"missing: {expected - hits}"
    assert result.parse_errors == ()


def test_mixed_repo_hits(request, engine: Engine) -> None:
    """Mixed-era corpus: legacy files hit, modern files stay clean."""
    root = _corpus_root(request) / "mixed_era_repo"
    result = _scan_dir(root, engine)
    hits = {f.rule_id for f in result.fossils}
    assert {"PF001", "PF003", "PF004", "PF002"} <= hits
    # zombie snapshot: asyncore removed in 3.12
    assert "ZA-asyncore" in hits
    modern = [f for f in result.fossils if "modern/" in f.path]
    assert modern == []


def test_clone_corpus_flagged(request, engine: Engine) -> None:
    """Duplicated helper across two files is fingerprinted."""
    root = _corpus_root(request) / "mixed_era_repo"
    result = _scan_dir(root, engine)
    pairs = {(c.path_a, c.path_b) for c in result.clones}
    flagged = any(
        {"copy_paste.py", "copy_paste_clone.py"} <= {a.rsplit("/", 1)[-1], b.rsplit("/", 1)[-1]}
        for a, b in pairs
    )
    assert flagged, f"clone corpus not flagged: {pairs}"


def test_fossil_index_sane(request, engine: Engine) -> None:
    """The py2 corpus produces a positive, bounded fossil index."""
    root = _corpus_root(request) / "py2_syntax_repo"
    result = _scan_dir(root, engine)
    report = build_report(result)
    assert 0 < report.fossil_index < 1000
