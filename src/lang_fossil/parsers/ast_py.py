"""基于标准库 ``ast`` 的现代语法快路径.

规则引擎针对 parso 树做匹配（多语法版本主力），因此本模块只用于需要
语义检查现代代码的场景（克隆指纹的名称提取、僵尸 API 的属性遍历），
以及廉价的"是否可按现代语法解析"探测.
"""

from __future__ import annotations

import ast

from lang_fossil.core.models import ParseResult


class AstPythonParser:
    """构建于 :mod:`ast` 之上的现代语法快速解析器."""

    language = "python"

    def parse(self, source: str, *, path: str = "<source>") -> ParseResult:
        """解析现代 Python 源码.

        Args:
            source: 原始源码文本.
            path: 仅用于诊断输出的路径.

        Returns:
            解析结果；出现 :class:`SyntaxError` 时 ``tree`` 为 ``None``，
            错误经 ``errors`` 上报（降级而非抛出）.
        """
        try:
            tree = ast.parse(source, filename=path)
        except (SyntaxError, ValueError) as exc:
            detail = getattr(exc, "msg", str(exc))
            message = f"line {getattr(exc, 'lineno', '?')}: {detail}"
            return ParseResult(
                tree=None,
                errors=(message,),
                language=self.language,
                grammar_version="stdlib",
            )
        except RecursionError:  # pragma: no cover - 防御性兜底
            return ParseResult(
                tree=None,
                errors=("parser failure: recursion limit",),
                language=self.language,
                grammar_version="stdlib",
            )
        return ParseResult(
            tree=tree,
            errors=(),
            language=self.language,
            grammar_version="stdlib",
        )


def walk_names(tree: ast.AST) -> list[tuple[str, int, int]]:
    """收集 AST 中全部标识符.

    Args:
        tree: 已解析的模块节点.

    Returns:
        树中每个 ``Name`` / ``Attribute`` 标识符的
        ``(名称, 行号, 列偏移)`` 元组.
    """
    names: list[tuple[str, int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.append((node.id, node.lineno, node.col_offset))
        elif isinstance(node, ast.Attribute):
            names.append((node.attr, node.lineno, node.col_offset))
    return names
