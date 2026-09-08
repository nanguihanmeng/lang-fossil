"""僵尸 API 检测（P0 差异化能力，数据驱动）.

lint 生态只标记"可升级"的对象；本模块标记"已死亡"的对象：彻底从
Python 标准库移除的模块与 API，对照随包分发的 ``dead-packages.json``
离线快照检测（零网络访问）.
"""

from __future__ import annotations

from typing import Any

from lang_fossil.core.models import Fossil, ParseResult
from lang_fossil.infra.offline_db import load_snapshot


def iter_tree(node: Any) -> Any:
    """产出 parso 节点及其全部后代.

    僵尸检测与规则引擎共用（两者都遍历 parso 树）.

    Args:
        node: 根 parso 节点.

    Yields:
        树中每个节点与叶子.
    """
    yield node
    for child in getattr(node, "children", []):
        yield from iter_tree(child)


def _dotted_value(node: Any) -> str:
    """把 dotted_name 节点（或 name 叶）渲染成点分字符串.

    Args:
        node: parso 的 ``dotted_name`` 节点或 ``name`` 叶.

    Returns:
        点分模块名，如 ``distutils.util``.
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
    """从普通 ``import`` 语句节点提取模块名.

    Args:
        node: parso 的 ``import_name`` 节点（children 从关键字之后开始）.

    Returns:
        点分模块名列表（忽略别名）.
    """
    modules: list[str] = []

    def _collect(target: Any) -> None:
        """收集一个导入子句中的模块字符串."""
        children = getattr(target, "children", None)
        if children is None:  # 普通 name 叶
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
                break  # 'as'：别名不是模块

    for child in node.children[1:]:
        if child.type == "operator" and child.value == ",":
            continue
        _collect(child)
    return modules


def _import_from_module(node: Any) -> str | None:
    """从 ``from ... import ...`` 节点提取模块名.

    Args:
        node: parso 的 ``import_from`` 节点.

    Returns:
        点分模块名；相对导入返回 ``None``（根不稳定）.
    """
    parts: list[str] = []
    for child in node.children[1:]:
        if child.type == "keyword":
            break  # 到达 'import'
        if child.type == "operator":
            parts.append(".")  # 相对导入标记
        elif child.type in ("name", "dotted_name"):
            parts.append(_dotted_value(child))
    module = "".join(parts)
    if not module or module.startswith("."):
        return None
    return module


def iter_import_modules(tree: Any) -> list[tuple[str, int, int]]:
    """从 parso 树提取带位置的导入模块名.

    Args:
        tree: parso 模块节点.

    Returns:
        ``(模块名, 行, 列)`` 元组列表（普通与 from 导入；相对导入跳过）.
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


# 一条 dead-package 快照条目（模块级或属性级移除）.
_Entry = dict[str, Any]


class ZombieApiDB:
    """离线移除快照的内存索引."""

    def __init__(self, snapshot: dict[str, Any]) -> None:
        """按模块根与"模块+属性"索引快照条目.

        Args:
            snapshot: 解析后的 ``dead-packages.json`` 文档.

        Raises:
            ValueError: 属性级条目携带点分属性名。属性检测匹配单个
                name 叶，点分属性会静默永不命中，加载即拒绝.
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
        """加载随包分发的离线快照.

        Returns:
            数据库；无快照可用时为空（零条目）.
        """
        return cls(load_snapshot())

    @property
    def entry_count(self) -> int:
        """返回已索引的快照条目数."""
        return len(self._by_module) + len(self._by_attribute)

    def entries_for_module(self, root: str) -> list[_Entry]:
        """返回某模块根下索引的移除条目.

        Args:
            root: 点分模块名的首段.

        Returns:
            匹配的快照条目（可能为空）.
        """
        return self._by_module.get(root, [])

    @property
    def attribute_entries(self) -> dict[tuple[str, str], list[_Entry]]:
        """返回按 ``(模块根, 属性)`` 索引的条目."""
        return self._by_attribute


def _make_fossil(path: str, line: int, column: int, entry: _Entry, version: str) -> Fossil:
    """由快照条目与源码位置构建化石."""
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
    """检测 Python 文件中已移除标准库 API 的使用.

    Args:
        path: 仓库相对路径（用于报告）.
        parse_result: 携带 parso 树的解析结果.
        db: 已加载的僵尸 API 数据库.

    Returns:
        已移除模块导入与已移除属性使用的化石。无树（硬解析失败）的
        文件返回空：检测降级而非中断扫描.
    """
    tree = parse_result.tree
    if tree is None:
        return []

    fossils: list[Fossil] = []
    imports = iter_import_modules(tree)
    imported_roots = {module.split(".")[0] for module, _line, _col in imports}

    # 模块级条目：导入名与移除模块（或其子模块）匹配即命中.
    for module, line, column in imports:
        for entry in db.entries_for_module(module.split(".")[0]):
            if entry["module"] == module or module.startswith(entry["module"] + "."):
                fossils.append(_make_fossil(path, line, column, entry, db.snapshot_version))

    # 属性级条目：匹配 module.attr 链，或模块根已导入时的裸名使用.
    # ponytail: 朴素的 O(names x attribute-entries) 遍历；快照增长远超
    # 当前 ~4 条规模时再按属性名反转索引.
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
