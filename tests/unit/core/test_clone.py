"""Unit tests for winnowing clone detection (mirrors core/clone.py)."""

from __future__ import annotations

from lang_fossil.core.clone import _kgram_hashes, _winnow, detect_clones, tokenize


def test_tokenize_drops_comments_and_case() -> None:
    """Comments are dropped and identifiers normalized to lower case."""
    tokens = tokenize("Foo = 1  # comment\nBar\n")
    values = [v for v, _line in tokens]
    assert values == ["foo", "=", "1", "bar"]


def test_tokenize_tracks_line_numbers() -> None:
    """Each token carries the 1-based line it appears on."""
    tokens = tokenize("x = 1\n\n# comment only line\ny = 2\n")
    assert [(v, line) for v, line in tokens] == [
        ("x", 1),
        ("=", 1),
        ("1", 1),
        ("y", 4),
        ("=", 4),
        ("2", 4),
    ]


def test_kgram_hashes_short_input() -> None:
    """Fewer than k tokens produce no fingerprints."""
    tokens = tokenize("x = 1\n")
    assert _kgram_hashes(tokens, 8) == []


def test_winnow_selects_minima() -> None:
    """Winnowing returns at most one fingerprint per window."""
    hashes = [("f0", 1), ("f1", 2), ("f2", 3), ("f3", 4), ("f4", 5)]
    selected = _winnow(hashes, 2)
    assert 0 < len(selected) < len(hashes)
    assert all(h in hashes for h in selected)


def test_identical_files_detected() -> None:
    """Duplicated code across files yields clone matches."""
    body = (
        "def compute(values):\n"
        "    total = 0\n"
        "    for value in values:\n"
        "        total += value * 2 + 7\n"
        "    return total\n"
    )
    clones = detect_clones([("a.py", body), ("b.py", body)])
    assert len(clones) == 1
    match = clones[0]
    assert {match.path_a, match.path_b} == {"a.py", "b.py"}
    assert match.token_count == 8


def test_distinct_files_not_flagged() -> None:
    """Unrelated small files produce no clones."""
    clones = detect_clones([("a.py", "x = 1\n"), ("b.py", "y = 2\n")])
    assert clones == []


def test_pair_cap_respected() -> None:
    """The matcher caps output to keep reports usable."""
    body = (
        "def compute(values):\n"
        "    total = 0\n"
        "    for value in values:\n"
        "        total += value\n"
        "    return total\n"
    ) * 3
    files = [(f"f{i}.py", body) for i in range(10)]
    clones = detect_clones(files)
    assert len(clones) <= 200
