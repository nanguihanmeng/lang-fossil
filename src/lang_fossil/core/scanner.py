"""Discovery stage: directory walk, language sniffing, scan orchestration."""

from __future__ import annotations

import fnmatch
import os
import zlib
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path

from lang_fossil.config import AmbiguousHeaderSettings, LangFossilSettings
from lang_fossil.core.engine import Engine
from lang_fossil.core.enricher import enrich_commit_years
from lang_fossil.core.language import HEADER_AMBIGUOUS, HEURISTIC_LANGUAGES, sniff_language
from lang_fossil.core.models import (
    ERA_META,
    RULE_ID_META,
    CloneMatch,
    FileEntry,
    Fossil,
    ParseResult,
    ScanResult,
)
from lang_fossil.infra.cache import ScanCache
from lang_fossil.parsers.heuristic import HeuristicParser
from lang_fossil.parsers.js_heuristic import JsHeuristicParser
from lang_fossil.parsers.parso_py import ParsoPythonParser

_BINARY_SNIFF_LEN = 1024


def _resolve_header_language(
    relative: str,
    policy: AmbiguousHeaderSettings,
    family_counts: tuple[int, int],
) -> str:
    """Resolve an ambiguous ``.h`` from configuration, not content scoring.

    Glob overrides win; otherwise the ``mode`` decides. In ``auto`` mode the
    sibling directory's C-family tallies decide (more ``.cpp`` sources → cpp),
    defaulting to ``c`` with no C-family siblings.

    Args:
        relative: Repository-relative header path (glob matching target).
        policy: Ambiguous-header policy from settings.
        family_counts: ``(c_sources, cpp_sources)`` counted in the sibling dir.

    Returns:
        ``"cpp"`` or ``"c"``.
    """
    for pattern, language in policy.overrides.items():
        if fnmatch.fnmatchcase(relative, pattern):
            return language
    if policy.mode != "auto":
        return policy.mode
    c_count, cpp_count = family_counts
    return "cpp" if cpp_count > c_count else "c"


def _classify_candidate(
    path: Path,
    base: Path,
    settings: LangFossilSettings,
    family_counts: dict[Path, tuple[int, int]],
) -> FileEntry | None:
    """Classify one candidate file into a scan entry, or ``None`` to skip.

    A candidate is skipped when its language is unsupported, it is binary, or
    deterministic sampling drops it. Ambiguous headers are resolved against
    the configured policy.

    Args:
        path: Absolute candidate path.
        base: Root used to compute the repository-relative entry path.
        settings: Active settings.
        family_counts: Per-directory C-family tallies for "auto" resolution.

    Returns:
        A file entry, or ``None`` when the file should be skipped.
    """
    language = sniff_language(path)
    if language is None:
        return None
    try:
        with path.open("rb") as handle:
            head = handle.read(_BINARY_SNIFF_LEN)
    except OSError:
        return None
    if b"\x00" in head:
        return None
    ratio = settings.scan.sample_ratio
    if ratio < 1.0 and (zlib.crc32(str(path).encode()) % 1000) / 1000 >= ratio:
        return None
    relative = path.relative_to(base).as_posix()
    if language == HEADER_AMBIGUOUS:
        language = _resolve_header_language(
            relative,
            settings.scan.ambiguous_headers,
            family_counts.get(path.parent, (0, 0)),
        )
    return FileEntry(path=relative, language=language)


def discover(root: Path, settings: LangFossilSettings) -> tuple[list[FileEntry], int]:
    """Walk a directory tree and collect scannable files.

    Excluded directories come from settings; files are skipped when their
    language is unsupported or the sniff window contains a null byte.
    Ambiguous C/C++ headers (``.h``) are resolved by the configured
    ``ambiguous_headers`` policy.

    Args:
        root: Directory (or file) to scan.
        settings: Active settings (exclusions, sampling, header policy).

    Returns:
        A tuple of (entries, skipped_count).
    """
    root = root.resolve()
    base = root.parent if root.is_file() else root
    candidates: list[Path] = [root] if root.is_file() else []
    if root.is_dir():
        # Prune excluded directories during the walk (avoids descending into
        # node_modules-sized trees) instead of listing then dropping them.
        exclude = set(settings.scan.exclude)
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in exclude)
            for name in sorted(filenames):
                path = Path(dirpath) / name
                if name in exclude:  # e.g. a file literally named "build"
                    continue
                candidates.append(path)

    # Per-directory C-family tallies feed "auto" header resolution. Headers
    # are excluded from their own directory's tally.
    family_counts: dict[Path, tuple[int, int]] = {}
    for path in candidates:
        suffix = path.suffix.lower()
        if suffix == ".c":
            c_count, cpp_count = family_counts.get(path.parent, (0, 0))
            family_counts[path.parent] = (c_count + 1, cpp_count)
        elif suffix in (".cpp", ".cc", ".cxx"):
            c_count, cpp_count = family_counts.get(path.parent, (0, 0))
            family_counts[path.parent] = (c_count, cpp_count + 1)

    entries: list[FileEntry] = []
    skipped = 0
    for path in candidates:
        entry = _classify_candidate(path, base, settings, family_counts)
        if entry is None:
            skipped += 1
            continue
        entries.append(entry)
    return entries, skipped


def _worker_count(settings: LangFossilSettings) -> int:
    """Resolve the effective worker count (0 = min(CPU, 8))."""
    if settings.scan.workers > 0:
        return settings.scan.workers
    return min(os.cpu_count() or 1, 8)


