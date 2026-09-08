"""地层聚合阶段：把化石聚合为地层并计算指标."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from lang_fossil.core.models import ERA_META, ERA_UNSAFE, ScanResult


def compute_fossil_index(fossils: int, scanned_lines: int) -> float:
    """计算 Fossil Index：每千行代码的化石数.

    Args:
        fossils: 本次扫描收集的化石数.
        scanned_lines: 扫描的有效源码行数.

    Returns:
        化石指数；``scanned_lines`` 为 0 时返回 0.0.

    Raises:
        ValueError: ``scanned_lines`` 为负.
    """
    if scanned_lines < 0:
        raise ValueError("scanned_lines must be non-negative")
    if scanned_lines == 0:
        return 0.0
    return fossils * 1000.0 / scanned_lines


@dataclass(frozen=True)
class EraStratum:
    """一个地层：单一时代的化石集合."""

    era: str
    fossil_count: int
    top_modules: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class StratigraphyReport:
    """聚合完成、可直接报告的扫描视图."""

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
    # 可选 git 富化计数器（富化关闭时全为 0）.
    git_dated_fossils: int = 0
    active_fossils: int = 0


# 化石所在文件最近 N 年内仍有提交，即"活跃遗留"：风格 era 说是老代码，
# git 说它仍在被维护——这正是富化维度要暴露的年代错位.
# ponytail: 固定窗口；如需可调地平线再加配置项.
_RECENT_LEGACY_WINDOW_YEARS = 2
# 非"遗留"地层：工具级诊断与审查项不参与活性计数.
_NON_LEGACY_ERAS = frozenset({ERA_META, ERA_UNSAFE})


# 地层展示的时间顺序（从老到新）。Python 时代标签在前，随后是各语言
# 代际标签（越新的语言标准越靠后）；未知时代按字母序排在尾部；"meta"
# （工具级发现，如不可读文件）永远是最后一层.
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
    ERA_UNSAFE: 85,  # 审查发现（不断代）；排在 meta 之前
    ERA_META: 90,
}
_ERA_UNKNOWN = 80


def _module_of(path: str) -> str:
    """把文件路径映射到最近的"模块"桶（顶层目录）.

    Args:
        path: 仓库相对文件路径.

    Returns:
        首个路径段；根级文件返回文件名.
    """
    parts = path.split("/")
    return parts[0] if len(parts) > 1 else path


def build_report(scan_result: ScanResult) -> StratigraphyReport:
    """把扫描结果聚合为地层报告.

    Args:
        scan_result: 原始扫描产物.

    Returns:
        带地层层与各维度计数器的聚合报告.
    """
    fossils = scan_result.fossils
    by_era: dict[str, dict[str, int]] = {}
    by_rule: dict[str, int] = {}
    by_module: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    dated = 0
    active = 0
    # 活性判定阈值：当前年 - 窗口年数.
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
        unsafe_count=sum(1 for fossil in fossils if fossil.era == ERA_UNSAFE),
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
