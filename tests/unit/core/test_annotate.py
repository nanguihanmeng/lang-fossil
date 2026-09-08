"""Unit tests for external-finding annotation (mirrors core/annotate.py)."""

from __future__ import annotations

from pathlib import Path

from lang_fossil.core.annotate import Annotator, build_annotator
from lang_fossil.core.engine import Engine
from lang_fossil.importers import ExternalFinding


def _repo_with_app(tmp_path: Path) -> Path:
    """Write a small JS file exercising JS002 (var) and JS003 (document.all)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.js").write_text("var x = 1\ndocument.all\n", encoding="utf-8")
    return repo


def _annotator() -> Annotator:
    """Build the annotator over builtin rules."""
    return build_annotator()


def test_alias_channel_labels_eslint_rule(tmp_path: Path) -> None:
    """An eslint rule declared in provenance is labelled via the alias."""
    repo = _repo_with_app(tmp_path)
    findings = [
        ExternalFinding(
            tool="eslint",
            rule_id="no-var",
            path="app.js",
            line=1,
            column=0,
            severity="warning",
        )
    ]
    item = _annotator().annotate(repo, findings)[0]
    assert item.annotation is not None
    assert item.annotation.rule_id == "JS002"
    assert item.annotation.era == "unsafe"
    assert item.annotation.category == "unsafe"
    assert item.annotation.source == "alias"


def test_position_channel_labels_same_line(tmp_path: Path) -> None:
    """An external rule without an alias is labelled by a same-line fossil."""
    repo = _repo_with_app(tmp_path)
    findings = [
        ExternalFinding(
            tool="eslint",
            rule_id="no-unused-vars",  # no builtin alias
            path="app.js",
            line=2,  # document.all sits on this line -> JS003
            column=4,
        )
    ]
    item = _annotator().annotate(repo, findings)[0]
    assert item.annotation is not None
    assert item.annotation.rule_id == "JS003"
    assert item.annotation.era == "unsafe"
    assert item.annotation.source == "position"


def test_unannotated_when_no_signal(tmp_path: Path) -> None:
    """Findings with no alias and no same-line fossil stay unannotated."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "clean.js").write_text("const a = 1\n", encoding="utf-8")
    findings = [ExternalFinding(tool="eslint", rule_id="no-unused-vars", path="clean.js", line=1)]
    item = _annotator().annotate(repo, findings)[0]
    assert item.annotation is None


def test_unreadable_file_degrades_to_unannotated(tmp_path: Path) -> None:
    """A missing file yields no label instead of a crash."""
    repo = _repo_with_app(tmp_path)
    findings = [ExternalFinding(tool="eslint", rule_id="no-var", path="missing.js", line=1)]
    # no-var alias resolves regardless of file existence, so use an unaliased
    # rule whose label can only come from the (failing) file scan.
    unaliased = [ExternalFinding(tool="pmd", rule_id="Whatever", path="missing.js", line=1)]
    items = _annotator().annotate(repo, findings + unaliased)
    assert items[0].annotation is not None  # alias is independent of the file
    assert items[1].annotation is None  # missing file -> position channel silent


def test_annotator_injected_registry(tmp_path: Path) -> None:
    """Annotator accepts an explicit registry/engine (dependency injection)."""
    from lang_fossil.core.zombie_api import ZombieApiDB
    from lang_fossil.rules.registry import RuleRegistry

    repo = _repo_with_app(tmp_path)
    registry = RuleRegistry.load_builtin()
    annotator = Annotator(registry, Engine(registry, ZombieApiDB.load()))
    findings = [ExternalFinding(tool="eslint", rule_id="no-var", path="app.js", line=1)]
    item = annotator.annotate(repo, findings)[0]
    assert item.annotation is not None
    assert item.annotation.rule_id == "JS002"


def _repo_with_js_at(tmp_path: Path, name: str) -> Path:
    """Write a JS file that would match JS003 if the position channel read it."""
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    (repo / name).write_text("const a = 1\ndocument.all\n", encoding="utf-8")
    return repo


def test_position_channel_skips_parent_traversal(tmp_path: Path) -> None:
    """A ``../`` path that escapes the root is never read."""
    repo = _repo_with_js_at(tmp_path, "inner.js")
    secret = tmp_path / "secret.js"
    secret.write_text("const a = 1\ndocument.all\n", encoding="utf-8")  # outside root
    findings = [
        ExternalFinding(tool="eslint", rule_id="no-unused-vars", path="../secret.js", line=2)
    ]
    item = build_annotator().annotate(repo, findings)[0]
    assert item.annotation is None  # line 2 would label JS003 if the file were read


def test_position_channel_skips_absolute_paths(tmp_path: Path) -> None:
    """An absolute path outside the root is never read either."""
    repo = _repo_with_js_at(tmp_path, "inner.js")
    secret = tmp_path / "secret2.js"
    secret.write_text("const a = 1\ndocument.all\n", encoding="utf-8")
    findings = [ExternalFinding(tool="eslint", rule_id="no-unused-vars", path=str(secret), line=2)]
    item = build_annotator().annotate(repo, findings)[0]
    assert item.annotation is None


def test_builtin_alias_declarations_reference_supported_tools() -> None:
    """Every provenance alias must point at an importable linter tool.

    Guards the ``ecosystem: <tool> (<rule>)`` protocol from silently drifting:
    an alias for a tool with no importer would never fire (review finding #4).
    """
    from lang_fossil.core.annotate import _extract_aliases
    from lang_fossil.importers import SUPPORTED_TOOLS
    from lang_fossil.rules.registry import RuleRegistry

    registry = RuleRegistry.load_builtin()
    declared: set[tuple[str, str]] = set()
    for rule in registry:
        declared.update(_extract_aliases(rule))
    assert declared  # the protocol must be exercised by builtin rules
    assert all(tool.lower() in SUPPORTED_TOOLS for tool, _rule in declared)
    assert ("eslint", "no-var") in declared  # the canonical example stays alive


def test_alias_matching_is_case_insensitive(tmp_path: Path) -> None:
    """A PMD alias declared with human casing fires for lower-case reports."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "Old.java").write_text("class Old {}\n", encoding="utf-8")
    findings = [ExternalFinding(tool="pmd", rule_id="AvoidFinalizer", path="Old.java", line=1)]
    item = build_annotator().annotate(repo, findings)[0]
    assert item.annotation is not None
    assert item.annotation.rule_id == "JV005"
    assert item.annotation.source == "alias"
