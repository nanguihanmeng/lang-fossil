"""启发式 JavaScript 前端（:class:`HeuristicParser` 的薄封装）.

保留独立类名以维持既有导入路径与 JS 专属文档语义；行为与通用启发式
解析器完全一致.
"""

from __future__ import annotations

from lang_fossil.parsers.heuristic import HeuristicParser


class JsHeuristicParser(HeuristicParser):
    """正则级 JS"解析器"（无 AST）."""

    def __init__(self) -> None:
        """把解析器绑定到 JavaScript 语言."""
        super().__init__("javascript")
