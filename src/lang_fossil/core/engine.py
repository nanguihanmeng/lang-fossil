"""Rule engine: matches validated rules against parsed files.

Matching runs per file on a parso tree (``match_mode: ast``) or on raw
source lines (``match_mode: heuristic``). Parse failures degrade to
line-based rules only; they never abort the scan (PRD "降级而非中断").
"""

from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from typing import Any

from lang_fossil.core.models import ERA_UNSAFE, Fossil, ParseResult
from lang_fossil.core.zombie_api import (
    ZombieApiDB,
    detect_zombie_apis,
    iter_import_modules,
    iter_tree,
)
from lang_fossil.rules.registry import RuleRegistry, RuleSpec

_PREFIX_RE = re.compile(r"^([A-Za-z]*)")
_FLAGS = {"i": re.IGNORECASE, "m": re.MULTILINE, "s": re.DOTALL}


@lru_cache(maxsize=128)  # rules repeat across files; compile once per (target, flags)
def _compile_pattern(target: str, flags: int) -> re.Pattern[str]:
    """Compile a rule regex, cached across files.

    Args:
        target: The regex source.
        flags: Bitwise re flags.

    Returns:
        The compiled pattern.
    """
    return re.compile(target, flags)


def _match_node(rule: RuleSpec, tree: Any) -> list[tuple[int, int]]:
    """Match rules keyed on parso node types (e.g. ``print_stmt``).

    Args:
        rule: The rule being applied.
        tree: parso module node.

    Returns:
        Matching ``(line, column)`` positions.
    """
    return [
        (*node.start_pos,)
        for node in iter_tree(tree)
        if getattr(node, "type", "") == rule.match.target
    ]


def _match_name(rule: RuleSpec, tree: Any, require_dotted: bool) -> list[tuple[int, int]]:
    """Match bare or dotted attribute names against parso leaves.

    Args:
        rule: The rule being applied.
        tree: parso module node.
        require_dotted: When True, the name must follow a ``.`` operator
            (attribute access); when False it must NOT.

    Returns:
        Matching ``(line, column)`` positions.
    """
    hits: list[tuple[int, int]] = []
    for node in iter_tree(tree):
        if getattr(node, "type", "") != "name" or node.value != rule.match.target:
            continue
        previous = node.get_previous_leaf() if hasattr(node, "get_previous_leaf") else None
        is_dotted = previous is not None and previous.type == "operator" and previous.value == "."
        if is_dotted == require_dotted:
            hits.append((*node.start_pos,))
    return hits


def _match_string_prefix(rule: RuleSpec, tree: Any) -> list[tuple[int, int]]:
    """Match string literals with a given prefix (e.g. ``ur``).

    Args:
        rule: The rule being applied.
        tree: parso module node.

    Returns:
        Matching ``(line, column)`` positions.
    """
    hits: list[tuple[int, int]] = []
    wanted = (rule.match.prefix or rule.match.target).lower()
    for node in iter_tree(tree):
        if getattr(node, "type", "") != "string":
            continue
        prefix = _PREFIX_RE.match(node.value)
        if prefix and wanted in prefix.group(1).lower():
            hits.append((*node.start_pos,))
    return hits


def _match_import(rule: RuleSpec, tree: Any) -> list[tuple[int, int]]:
    """Match imports of a module (exact or submodule imports).

    Reuses the shared import walker from :mod:`zombie_api`.

    Args:
        rule: The rule being applied.
        tree: parso module node.

    Returns:
        Matching ``(line, column)`` positions.
    """
    target = rule.match.target
    return [
        (line, column)
        for module, line, column in iter_import_modules(tree)
        if module == target or module.startswith(target + ".")
    ]


def _match_regex(rule: RuleSpec, lines: list[str]) -> list[tuple[int, int]]:
    """Apply a line-based regex rule (heuristic mode).

    Args:
        rule: The rule being applied.
        lines: Source lines.

    Returns:
        Matching ``(line, column)`` positions.
    """
    flags = 0
    for char in rule.match.regex_flags or "":
        flags |= _FLAGS.get(char, 0)
    pattern = _compile_pattern(rule.match.target, flags)
    hits: list[tuple[int, int]] = []
    for index, line in enumerate(lines, start=1):
        match = pattern.search(line)
        if match:
            hits.append((index, match.start()))
    return hits


class Engine:
    """Applies the active rule set (plus zombie detection) to one file."""

    def __init__(
        self,
        registry: RuleRegistry,
        zombie_db: ZombieApiDB | None = None,
    ) -> None:
        """Create an engine.

        Args:
            registry: Validated rule registry.
            zombie_db: Optional zombie API database; when provided, removed
                stdlib API detection runs on every Python file.
        """
        self._registry = registry
        self._zombie_db = zombie_db

    def rules_digest(self) -> str:
        """Return a stable digest of the active rule set (cache key part).

        The zombie snapshot version is folded in so that a dead-packages data
        update invalidates stale cached fossils.

        Returns:
            A short hex digest over rule ids, match specs, and snapshot.
        """
        payload = ";".join(
            f"{rule.id}:{rule.category}:{rule.era}:{rule.match.kind}:{rule.match.target}"
            for rule in self._registry
        )
        if self._zombie_db is not None:
            payload += "|zombie-snapshot:" + self._zombie_db.snapshot_version
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def run(self, path: str, source: str, parse_result: ParseResult) -> list[Fossil]:
        """Run all applicable rules for one parsed file.

        Args:
            path: Repository-relative file path.
            source: Raw source text.
            parse_result: Result from the language parser.

        Returns:
            Fossils found (may be empty).
        """
        fossils: list[Fossil] = []
        lines = source.splitlines()
        tree = parse_result.tree

        for rule in self._registry.for_language(parse_result.language):
            kind = rule.match.kind
            if kind == "regex" or rule.match_mode == "heuristic":
                positions = _match_regex(rule, lines)
            elif tree is None:
                continue  # ast rules need a tree; degrade to nothing
            elif kind == "node":
                positions = _match_node(rule, tree)
            elif kind == "attribute":
                positions = _match_name(rule, tree, require_dotted=True)
            elif kind == "name":
                positions = _match_name(rule, tree, require_dotted=False)
            elif kind == "string_prefix":
                positions = _match_string_prefix(rule, tree)
            elif kind == "import":
                positions = _match_import(rule, tree)
            else:  # pragma: no cover - schema limits kinds
                continue
            fossils.extend(self._to_fossil(rule, path, line, column) for line, column in positions)

        if self._zombie_db is not None and parse_result.language == "python":
            fossils.extend(detect_zombie_apis(path, parse_result, self._zombie_db))
        return fossils

    @staticmethod
    def _to_fossil(rule: RuleSpec, path: str, line: int, column: int) -> Fossil:
        """Convert a rule match into a fossil record.

        Args:
            rule: The matched rule.
            path: File path.
            line: 1-based line number.
            column: 0-based column.

        Returns:
            A frozen fossil.
        """
        return Fossil(
            rule_id=rule.id,
            path=path,
            line=line,
            column=column,
            message=rule.message,
            # Unsafe findings are review items, never age-dated fossils.
            era=ERA_UNSAFE if rule.category == "unsafe" else rule.era,
            provenance=rule.provenance,
            severity=rule.severity,
            fix_hint=rule.fix_hint,
        )
