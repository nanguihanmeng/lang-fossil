"""``--fix`` bridge: map fossils to external fixer commands.

lang-fossil does not reimplement codemods: it bridges to established tools
(pyupgrade, eslint --fix) grouped per file, so a single invocation covers
all fixable fossils in that file.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lang_fossil.core.language import sniff_language
from lang_fossil.core.models import Fossil

_PYTHON_TOOL = ("pyupgrade", "--py3-plus")
_JS_TOOL = ("eslint", "--fix")
# Languages without a bridged fixer produce no fix commands; the fossil rule
# simply carries no fix_hint (or a hint with no tool, which is skipped).
_TOOL_BY_LANGUAGE = {
    "python": _PYTHON_TOOL,
    "javascript": _JS_TOOL,
}

# Languages with a bridged fixer (surfaced so the CLI can state the scope).
FIXABLE_LANGUAGES = frozenset(_TOOL_BY_LANGUAGE)


@dataclass(frozen=True)
class FixCommand:
    """One concrete external fixer invocation."""

    tool: str
    args: tuple[str, ...]
    paths: tuple[str, ...]
    rule_ids: tuple[str, ...]

    @property
    def run_args(self) -> tuple[str, ...]:
        """Build the argv for execution.

        Paths that start with ``-`` are guarded with the ``--`` end-of-options
        separator so a file named like a flag can never be parsed as an option
        by the bridged tool (list args already rule out shell injection).

        Returns:
            The full argument vector: tool, tool args, paths.
        """
        separator: tuple[str, ...] = ("--",) if any(p.startswith("-") for p in self.paths) else ()
        return (self.tool, *self.args, *separator, *self.paths)

    @property
    def command_line(self) -> str:
        """Render the full command line for display or execution.

        Returns:
            The command as a shell-agnostic string.
        """
        return " ".join(self.run_args)


def build_fix_plan(fossils: list[Fossil]) -> list[FixCommand]:
    """Group fixable fossils into per-tool, per-file fix commands.

    A fossil is fixable when its rule carries a ``fix_hint``. Files are
    grouped so each tool sees each path once.

    Args:
        fossils: Fossils from a scan.

    Returns:
        Fix commands in deterministic order.
    """
    grouped: dict[tuple[str, tuple[str, ...]], set[str]] = {}
    for fossil in fossils:
        if not fossil.fix_hint:
            continue
        language = sniff_language(Path(fossil.path))
        tool = _TOOL_BY_LANGUAGE.get(language or "")
        if tool is None:
            continue  # no bridged fixer for this language yet
        grouped.setdefault((fossil.path, tool), set()).add(fossil.rule_id)

    commands: list[FixCommand] = []
    for (path, fixer_tool), rule_ids in sorted(grouped.items()):
        commands.append(
            FixCommand(
                tool=fixer_tool[0],
                args=fixer_tool[1:],
                paths=(path,),
                rule_ids=tuple(sorted(rule_ids)),
            )
        )
    return commands


def unbridged_languages(fossils: list[Fossil]) -> list[str]:
    """List languages whose fix hints have no bridged fixer.

    Surfaced by the ``fix`` command so users are never left guessing why
    hinted fossils produced no command.

    Args:
        fossils: Fossils from a scan.

    Returns:
        Sorted language names that carry hints but are not bridged.
    """
    hinted = {sniff_language(Path(fossil.path)) for fossil in fossils if fossil.fix_hint}
    return sorted(lang for lang in hinted if lang and lang not in FIXABLE_LANGUAGES)
