"""Unit tests for the --fix bridge (mirrors core/fixer.py)."""

from __future__ import annotations

from lang_fossil.core.fixer import FixCommand, build_fix_plan, unbridged_languages
from lang_fossil.core.models import Fossil


def _fossil(rule: str, path: str, hint: str | None = None) -> Fossil:
    """Build a synthetic fossil."""
    return Fossil(
        rule_id=rule,
        path=path,
        line=1,
        column=0,
        message="m",
        era="paleozoic",
        provenance="test",
        fix_hint=hint,
    )


def test_only_fix_hinted_fossils_bridge() -> None:
    """Fossils without fix_hint never generate commands."""
    plan = build_fix_plan([_fossil("PF001", "a.py")])
    assert plan == []


def test_python_bridge_uses_pyupgrade() -> None:
    """Python fossils bridge to pyupgrade --py3-plus."""
    plan = build_fix_plan([_fossil("PF004", "old.py", "pyupgrade --py3-plus")])
    assert len(plan) == 1
    command = plan[0]
    assert command.tool == "pyupgrade"
    assert command.args == ("--py3-plus",)
    assert command.paths == ("old.py",)
    assert "pyupgrade --py3-plus old.py" in command.command_line


def test_js_bridge_uses_eslint() -> None:
    """JS fossils bridge to eslint --fix."""
    plan = build_fix_plan([_fossil("JS002", "app.js", "eslint --fix")])
    assert plan[0].tool == "eslint"
    assert plan[0].args == ("--fix",)


def test_unknown_language_skipped() -> None:
    """Files with unknown extensions are not bridged."""
    plan = build_fix_plan([_fossil("PF004", "Makefile", "pyupgrade")])
    assert plan == []


def test_grouping_by_file_and_rule() -> None:
    """Two fixable fossils in different files produce two commands."""
    plan = build_fix_plan(
        [
            _fossil("PF004", "a.py", "x"),
            _fossil("PF004", "b.py", "x"),
        ]
    )
    assert [c.paths for c in plan] == [("a.py",), ("b.py",)]


def test_fix_command_line() -> None:
    """The rendered command line joins tool, args and paths."""
    command = FixCommand("pyupgrade", ("--py3-plus",), ("a.py",), ("PF004",))
    assert command.command_line == "pyupgrade --py3-plus a.py"


def test_dash_prefixed_path_gets_separator() -> None:
    """A path starting with '-' is guarded with the end-of-options separator."""
    normal = FixCommand("pyupgrade", ("--py3-plus",), ("old.py",), ("PF004",))
    assert normal.run_args == ("pyupgrade", "--py3-plus", "old.py")
    dashy = FixCommand("pyupgrade", ("--py3-plus",), ("-dash.py",), ("PF004",))
    assert dashy.run_args == ("pyupgrade", "--py3-plus", "--", "-dash.py")
    assert "-- -dash.py" in dashy.command_line


def test_unbridged_languages_reports_hinted_non_bridged() -> None:
    """Hinted fossils in non-bridged languages surface; bridged ones don't."""
    fossils = [
        _fossil("JV004", "a.java", "use interruption"),  # hinted, no bridge
        _fossil("PF004", "b.py", "pyupgrade --py3-plus"),  # bridged
        _fossil("PF001", "c.py"),  # no hint at all
    ]
    assert unbridged_languages(fossils) == ["java"]
    assert unbridged_languages([_fossil("PF004", "b.py", "x")]) == []
