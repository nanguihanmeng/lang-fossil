"""Zombie API detection (P0 differentiator, data-driven).

Lint ecosystems only flag what is *upgradeable*; this module flags what is
already *dead*: standard-library modules and APIs that have been removed
from Python entirely, detected against the offline ``dead-packages.json``
snapshot (no network access).
"""

from __future__ import annotations

from typing import Any

from lang_fossil.core.models import Fossil, ParseResult
from lang_fossil.infra.offline_db import load_snapshot


def iter_tree(node: Any) -> Any:
    """Yield a parso node and all its descendants.

    Shared by zombie detection and the rule engine (both walk parso trees).

    Args:
        node: Root parso node.

    Yields:
        Every node and leaf in the tree.
    """
    yield node
    for child in getattr(node, "children", []):
        yield from iter_tree(child)


def _dotted_value(node: Any) -> str:
    """Render a dotted_name node (or name leaf) to its dotted string.

    Args:
        node: A parso ``dotted_name`` node or ``name`` leaf.

    Returns:
        The dotted module name, e.g. ``distutils.util``.
    """
    value = getattr(node, "value", None)
    if value is not None and not getattr(node, "children", None):
        return str(value)
    parts: list[str] = []
    for child in node.children:
        if child.type == "name":
            parts.append(child.value)
        elif child.type == "dotted_name":
            parts.append(_dotted_value(child))
    return ".".join(parts)


def _import_name_modules(node: Any) -> list[str]:
    """Extract module names from a plain ``import`` statement node.

    Args:
        node: A parso ``import_name`` node (children after the keyword).

    Returns:
        Dotted module names (aliases are ignored).
    """
    modules: list[str] = []

    def _collect(target: Any) -> None:
        """Collect module strings from one import clause."""
        children = getattr(target, "children", None)
        if children is None:  # plain name leaf
            modules.append(target.value)
            return
        for child in children:
            if child.type == "dotted_name":
                modules.append(_dotted_value(child))
            elif child.type == "name":
                modules.append(child.value)
            elif child.type in ("dotted_as_name", "dotted_as_names"):
                _collect(child)
            elif child.type == "keyword":
                break  # 'as': the alias is not a module

    for child in node.children[1:]:
        if child.type == "operator" and child.value == ",":
            continue
        _collect(child)
    return modules


def _import_from_module(node: Any) -> str | None:
    """Extract the module name from a ``from ... import ...`` node.

    Args:
        node: A parso ``import_from`` node.

    Returns:
        The dotted module name, or ``None`` for relative imports.
    """
    parts: list[str] = []
    for child in node.children[1:]:
        if child.type == "keyword":
            break  # reached 'import'
        if child.type == "operator":
            parts.append(".")  # relative import marker
        elif child.type in ("name", "dotted_name"):
            parts.append(_dotted_value(child))
    module = "".join(parts)
    if not module or module.startswith("."):
        return None
    return module


def iter_import_modules(tree: Any) -> list[tuple[str, int, int]]:
    """Extract imported module names with positions from a parso tree.

    Args:
        tree: parso module node.

    Returns:
        Tuples of ``(module_name, line, column)`` for plain and ``from``
        imports (relative imports are skipped; their root is not stable).
    """
    found: list[tuple[str, int, int]] = []
    for node in iter_tree(tree):
        if node.type == "import_name":
            for name in _import_name_modules(node):
                found.append((name, *node.start_pos))
        elif node.type == "import_from":
            module = _import_from_module(node)
            if module:
                found.append((module, *node.start_pos))
    return found


# One dead-package snapshot entry (module-level or attribute-level removal).
_Entry = dict[str, Any]


