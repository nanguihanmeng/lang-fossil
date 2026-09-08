"""lang-fossil CLI：dig / check / diff / rules / annotate / fix."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from lang_fossil import __version__
from lang_fossil.cli.exit_codes import (
    EXIT_CONFIG,
    EXIT_OK,
    EXIT_THRESHOLD,
    EXIT_USAGE,
)
from lang_fossil.config import ConfigError, LangFossilSettings, load_settings
from lang_fossil.core.annotate import AnnotatedFinding, build_annotator
from lang_fossil.core.engine import Engine
from lang_fossil.core.fixer import FIXABLE_LANGUAGES, build_fix_plan, unbridged_languages
from lang_fossil.core.models import ScanResult
from lang_fossil.core.scanner import scan
from lang_fossil.core.stratigraphy import StratigraphyReport, build_report
from lang_fossil.core.zombie_api import ZombieApiDB
from lang_fossil.importers import SUPPORTED_TOOLS, parse_report
from lang_fossil.infra.cache import ScanCache
from lang_fossil.rules.registry import RuleRegistry

app = typer.Typer(
    name="lang-fossil",
    help="Archaeology for codebases: dig out fossilized legacy APIs.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()
err_console = Console(stderr=True)

# 公共选项定义（避免重复）.
Formats = typer.Option("table", "--format", "-f", help="Output format: table, json, html, sarif.")
OutputOpt = typer.Option(None, "--output", "-o", help="Output file path.")
WorkersOpt = typer.Option(None, "--workers", "-w", min=0, max=16, help="Worker threads (0 = auto).")
NoCacheOpt = typer.Option(False, "--no-cache", help="Disable the content-hash cache.")
NoEmbedOpt = typer.Option(False, "--no-embed", help="HTML shell mode (http preview only).")


def _load_engine() -> Engine:
    """构建默认引擎（内置规则 + 离线僵尸数据库）.

    Returns:
        配置好的引擎.

    Raises:
        ConfigError: 内置规则包或快照非法.
    """
    try:
        registry = RuleRegistry.load_builtin()
        zombie_db = ZombieApiDB.load()
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc
    return Engine(registry, zombie_db)


def _run_scan(
    path: Path,
    workers: int | None,
    no_cache: bool,
) -> tuple[ScanResult, StratigraphyReport, LangFossilSettings]:
    """以"配置 + CLI 覆盖"解析出的设置执行扫描.

    Args:
        path: 扫描根.
        workers: CLI worker 覆盖（None = 遵循配置）.
        no_cache: 本次运行禁用缓存.

    Returns:
        (扫描结果, 地层报告, 当前设置) 三元组。返回设置是为了让调用方
        在输出中体现可选功能（如 git 富化）.

    Raises:
        ConfigError: 配置非法.
    """
    overrides: dict[str, Any] = {}
    if workers is not None:
        overrides["scan"] = {"workers": workers}
    settings = load_settings(overrides)
    if no_cache:
        settings.cache.enabled = False

    cache = (
        ScanCache(Path(settings.cache.path), enabled=settings.cache.enabled)
        if settings.cache.enabled
        else None
    )
    try:
        engine = _load_engine()
        result = scan(path, settings, engine, cache)
    finally:
        if cache is not None:
            cache.close()
    return result, build_report(result), settings


def _print_table(report: StratigraphyReport, git_enabled: bool = False) -> None:
    """渲染人类可读的地层表.

    Args:
        report: 聚合的地层报告.
        git_enabled: 本次扫描是否开启 git 富化；开启时追加活性
            （最近被维护的）遗留计数.
    """
    table = Table(title="lang-fossil stratigraphy")
    table.add_column("Era")
    table.add_column("Fossils", justify="right")
    table.add_column("Top modules")
    for era in report.eras:
        modules = ", ".join(f"{name} ({count})" for name, count in era.top_modules)
        table.add_row(era.era, str(era.fossil_count), modules)
    console.print(table)
    summary = (
        f"fossil index: {report.fossil_index:.2f}/kLOC, "
        f"files: {report.scanned_files}, "
        f"fossils: {report.total_fossils}, "
        f"unsafe: {report.unsafe_count}, "
        f"clones: {report.clone_count}, "
        f"parse errors: {len(report.parse_errors)}"
    )
    if git_enabled:
        summary += f", active legacy fossils: {report.active_fossils}"
    console.print(summary)


@app.command()
def dig(
    path: Path = typer.Argument(..., exists=True, help="Directory or file to scan."),
    fmt: str = Formats,
    output: Path | None = OutputOpt,
    workers: int | None = WorkersOpt,
    no_cache: bool = NoCacheOpt,
    no_embed: bool = NoEmbedOpt,
) -> None:
    """扫描仓库并报告其化石记录.

    Args:
        path: 目录或文件.
        fmt: 报告格式（table, json, html, sarif）.
        output: 输出文件（json 默认 stdout；table 始终打印）.
        workers: worker 覆盖.
        no_cache: 禁用缓存.
        no_embed: HTML 外壳模式.

    Raises:
        typer.Exit: 配置错误（退出码 2）.
    """
    try:
        result, report, settings = _run_scan(path, workers, no_cache)
    except ConfigError as exc:
        err_console.print(f"[red]config error:[/red] {exc}")
        raise typer.Exit(EXIT_CONFIG) from exc

    _print_table(report, git_enabled=settings.git.enabled)
    if output is None and fmt == "table":
        return
    out = output or Path(f"lang-fossil-report.{fmt}")
    root = path.resolve()
    if fmt == "json":
        from lang_fossil.reporting import json_report

        json_report.write_report(result, report, root, out)
    elif fmt == "html":
        from lang_fossil.reporting import html_report

        html_report.write_report(result, report, root, out, embed_data=not no_embed)
    elif fmt == "sarif":
        from lang_fossil.reporting import sarif_report

        sarif_report.write_report(result, report, root, out)
    else:
        err_console.print(f"[red]unknown format:[/red] {fmt}")
        raise typer.Exit(EXIT_USAGE)
    console.print(f"report written: {out}")


@app.command()
def check(
    path: Path = typer.Argument(..., exists=True, help="Directory or file to scan."),
    max_fi: float | None = typer.Option(
        None, "--max-fi", min=0.0, help="Maximum allowed fossil index (CI gate)."
    ),
    max_fossils: int | None = typer.Option(
        None, "--max-fossils", min=0, help="Maximum allowed fossil count."
    ),
    no_cache: bool = NoCacheOpt,
) -> None:
    """CI 门禁：超出化石预算时以退出码 1 失败.

    Args:
        path: 目录或文件.
        max_fi: 化石指数阈值（每 kLOC）.
        max_fossils: 化石总数阈值.
        no_cache: 禁用缓存.

    Raises:
        typer.Exit: 0（通过）、1（超阈值）或 2（配置错误）.
    """
    try:
        _result, report, _settings = _run_scan(path, None, no_cache)
    except ConfigError as exc:
        err_console.print(f"[red]config error:[/red] {exc}")
        raise typer.Exit(EXIT_CONFIG) from exc

    exceeded = False
    if max_fi is not None and report.fossil_index > max_fi:
        err_console.print(f"[red]fossil index {report.fossil_index:.2f} exceeds --max-fi {max_fi}")
        exceeded = True
    if max_fossils is not None and report.total_fossils > max_fossils:
        err_console.print(f"[red]{report.total_fossils} fossils exceed --max-fossils {max_fossils}")
        exceeded = True
    raise typer.Exit(EXIT_THRESHOLD if exceeded else EXIT_OK)


@app.command()
def diff(
    old: Path = typer.Argument(..., exists=True, help="Baseline JSON report."),
    new: Path = typer.Argument(..., exists=True, help="Current JSON report."),
) -> None:
    """对比两份 JSON 报告：新增与已解决的化石.

    Args:
        old: 基线报告.
        new: 当前报告.

    Raises:
        typer.Exit: 报告畸形（退出码 2）.
    """
    try:
        old_doc: dict[str, Any] = json.loads(old.read_text(encoding="utf-8"))
        new_doc: dict[str, Any] = json.loads(new.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        err_console.print(f"[red]cannot read reports:[/red] {exc}")
        raise typer.Exit(EXIT_CONFIG) from exc

    def _keys(doc: dict[str, Any]) -> Counter[tuple[str, str, int]]:
        """按 (规则, 路径, 行) 为化石计数；畸形记录跳过."""

        def _item(item: Any) -> tuple[str, str, int] | None:
            if not isinstance(item, dict):
                return None
            rule_id, path, line = item.get("rule_id"), item.get("path"), item.get("line")
            if (
                not isinstance(rule_id, str)
                or not isinstance(path, str)
                or not isinstance(line, int)
            ):
                return None
            return (rule_id, path, line)

        items: list[tuple[str, str, int]] = []
        for fossil in doc.get("fossils", []):
            key = _item(fossil)
            if key is not None:
                items.append(key)
        return Counter(items)

    old_keys, new_keys = _keys(old_doc), _keys(new_doc)
    introduced = new_keys - old_keys
    resolved = old_keys - new_keys

    table = Table(title="fossil diff")
    table.add_column("Change")
    table.add_column("Rule")
    table.add_column("Where")
    for rule, path, line in sorted(introduced.elements()):
        table.add_row("[red]new[/red]", rule, f"{path}:{line}")
    for rule, path, line in sorted(resolved.elements()):
        table.add_row("[green]resolved[/green]", rule, f"{path}:{line}")
    console.print(table)
    console.print(f"introduced: {sum(introduced.values())}, resolved: {sum(resolved.values())}")


@app.command()
def rules() -> None:
    """列出内置规则及其来源."""
    registry = RuleRegistry.load_builtin()
    table = Table(title=f"builtin rules ({len(registry)})")
    table.add_column("ID")
    table.add_column("Lang")
    table.add_column("Category")
    table.add_column("Era")
    table.add_column("Dep./Removed")
    table.add_column("Mode")
    table.add_column("Provenance")
    table.add_column("Message")
    for rule in registry:
        version = rule.removed_in or rule.deprecated_in or "-"
        table.add_row(
            rule.id,
            rule.language,
            rule.category,
            rule.era,
            version,
            rule.match_mode,
            rule.provenance,
            rule.message,
        )
    console.print(table)


def _write_annotation_json(
    root: Path,
    tool: str,
    annotated: list[AnnotatedFinding],
    output: Path,
) -> None:
    """把标注报告写为规范的 JSON 文档.

    Args:
        root: 扫描根目录（写入 provenance）.
        tool: 来源 linter 工具.
        annotated: 已标注的 finding.
        output: 输出文件路径.
    """
    by_era: Counter[str] = Counter()
    by_category: Counter[str] = Counter()
    labeled = 0
    for item in annotated:
        if item.annotation is None:
            continue
        labeled += 1
        by_era[item.annotation.era] += 1
        by_category[item.annotation.category] += 1
    records = []
    for item in annotated:
        finding = item.finding
        annotation = item.annotation
        records.append(
            {
                "tool": finding.tool,
                "rule_id": finding.rule_id,
                "path": finding.path,
                "line": finding.line,
                "column": finding.column,
                "severity": finding.severity,
                "message": finding.message,
                "label": (
                    None
                    if annotation is None
                    else {
                        "era": annotation.era,
                        "category": annotation.category,
                        "rule_id": annotation.rule_id,
                        "provenance": annotation.provenance,
                        "source": annotation.source,
                    }
                ),
            }
        )
    document = {
        "tool": {"name": "lang-fossil", "version": __version__},
        "root": str(root),
        "linter": tool,
        "summary": {
            "total": len(annotated),
            "annotated": labeled,
            "unannotated": len(annotated) - labeled,
            "by_era": dict(sorted(by_era.items())),
            "by_category": dict(sorted(by_category.items())),
        },
        "annotations": records,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")


def _print_annotation_table(annotated: list[AnnotatedFinding]) -> None:
    """把标注 finding 渲染为人类可读的表格.

    Args:
        annotated: 已标注的 finding.
    """
    table = Table(title="external findings with archaeology labels")
    table.add_column("Tool")
    table.add_column("Rule")
    table.add_column("Where")
    table.add_column("Era")
    table.add_column("Category")
    table.add_column("Label source")
    for item in annotated:
        finding = item.finding
        annotation = item.annotation
        table.add_row(
            finding.tool,
            finding.rule_id,
            f"{finding.path}:{finding.line}",
            annotation.era if annotation else "-",
            annotation.category if annotation else "unannotated",
            annotation.source if annotation else "-",
        )
    console.print(table)
    labeled = sum(1 for item in annotated if item.annotation is not None)
    console.print(f"annotated: {labeled}, unannotated: {len(annotated) - labeled}")


@app.command()
def annotate(
    root: Path = typer.Argument(..., exists=True, help="Repository root directory."),
    report: Path = typer.Argument(..., exists=True, help="External linter report file."),
    tool: str = typer.Option(
        ...,
        "--tool",
        "-t",
        help=f"Report format: {', '.join(SUPPORTED_TOOLS)}.",
    ),
    fmt: str = typer.Option("table", "--format", "-f", help="Output format: table, json."),
    output: Path | None = OutputOpt,
) -> None:
    """为外部 linter 报告附加 era/category 考古标签.

    导入 clang-tidy / PMD / eslint 输出，为每条 finding 附上 lang-fossil
    考古元数据（era、category、provenance）。无法断代的 finding 报告为
    ``unannotated``——绝不捏造.

    Args:
        root: 仓库根（报告中的路径相对它解析）.
        report: 待导入的外部 linter 报告.
        tool: 生成 ``report`` 的工具.
        fmt: 输出格式（table, json）.
        output: 输出文件路径（仅 json；table 始终打印）.

    Raises:
        typer.Exit: 工具不支持、报告不可读或内容非法（退出码 2）.
    """
    resolved_root = root.resolve()
    try:
        content = report.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        err_console.print(f"[red]cannot read report:[/red] {exc}")
        raise typer.Exit(EXIT_CONFIG) from exc
    try:
        findings = parse_report(tool, content, resolved_root)
        annotated = build_annotator().annotate(resolved_root, findings)
    except ValueError as exc:
        err_console.print(f"[red]annotate error:[/red] {exc}")
        raise typer.Exit(EXIT_CONFIG) from exc
    if not annotated:
        console.print("no findings in report")
        return
    _print_annotation_table(annotated)
    if output is None and fmt == "table":
        return
    out = output or Path(f"lang-fossil-annotations.{fmt}")
    if fmt == "json":
        _write_annotation_json(resolved_root, tool, annotated, out)
        console.print(f"report written: {out}")
    else:
        err_console.print(f"[red]unknown format:[/red] {fmt}")
        raise typer.Exit(EXIT_USAGE)


@app.command()
def fix(
    path: Path = typer.Argument(..., exists=True, help="Directory or file to scan."),
    apply: bool = typer.Option(
        False, "--apply", help="Actually run the fixer commands (tools must be installed)."
    ),
) -> None:
    """打印（或运行）可修复化石对应的外部修复器命令.

    Args:
        path: 目录或文件.
        apply: 执行命令而非打印（需已安装工具）.
    """
    try:
        result, _report, _settings = _run_scan(path, None, False)
    except ConfigError as exc:
        err_console.print(f"[red]config error:[/red] {exc}")
        raise typer.Exit(EXIT_CONFIG) from exc
    commands = build_fix_plan(list(result.fossils))
    unbridged = unbridged_languages(list(result.fossils))
    if unbridged:
        console.print(
            f"note: no fixer bridge for: {', '.join(unbridged)} "
            f"(bridged: {', '.join(sorted(FIXABLE_LANGUAGES))}); "
            "apply their fix_hint values manually"
        )
    if not commands:
        console.print("no fixable fossils found")
        return
    for command in commands:
        console.print(f"$ {command.command_line}  # rules: {', '.join(command.rule_ids)}")
    if apply:
        import subprocess

        for command in commands:
            subprocess.run(list(command.run_args), check=False)  # noqa: S603
    else:
        console.print("dry run: pass --apply to execute (requires the tools)")


def _version_callback(value: bool) -> None:
    """传入 ``--version`` 时立即打印版本并退出."""
    if value:
        console.print(f"lang-fossil {__version__}")
        raise typer.Exit(EXIT_OK)


@app.callback()
def main_callback(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show version.",
    ),
) -> None:
    """lang-fossil：代码考古学."""


def main() -> None:
    """console-script 入口."""
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
