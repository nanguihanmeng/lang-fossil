"""无 AST 语言通用的正则级前端.

JavaScript 与 C/C++/C#/Java 家族只做启发式逐行匹配：不尝试结构性解析.
结果标记 ``heuristic=True``，下游可据此标注置信度（见 ``ParseResult``）.
"""

from __future__ import annotations

from lang_fossil.core.models import ParseResult

_BINARY_SNIFF_LEN = 1024  # 二进制嗅探窗口大小


class HeuristicParser:
    """面向指定语言的启发式"解析器"（无 AST）.

    Args:
        language: 每条解析结果携带的语言标签（如 ``javascript``、
            ``c``、``cpp``、``csharp``、``java``）.
    """

    def __init__(self, language: str) -> None:
        """把解析器绑定到一种语言."""
        self.language = language

    def parse(self, source: str, *, path: str = "<source>") -> ParseResult:
        """把源码当作纯文本行处理；不做结构性解析.

        Args:
            source: 原始源码文本.
            path: 仅用于诊断输出的路径.

        Returns:
            ``tree=None`` 且 ``heuristic=True`` 的解析结果；嗅探窗口内
            出现空字节则视为二进制文件并记录一条错误.
        """
        if "\x00" in source[:_BINARY_SNIFF_LEN]:
            return ParseResult(
                tree=None,
                errors=("binary content skipped",),
                language=self.language,
                grammar_version="n/a",
                heuristic=True,
            )
        return ParseResult(
            tree=None,
            errors=(),
            language=self.language,
            grammar_version="n/a",
            heuristic=True,
        )
