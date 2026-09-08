"""lang-fossil CLI: dig / check / diff / rules / annotate / fix."""

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

Formats = typer.Option("table", "--format", "-f", help="Output format: table, json, html, sarif.")
OutputOpt = typer.Option(None, "--output", "-o", help="Output file path.")
WorkersOpt = typer.Option(None, "--workers", "-w", min=0, max=16, help="Worker threads (0 = auto).")
NoCacheOpt = typer.Option(False, "--no-cache", help="Disable the content-hash cache.")
NoEmbedOpt = typer.Option(False, "--no-embed", help="HTML shell mode (http preview only).")


def _load_engine() -> Engine:
    """Build the default engine (builtin rules + offline zombie DB).

    Returns:
        A configured engine.

    Raises:
        ConfigError: If builtin rule packs or the snapshot are invalid.
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
    """Execute a scan with settings resolved from config + CLI overrides.

    Args:
        path: Scan root.
        workers: CLI worker override (None = defer to config).
        no_cache: Disable caching for this run.

    Returns:
        Tuple of (scan result, stratigraphy report, active settings).
        The settings are returned so callers can reflect opt-in features
        (e.g. git enrichment) in their output.

    Raises:
        ConfigError: On invalid configuration.
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
    """Render a human-readable stratigraphy table.

    Args:
        report: Aggregated stratigraphy report.
        git_enabled: Whether git enrichment was on for this scan; when on,
            the recently-touched (active) legacy count is appended.
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
    """Scan a repository and report its fossil record.

    Args:
        path: Directory or file to scan.
        fmt: Report format (table, json, html, sarif).
        output: Output file (defaults to stdout for json, table always prints).
        workers: Worker override.
        no_cache: Disable cache.
        no_embed: HTML shell mode.

    Raises:
        typer.Exit: On config errors (exit code 2).
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
    """CI gate: exit 1 when the fossil budget is exceeded.

    Args:
        path: Directory or file to scan.
        max_fi: Fossil-index threshold (per kLOC).
        max_fossils: Absolute fossil count threshold.
        no_cache: Disable cache.

    Raises:
        typer.Exit: 0 (pass), 1 (threshold exceeded), or 2 (config error).
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
    """Compare two JSON reports: new and resolved fossils.

    Args:
        old: Baseline report.
        new: Current report.

    Raises:
        typer.Exit: On malformed reports (exit code 2).
    """
    try:
        old_doc: dict[str, Any] = json.loads(old.read_text(encoding="utf-8"))
        new_doc: dict[str, Any] = json.loads(new.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        err_console.print(f"[red]cannot read reports:[/red] {exc}")
        raise typer.Exit(EXIT_CONFIG) from exc

    def _keys(doc: dict[str, Any]) -> Counter[tuple[str, str, int]]:
        """Key fossils by (rule, path, line); malformed records are skipped."""

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
    """List builtin rules with their provenance."""
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
    """Write the annotation report as the canonical JSON document.

    Args:
        root: Scan root directory (echoed for provenance).
        tool: Source linter tool.
        annotated: Labeled findings.
        output: Output file path.
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
    """Render the annotated findings as a human-readable table.

    Args:
        annotated: Labeled findings.
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
    """Attach era/category archaeology labels to an external linter report.

    Imports clang-tidy / PMD / eslint output and labels every finding with
    lang-fossil archaeology metadata (era, category, provenance). Findings
    that cannot be dated are reported as ``unannotated`` -- never invented.

    Args:
        root: Repository root (paths in the report are resolved against it).
        report: External linter report to import.
        tool: Which tool produced ``report``.
        fmt: Report format (table, json).
        output: Output file path (json only; table always prints).

    Raises:
        typer.Exit: On an unsupported tool, unreadable report, or invalid
            content (exit code 2).
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
    """Print (or run) external fixer commands for fixable fossils.

    Args:
        path: Directory or file to scan.
        apply: Execute the commands instead of printing them.
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
    """Eagerly print the version and exit when ``--version`` is passed."""
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
    """lang-fossil: archaeology for codebases."""


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