def scan(
    root: Path,
    settings: LangFossilSettings,
    engine: Engine,
    cache: ScanCache | None = None,
) -> ScanResult:
    """Run the full extraction pipeline over a directory.

    Args:
        root: Directory (or file) to scan.
        settings: Active settings.
        engine: Configured rule engine.
        cache: Optional content-hash cache.

    Returns:
        The aggregated scan result.
    """
    entries, skipped = discover(root, settings)
    root = root.resolve()
    base = root.parent if root.is_file() else root
    digest = engine.rules_digest()
    # Python has a tree front end; every other supported language is served by
    # the generic line parser (JS keeps its documented subclass front end).
    parsers: dict[str, Callable[[str], ParseResult]] = {
        "python": ParsoPythonParser().parse,
    }
    for language in HEURISTIC_LANGUAGES:
        front = JsHeuristicParser() if language == "javascript" else HeuristicParser(language)
        parsers[language] = front.parse

    def process(
        entry: FileEntry,
    ) -> tuple[list[Fossil], int, str | None, str, tuple[str, ...]]:
        """Parse and match one file, honoring the cache.

        Args:
            entry: The file entry to process.

        Returns:
            Fossils, source line count, cache key (None if disabled),
            source text, and parse errors.
        """
        file_path = base / entry.path
        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return (
                [
                    Fossil(
                        rule_id=RULE_ID_META,
                        path=entry.path,
                        line=1,
                        column=0,
                        message=f"unreadable file: {exc}",
                        era=ERA_META,
                        provenance="internal",
                        severity="info",
                    )
                ],
                0,
                None,
                "",
                (),
            )

        key = ScanCache.make_key(source, digest) if cache else None
        cached = cache.get(key) if key and cache else None
        if cached is not None:
            # Re-attach the path of the file we are scanning now: the cached
            # fossils were produced for whatever file first stored this content.
            fossils = [Fossil(**{**item, "path": entry.path}) for item in cached["fossils"]]
            errors = tuple(f"{entry.path}: {e}" for e in cached.get("errors", ()))
            return fossils, len(source.splitlines()), key, source, errors

        parse_result = parsers[entry.language](source)
        fossils = engine.run(entry.path, source, parse_result)
        if key and cache:
            cache.put(
                key,
                [asdict(f) for f in fossils],
                errors=parse_result.errors,
            )
        return (
            fossils,
            len(source.splitlines()),
            key,
            source,
            tuple(f"{entry.path}: {error}" for error in parse_result.errors),
        )

    workers = _worker_count(settings)
    if workers > 1 and len(entries) > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            outcomes = list(pool.map(process, entries))
    else:
        outcomes = [process(entry) for entry in entries]

    all_fossils: list[Fossil] = []
    parse_errors: list[str] = []
    scanned_lines = 0
    sources: dict[str, str] = {}
    for entry, (fossils, n_lines, _key, source, errors) in zip(entries, outcomes):
        all_fossils.extend(fossils)
        scanned_lines += n_lines
        if source and entry.language == "python":  # clone fingerprints run on Python only
            sources[entry.path] = source
        parse_errors.extend(errors)

    clones = _detect_clones_if_possible(entries, sources)
    all_fossils = _date_fossils(root, entries, settings, all_fossils)
    return ScanResult(
        fossils=tuple(all_fossils),
        scanned_files=len(entries),
        scanned_lines=scanned_lines,
        skipped_files=skipped,
        parse_errors=tuple(parse_errors),
        clones=tuple(clones),
    )


def _date_fossils(
    root: Path,
    entries: list[FileEntry],
    settings: LangFossilSettings,
    fossils: list[Fossil],
) -> list[Fossil]:
    """Attach each file's last-commit year to its fossils (opt-in git dating).

    Dating runs once per scan (not per worker) after extraction; it is a no-op
    when ``settings.git.enabled`` is False (the default), so the scan stays
    zero-overhead and repository-agnostic unless explicitly enabled. Years are
    content-independent, therefore never part of the cache key: fossils from a
    cache hit are dated here just like freshly matched ones.

    Args:
        root: Scan root (git working-directory probe target).
        entries: Scanned file entries (their ``path`` values are the lookup
            keys returned by the enricher).
        settings: Active settings carrying the git section.
        fossils: Fossils produced by the scan, mutated via replacement.

    Returns:
        Fossils with ``last_commit_year`` populated, or the input unchanged
        when git dating is disabled or yields no data.
    """
    if not settings.git.enabled or not fossils or not entries:
        return fossils
    years = enrich_commit_years(root, [entry.path for entry in entries], settings)
    if not years:
        return fossils
    return [replace(fossil, last_commit_year=years.get(fossil.path)) for fossil in fossils]


def _detect_clones_if_possible(
    entries: list[FileEntry], sources: dict[str, str]
) -> list[CloneMatch]:
    """Run clone fingerprinting over Python sources.

    Args:
        entries: Scanned file entries.
        sources: In-memory sources keyed by relative path.

    Returns:
        Clone matches across files (empty when fewer than two files).
    """
    if len(sources) < 2:  # noqa: PLR2004 - a clone needs two files by definition
        return []
    from lang_fossil.core.clone import detect_clones

    py_sources = [
        (entry.path, sources[entry.path])
        for entry in entries
        if entry.path in sources and entry.language == "python"
    ]
    return detect_clones(py_sources)


__all__ = ["discover", "scan", "sniff_language"]
