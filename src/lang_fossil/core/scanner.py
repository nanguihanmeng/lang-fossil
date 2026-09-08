"""发现阶段：目录遍历、语言嗅探与扫描编排."""

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

_BINARY_SNIFF_LEN = 1024  # 二进制嗅探窗口大小


def _resolve_header_language(
    relative: str,
    policy: AmbiguousHeaderSettings,
    family_counts: tuple[int, int],
) -> str:
    """按配置（而非内容评分）解析歧义 ``.h``.

    glob overrides 优先；否则由 ``mode`` 决定。``auto`` 模式参考同级目录
    的 C 家族计数（``.cpp`` 源多则判 cpp），无同族默认 ``c``.

    Args:
        relative: 歧义头文件的仓库相对路径（glob 匹配目标）.
        policy: 设置中的歧义头策略.
        family_counts: 同级目录的 ``(c 源数, cpp 源数)``.

    Returns:
        ``"cpp"`` 或 ``"c"``.
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
    """把一个候选文件分类为扫描条目，或返回 ``None`` 跳过.

    语言不支持、二进制文件或被确定性采样丢弃的候选会被跳过；歧义
    头文件按配置策略解析.

    Args:
        path: 候选文件绝对路径.
        base: 用于计算仓库相对路径的根.
        settings: 当前设置.
        family_counts: 供 "auto" 判定用的每目录 C 家族计数.

    Returns:
        文件条目；应跳过时为 ``None``.
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
    """遍历目录树并收集可扫描文件.

    排除目录来自设置；语言不支持或嗅探窗口含空字节的文件跳过。歧义的
    C/C++ 头文件（``.h``）按 ``ambiguous_headers`` 策略解析.

    Args:
        root: 要扫描的目录（或文件）.
        settings: 当前设置（排除项、采样、头文件策略）.

    Returns:
        (条目列表, 跳过数) 元组.
    """
    root = root.resolve()
    base = root.parent if root.is_file() else root
    candidates: list[Path] = [root] if root.is_file() else []
    if root.is_dir():
        # 遍历期剪枝排除目录（避免深入 node_modules 级目录树），
        # 而不是先全列出再丢弃.
        exclude = set(settings.scan.exclude)
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in exclude)
            for name in sorted(filenames):
                path = Path(dirpath) / name
                if name in exclude:  # 例如字面名为 "build" 的文件
                    continue
                candidates.append(path)

    # 每目录 C 家族计数供 "auto" 头文件判定；头文件不计入自身所在目录.
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
    """解析实际 worker 数（0 = min(CPU, 8)）."""
    if settings.scan.workers > 0:
        return settings.scan.workers
    return min(os.cpu_count() or 1, 8)


def scan(
    root: Path,
    settings: LangFossilSettings,
    engine: Engine,
    cache: ScanCache | None = None,
) -> ScanResult:
    """对一个目录运行完整提取管线.

    Args:
        root: 要扫描的目录（或文件）.
        settings: 当前设置.
        engine: 已配置的规则引擎.
        cache: 可选的内容哈希缓存.

    Returns:
        聚合的扫描结果.
    """
    entries, skipped = discover(root, settings)
    root = root.resolve()
    base = root.parent if root.is_file() else root
    digest = engine.rules_digest()
    # Python 有树级前端；其余受支持语言走通用逐行解析器
    # （JS 保留其文档化的子类前端）.
    parsers: dict[str, Callable[[str], ParseResult]] = {
        "python": ParsoPythonParser().parse,
    }
    for language in HEURISTIC_LANGUAGES:
        front = JsHeuristicParser() if language == "javascript" else HeuristicParser(language)
        parsers[language] = front.parse

    def process(
        entry: FileEntry,
    ) -> tuple[list[Fossil], int, str | None, str, tuple[str, ...]]:
        """解析并匹配一个文件，尊重缓存.

        Args:
            entry: 待处理的文件条目.

        Returns:
            (化石列表, 源码行数, 缓存键[禁用时 None], 源码文本, 解析错误).
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
            # 重贴当前文件路径：缓存里的化石属于首次入库的那个文件.
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
        if source and entry.language == "python":  # 克隆指纹仅针对 Python
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
    """把每个文件的最近提交年附加到其化石上（可选择的 git 定年）.

    富化在提取之后每次扫描运行一次（不按 worker 执行）；``settings.git.enabled``
    为 False（默认）时为空转，扫描零开销且与仓库无关。年份与内容无关，
    因此不参与缓存键：缓存命中的化石与新匹配的一视同仁地在此定年.

    Args:
        root: 扫描根目录（git 工作目录探测目标）.
        entries: 已扫描的文件条目（其 ``path`` 是 enricher 返回映射的键）.
        settings: 携带 git 节的当前设置.
        fossils: 本次扫描产出的化石，经替换回填.

    Returns:
        已填 ``last_commit_year`` 的化石；git 定年关闭或无数据时原样返回.
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
    """对 Python 源码运行克隆指纹检测.

    Args:
        entries: 已扫描的文件条目.
        sources: 按相对路径驻留内存的源码.

    Returns:
        跨文件克隆匹配（不足两个文件时为空）.
    """
    if len(sources) < 2:  # noqa: PLR2004 - 克隆按定义需要两个文件
        return []
    from lang_fossil.core.clone import detect_clones

    py_sources = [
        (entry.path, sources[entry.path])
        for entry in entries
        if entry.path in sources and entry.language == "python"
    ]
    return detect_clones(py_sources)


__all__ = ["discover", "scan", "sniff_language"]
