"""规则引擎：把校验过的规则匹配到已解析文件.

匹配按文件进行：``match_mode: ast`` 走 parso 树，``match_mode: heuristic``
走源码行。解析失败只降级为行级规则，绝不中断扫描（PRD"降级而非中断"）.
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


@lru_cache(maxsize=128)  # 规则跨文件重复；(target, flags) 编译一次
def _compile_pattern(target: str, flags: int) -> re.Pattern[str]:
    """编译规则正则，跨文件缓存.

    Args:
        target: 正则原文.
        flags: 位组合的 re 标志.

    Returns:
        编译后的 pattern.
    """
    return re.compile(target, flags)


def _match_node(rule: RuleSpec, tree: Any) -> list[tuple[int, int]]:
    """按 parso 节点类型匹配规则（如 ``print_stmt``）.

    Args:
        rule: 当前规则.
        tree: parso 模块节点.

    Returns:
        命中的 ``(line, column)`` 位置列表.
    """
    return [
        (*node.start_pos,)
        for node in iter_tree(tree)
        if getattr(node, "type", "") == rule.match.target
    ]


def _match_name(rule: RuleSpec, tree: Any, require_dotted: bool) -> list[tuple[int, int]]:
    """对 parso 叶子匹配裸名或点分属性名.

    Args:
        rule: 当前规则.
        tree: parso 模块节点.
        require_dotted: True 时名称必须紧跟 ``.``（属性访问）；False 时
            必须不是.

    Returns:
        命中的 ``(line, column)`` 位置列表.
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
    """匹配带指定前缀的字符串字面量（如 ``ur``）.

    Args:
        rule: 当前规则.
        tree: parso 模块节点.

    Returns:
        命中的 ``(line, column)`` 位置列表.
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
    """匹配模块导入（精确或子模块匹配）.

    复用 :mod:`zombie_api` 的共享导入遍历器.

    Args:
        rule: 当前规则.
        tree: parso 模块节点.

    Returns:
        命中的 ``(line, column)`` 位置列表.
    """
    target = rule.match.target
    return [
        (line, column)
        for module, line, column in iter_import_modules(tree)
        if module == target or module.startswith(target + ".")
    ]


def _match_regex(rule: RuleSpec, lines: list[str]) -> list[tuple[int, int]]:
    """应用逐行正则规则（启发式模式）.

    Args:
        rule: 当前规则.
        lines: 源码行列表.

    Returns:
        命中的 ``(line, column)`` 位置列表.
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
    """把生效规则集（及僵尸检测）应用于单个文件."""

    def __init__(
        self,
        registry: RuleRegistry,
        zombie_db: ZombieApiDB | None = None,
    ) -> None:
        """创建引擎.

        Args:
            registry: 已校验的规则注册表.
            zombie_db: 可选的僵尸 API 数据库；提供时每个 Python 文件都
                会执行已移除标准库 API 检测.
        """
        self._registry = registry
        self._zombie_db = zombie_db

    def rules_digest(self) -> str:
        """返回生效规则集的稳定摘要（缓存键的组成部分）.

        僵尸快照版本一并折入：dead-packages 数据更新即令旧缓存失效.

        Returns:
            覆盖规则 id、匹配规格与快照版本的短十六进制摘要.
        """
        payload = ";".join(
            f"{rule.id}:{rule.category}:{rule.era}:{rule.match.kind}:{rule.match.target}"
            for rule in self._registry
        )
        if self._zombie_db is not None:
            payload += "|zombie-snapshot:" + self._zombie_db.snapshot_version
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def run(self, path: str, source: str, parse_result: ParseResult) -> list[Fossil]:
        """对单个已解析文件运行全部适用规则.

        Args:
            path: 仓库相对文件路径.
            source: 原始源码文本.
            parse_result: 语言解析器的结果.

        Returns:
        化石列表（可能为空）.
        """
        fossils: list[Fossil] = []
        lines = source.splitlines()
        tree = parse_result.tree

        for rule in self._registry.for_language(parse_result.language):
            kind = rule.match.kind
            if kind == "regex" or rule.match_mode == "heuristic":
                positions = _match_regex(rule, lines)
            elif tree is None:
                continue  # ast 规则没有树：降级为不命中
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
            else:  # pragma: no cover - schema 限制了 kind 集合
                continue
            fossils.extend(self._to_fossil(rule, path, line, column) for line, column in positions)

        if self._zombie_db is not None and parse_result.language == "python":
            fossils.extend(detect_zombie_apis(path, parse_result, self._zombie_db))
        return fossils

    @staticmethod
    def _to_fossil(rule: RuleSpec, path: str, line: int, column: int) -> Fossil:
        """把规则命中转换为化石记录.

        Args:
            rule: 命中的规则.
            path: 文件路径.
            line: 1 起始行号.
            column: 0 起始列号.

        Returns:
            冻结的化石对象.
        """
        return Fossil(
            rule_id=rule.id,
            path=path,
            line=line,
            column=column,
            message=rule.message,
            # unsafe 发现是审查项，绝不冒充可断代的化石.
            era=ERA_UNSAFE if rule.category == "unsafe" else rule.era,
            provenance=rule.provenance,
            severity=rule.severity,
            fix_hint=rule.fix_hint,
        )
