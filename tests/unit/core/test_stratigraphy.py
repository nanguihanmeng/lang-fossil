"""Unit tests for stratigraphy aggregation (mirrors core/stratigraphy.py)."""

from __future__ import annotations

from datetime import date

import pytest

from lang_fossil.core.models import CloneMatch, Fossil, ScanResult
from lang_fossil.core.stratigraphy import build_report, compute_fossil_index


def _dated_fossil(
    rule: str,
    era: str,
    year: int | None,
    *,
    path: str = "a/old.py",
) -> Fossil:
    """Build a fossil carrying a git-dating year (or None)."""
    return Fossil(
        rule_id=rule,
        path=path,
        line=1,
        column=0,
        message="m",
        era=era,
        provenance="test",
        last_commit_year=year,
    )


def _fossil(rule: str = "PF001", path: str = "a/old.py", era: str = "paleozoic") -> Fossil:
    """Build a synthetic fossil."""
    return Fossil(
        rule_id=rule,
        path=path,
        line=1,
        column=0,
        message="m",
        era=era,
        provenance="test",
    )


def test_fossil_index_basic() -> None:
    """20 fossils in 1000 lines -> index 20."""
    assert compute_fossil_index(20, 1000) == 20.0


def test_fossil_index_zero_lines() -> None:
    """Zero scanned lines yields 0.0 (guard per spec section 2.2)."""
    assert compute_fossil_index(5, 0) == 0.0


def test_fossil_index_negative_lines() -> None:
    """Negative input raises ValueError."""
    with pytest.raises(ValueError, match="non-negative"):
        compute_fossil_index(1, -1)


def test_build_report_aggregates() -> None:
    """Eras, rules, modules and severity buckets aggregate correctly."""
    scan_result = ScanResult(
        fossils=(
            _fossil(),
            _fossil(),
            _fossil(rule="PF004", path="a/old.py"),
            _fossil(rule="JS001", path="b/x.js", era="mesozoic"),
        ),
        scanned_files=4,
        scanned_lines=2000,
        skipped_files=1,
        parse_errors=(),
        clones=(CloneMatch("a/old.py", 1, "b/copy.py", 5, "ff00", 8),),
    )
    report = build_report(scan_result)
    assert report.total_fossils == 4
    assert report.fossil_index == 2.0
    assert report.clone_count == 1
    eras = {era.era: era.fossil_count for era in report.eras}
    assert eras == {"paleozoic": 3, "mesozoic": 1}
    assert report.by_rule == {"PF001": 2, "PF004": 1, "JS001": 1}
    assert report.by_module == {"a": 3, "b": 1}
    paleo = next(era for era in report.eras if era.era == "paleozoic")
    assert paleo.top_modules[0] == ("a/old.py", 3)


def test_empty_scan_is_zeroed() -> None:
    """An empty scan produces a well-formed zero report."""
    report = build_report(ScanResult((), 0, 0, 0, (), ()))
    assert report.total_fossils == 0
    assert report.unsafe_count == 0
    assert report.fossil_index == 0.0
    assert report.eras == ()


def test_unsafe_findings_reported_separately() -> None:
    """Unsafe (never-dated) findings count apart and form their own stratum."""
    result = ScanResult(
        fossils=(
            _fossil(),
            _fossil(rule="CF002", path="a/old.c", era="unsafe"),
            _fossil(rule="JV004", path="b/x.java", era="java-legacy"),
        ),
        scanned_files=2,
        scanned_lines=100,
        skipped_files=0,
        parse_errors=(),
        clones=(),
    )
    report = build_report(result)
    assert report.total_fossils == 3
    assert report.unsafe_count == 1
    order = [era.era for era in report.eras]
    assert order == ["paleozoic", "java-legacy", "unsafe"]


def test_git_counters_zero_without_dating() -> None:
    """No commit years -> dated/active counters stay zero."""
    report = build_report(ScanResult((_fossil(),), 1, 10, 0, (), ()))
    assert report.git_dated_fossils == 0
    assert report.active_fossils == 0


def test_active_fossils_window() -> None:
    """Recently committed legacy fossils are 'active'; stale and non-legacy ones are not."""
    now = date.today().year
    result = ScanResult(
        fossils=(
            # Old code touched this year -> active legacy.
            _dated_fossil("PF001", "paleozoic", now),
            # Dated but dormant for years -> not active, still counted as dated.
            _dated_fossil("PF004", "paleozoic", now - 10),
            # Unsafe findings never masquerade as dated legacy.
            _dated_fossil("JS001", "unsafe", now),
            # Meta (tool-level) findings are not legacy either.
            _dated_fossil("LF-IO", "meta", now),
            # Undated fossil.
            _dated_fossil("JV004", "java-legacy", None),
        ),
        scanned_files=5,
        scanned_lines=500,
        skipped_files=0,
        parse_errors=(),
        clones=(),
    )
    report = build_report(result)
    assert report.git_dated_fossils == 4
    assert report.active_fossils == 1
