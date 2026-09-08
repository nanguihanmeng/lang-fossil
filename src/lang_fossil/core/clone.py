"""Code clone fingerprinting via winnowing (P1 differentiator).

Detects cross-file copy-pasted code: "the same fossil appearing in three
strata". Token streams are hashed into k-grams, and the classic winnowing
algorithm (Schleimer et al., 2007) selects a minimal fingerprint set with a
guarantee: any match longer than the window size is detected.

Status: experimental *archaeological signal* — repeated legacy code across
strata. Not a general-purpose duplicate detector; dedicated tools (PMD-CPD
and friends) own that space.
"""

from __future__ import annotations

import hashlib
import re

from lang_fossil.core.models import CloneMatch

_TOKEN_RE = re.compile(r"[A-Za-z_]\w*|\d+(?:\.\d+)?|\"[^\"]*\"|'[^']*'|[^\s\w]")

# Comment syntax stripped before tokenizing (Python + JS conventions).
_LINE_COMMENT_RE = re.compile(r"#[^\n]*|//[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)

_DEFAULT_K = 8  # k-gram length (tokens)
_DEFAULT_W = 4  # winnowing window (hashes)
_MAX_PAIRS = 200  # report cap to keep reports usable
_MIN_CLONE_SITES = 2  # a fingerprint needs >=2 distinct sites to be a clone


def tokenize(source: str) -> list[tuple[str, int]]:
    """Tokenize source into normalized tokens with line numbers.

    Comments and whitespace are dropped implicitly (they match no token);
    token values are case-normalized for identifiers.

    Args:
        source: Raw source text (any brace/indent language).

    Returns:
        Tuples of ``(token, line)``.
    """
    tokens: list[tuple[str, int]] = []
    line = 1
    last_end = 0
    stripped = _LINE_COMMENT_RE.sub(" ", _BLOCK_COMMENT_RE.sub(" ", source))
    for match in _TOKEN_RE.finditer(stripped):
        value = match.group(0)
        line += stripped.count("\n", last_end, match.start())
        last_end = match.end()
        if re.match(r"[A-Za-z_]", value):
            value = value.lower()
        tokens.append((value, line))
    return tokens


def _kgram_hashes(tokens: list[tuple[str, int]], k: int) -> list[tuple[str, int]]:
    """Hash every k-gram to a stable digest.

    Args:
        tokens: Token stream from :func:`tokenize`.
        k: K-gram length.

    Returns:
        Tuples of ``(fingerprint, line_of_first_token)``; fewer than ``k``
        tokens yields no fingerprints.
    """
    if len(tokens) < k:
        return []
    hashes: list[tuple[str, int]] = []
    parts = [value for value, _line in tokens]
    for index in range(len(tokens) - k + 1):
        gram = " ".join(parts[index : index + k])
        digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=8).hexdigest()
        hashes.append((digest, tokens[index][1]))
    return hashes


def _winnow(hashes: list[tuple[str, int]], w: int) -> list[tuple[str, int]]:
    """Select the winnowing fingerprint set (rightmost minimum per window).

    Args:
        hashes: K-gram hashes from :func:`_kgram_hashes`.
        w: Window size.

    Returns:
        Selected ``(fingerprint, line)`` pairs.
    """
    if not hashes:
        return []
    if len(hashes) <= w:
        return [min(hashes, key=lambda item: (item[0], -item[1]))]
    selected: list[tuple[str, int]] = []
    last_index = -1
    for start in range(len(hashes) - w + 1):
        window = hashes[start : start + w]
        # Rightmost minimum: guarantees the gap property of winnowing.
        best_index = start + max(
            i for i, item in enumerate(window) if item[0] == min(x[0] for x in window)
        )
        if best_index != last_index:
            selected.append(hashes[best_index])
            last_index = best_index
    return selected


def detect_clones(
    files: list[tuple[str, str]],
    k: int = _DEFAULT_K,
    w: int = _DEFAULT_W,
) -> list[CloneMatch]:
    """Detect cross-file clones among a set of sources.

    Args:
        files: Tuples of ``(path, source)``.
        k: K-gram length in tokens.
        w: Winnowing window size.

    Returns:
        Clone matches, one per file pair, capped at ``_MAX_PAIRS`` entries.
    """
    fingerprint_index: dict[str, list[tuple[str, int]]] = {}
    for path, source in files:
        tokens = tokenize(source)
        for fingerprint, line in _winnow(_kgram_hashes(tokens, k), w):
            fingerprint_index.setdefault(fingerprint, []).append((path, line))

    matches: list[CloneMatch] = []
    seen: set[tuple[str, int, str, int]] = set()
    for fingerprint, locations in fingerprint_index.items():
        if len(locations) < _MIN_CLONE_SITES:
            continue
        for i, (path_a, line_a) in enumerate(locations):
            for path_b, line_b in locations[i + 1 :]:
                if path_a == path_b and line_a == line_b:
                    continue
                pair = (path_a, line_a, path_b, line_b)
                mirror = (path_b, line_b, path_a, line_a)
                if pair in seen or mirror in seen:
                    continue
                seen.add(pair)
                matches.append(
                    CloneMatch(
                        path_a=path_a,
                        line_a=line_a,
                        path_b=path_b,
                        line_b=line_b,
                        fingerprint=fingerprint,
                        token_count=k,
                    )
                )

    # One duplicated region yields several shared fingerprints (winnowing picks
    # one per window), so collapse to the earliest anchor per file pair.
    # ponytail: file-pair granularity; a second, separate duplicated region in
    # the same file pair is under-reported. Revisit if that case matters.
    earliest: dict[frozenset[str], CloneMatch] = {}
    for match in matches:
        key = frozenset((match.path_a, match.path_b))
        current = earliest.get(key)
        if current is None or (match.line_a, match.line_b) < (current.line_a, current.line_b):
            earliest[key] = match
    ordered = sorted(earliest.values(), key=lambda m: (m.path_a, m.line_a))
    return ordered[:_MAX_PAIRS]
