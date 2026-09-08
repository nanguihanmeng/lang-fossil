"""Stratification stage: aggregate fossils into strata and compute metrics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from lang_fossil.core.models import ERA_META, ERA_UNSAFE, ScanResult


def compute_fossil_index(fossils: int, scanned_lines: int) -> float:
    """Compute the Fossil Index: fossils per thousand lines of code.

    Args:
        fossils: Number of fossils collected in a scan.
        scanned_lines: Number of eligible source lines scanned.

    Returns:
        The fossil index; ``0.0`` when ``scanned_lines`` is 0.

    Raises:
        ValueError: If ``scanned_lines`` is negative.
    """
    if scanned_lines < 0:
        raise ValueError("scanned_lines must be non-negative")
    if scanned_lines == 0:
        return 0.0
    return fossils * 1000.0 / scanned_lines


@dataclass(frozen=True)
class EraStratum:
    """One stratigraphic layer: fossils of a single era."""

    era: str
    fossil_count: int
    top_modules: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class StratigraphyReport:
    """Aggregated, report-ready view of a scan."""

    total_fossils: int
    unsafe_count: int
    scanned_files: int
    scanned_lines: int
    skipped_files: int
    fossil_index: float
    eras: tuple[EraStratum, ...]
    by_rule: dict[str, int]
    by_module: dict[str, int]
    by_severity: dict[str, int]
    parse_errors: tuple[str, ...]
    clone_count: int
    # Optional git-enrichment counters (all zero when dating is disabled).
    git_dated_fossils: int = 0
    active_fossils: int = 0


# A fossil whose file was committed within this many years is "active": the
# style-era says old code, git says it is still being maintained -- the era
# vs. git dating drift the enrichment dimension exists to expose.
# ponytail: fixed window; add a config knob if a tunable horizon is ever needed.
_RECENT_LEGACY_WINDOW_YEARS = 2
_NON_LEGACY_ERAS = frozenset({ERA_META, ERA_UNSAFE})


# Chronological ordering for stratum display (oldest first). The python eras
# come first, then per-language generation labels (newest language standards
# last); unknown eras sort near the end alphabetically; "meta" (tool-level
# findings such as unreadable files) is always the final stratum.
_ERA_ORDER = {
    "paleozoic": 0,
    "mesozoic": 1,
    "cenozoic": 2,
    "c90": 10,
    "c99": 11,
    "c11": 12,
    "cpp98": 20,
    "cpp17": 21,
    "cs1": 30,
    "cs8": 31,
    "java-legacy": 40,
    ERA_UNSAFE: 85,  # review findings (never dated); ordered just before meta
    ERA_META: 90,
}
_ERA_UNKNOWN = 80


def _module_of(path: str) -> str:
    """Map a file path to its nearest "module" bucket (top directory).

    Args:
        path: Repository-relative file path.

    Returns:
        The first path segment (or the file name for root-level files).
    """
    parts = path.split("/")
    return parts[0] if len(parts) > 1 else path


def build_report(scan_result: ScanResult) -> StratigraphyReport:
    """Aggregate a scan result into a stratigraphy report.

    Args:
        scan_result: Raw scan outcome.

    Returns:
        The aggregated report with era strata and per-bucket counters.
    """
    fossils = scan_result.fossils
    by_era: dict[str, dict[str, int]] = {}
    by_rule: dict[str, int] = {}
    by_module: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    dated = 0
    active = 0
    cutoff_year = date.today().year - _RECENT_LEGACY_WINDOW_YEARS

    for fossil in fossils:
        if fossil.last_commit_year is not None:
            dated += 1
            if fossil.era not in _NON_LEGACY_ERAS and fossil.last_commit_year >= cutoff_year:
                active += 1
        by_era.setdefault(fossil.era, {}).setdefault(fossil.path, 0)
        by_era[fossil.era][fossil.path] = by_era[fossil.era].get(fossil.path, 0) + 1
        by_rule[fossil.rule_id] = by_rule.get(fossil.rule_id, 0) + 1
        module = _module_of(fossil.path)
        by_module[module] = by_module.get(module, 0) + 1
        by_severity[fossil.severity] = by_severity.get(fossil.severity, 0) + 1

    eras = tuple(
        EraStratum(
            era=era,
            fossil_count=sum(paths.values()),
            top_modules=tuple(sorted(paths.items(), key=lambda item: (-item[1], item[0]))[:5]),
        )
        for era, paths in sorted(
            by_era.items(),
            key=lambda item: (_ERA_ORDER.get(item[0], _ERA_UNKNOWN), item[0]),
        )
    )

    return StratigraphyReport(
        total_fossils=len(fossils),
        unsafe_count=sum(1 for fossil in fossils if fossil.era == "unsafe"),
        scanned_files=scan_result.scanned_files,
        scanned_lines=scan_result.scanned_lines,
        skipped_files=scan_result.skipped_files,
        fossil_index=compute_fossil_index(len(fossils), scan_result.scanned_lines),
        eras=eras,
        by_rule=by_rule,
        by_module=by_module,
        by_severity=by_severity,
        parse_errors=scan_result.parse_errors,
        clone_count=len(scan_result.clones),
        git_dated_fossils=dated,
        active_fossils=active,
    )