class ZombieApiDB:
    """In-memory index of the offline removal snapshot."""

    def __init__(self, snapshot: dict[str, Any]) -> None:
        """Index snapshot entries by module root and module+attribute.

        Args:
            snapshot: Parsed ``dead-packages.json`` document.

        Raises:
            ValueError: If an attribute-level entry carries a dotted attribute
                name. Attribute detection matches single name leaves, so a
                dotted attribute would silently never fire; reject it at load.
        """
        self.snapshot_version: str = str(snapshot.get("snapshot_version", "unknown"))
        self._by_module: dict[str, list[_Entry]] = {}
        self._by_attribute: dict[tuple[str, str], list[_Entry]] = {}
        for entry in snapshot.get("packages", []):
            if not isinstance(entry, dict):
                continue
            module = entry.get("module")
            if not isinstance(module, str) or not module:
                continue
            attribute = entry.get("attribute")
            root = module.split(".")[0]
            if isinstance(attribute, str) and attribute:
                if "." in attribute:
                    raise ValueError(
                        f"dotted attribute entries are unsupported: {module}.{attribute}"
                    )
                self._by_attribute.setdefault((root, attribute), []).append(entry)
            else:
                self._by_module.setdefault(root, []).append(entry)

    @classmethod
    def load(cls) -> ZombieApiDB:
        """Load the bundled offline snapshot.

        Returns:
            A database; empty (no entries) when no snapshot is available.
        """
        return cls(load_snapshot())

    @property
    def entry_count(self) -> int:
        """Return the number of indexed snapshot entries."""
        return len(self._by_module) + len(self._by_attribute)

    def entries_for_module(self, root: str) -> list[_Entry]:
        """Return removal entries indexed under a module root.

        Args:
            root: First segment of a dotted module name.

        Returns:
            Matching snapshot entries (possibly empty).
        """
        return self._by_module.get(root, [])

    @property
    def attribute_entries(self) -> dict[tuple[str, str], list[_Entry]]:
        """Return entries keyed by ``(module_root, attribute)``."""
        return self._by_attribute


def _make_fossil(path: str, line: int, column: int, entry: _Entry, version: str) -> Fossil:
    """Build a fossil from a snapshot entry and a source position."""
    module = entry["module"]
    attribute = entry.get("attribute")
    target = f"{module}.{attribute}" if attribute else module
    removed = entry.get("removed_in", "?")
    replacement = entry.get("replacement", "see documentation")
    return Fossil(
        rule_id=f"ZA-{target}",
        path=path,
        line=line,
        column=column,
        message=(
            f"{target} was removed in Python {removed} ({entry.get('removal', 'removed')}); "
            f"use {replacement}"
        ),
        era="cenozoic",
        provenance=f"offline snapshot {version} (dead-packages.json)",
        severity="error",
        fix_hint=replacement,
    )


def detect_zombie_apis(path: str, parse_result: ParseResult, db: ZombieApiDB) -> list[Fossil]:
    """Detect removed standard-library API usage in a parsed Python file.

    Args:
        path: Repository-relative path (for reporting).
        parse_result: Parse result carrying a parso tree.
        db: Loaded zombie API database.

    Returns:
        Fossils for removed-module imports and removed attribute usage.
        Files without a tree (hard parse failure) yield nothing: detection
        degrades instead of interrupting the scan.
    """
    tree = parse_result.tree
    if tree is None:
        return []

    fossils: list[Fossil] = []
    imports = iter_import_modules(tree)
    imported_roots = {module.split(".")[0] for module, _line, _col in imports}

    for module, line, column in imports:
        for entry in db.entries_for_module(module.split(".")[0]):
            if entry["module"] == module or module.startswith(entry["module"] + "."):
                fossils.append(_make_fossil(path, line, column, entry, db.snapshot_version))

    # Attribute-level entries: match module.attr chains, or bare names when
    # the module root is imported in the same file.
    # ponytail: naive O(names x attribute-entries) walk; invert the index on
    # attribute name once the snapshot grows well past its current ~4 entries.
    for node in iter_tree(tree):
        if getattr(node, "type", "") != "name":
            continue
        value = node.value
        for (root, attribute), entries in db.attribute_entries.items():
            if value != attribute:
                continue
            previous = node.get_previous_leaf() if hasattr(node, "get_previous_leaf") else None
            chained = (
                previous is not None
                and getattr(previous, "value", "") == "."
                and previous.get_previous_leaf() is not None
                and previous.get_previous_leaf().value == root
            )
            bare = root in imported_roots and getattr(previous, "value", "") != "."
            if chained or bare:
                line, column = node.start_pos
                for entry in entries:
                    fossils.append(_make_fossil(path, line, column, entry, db.snapshot_version))
    return fossils
