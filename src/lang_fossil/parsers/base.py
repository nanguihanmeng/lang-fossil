"""所有语言前端共享的解析器协议.

解析器从不因语法错误抛异常：一律降级（PRD"降级而非中断"），问题通过
:attr:`ParseResult.errors` 上报。实现位于 ``parso_py``、``ast_py`` 与
``js_heuristic``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from lang_fossil.core.models import ParseResult


@runtime_checkable
class Parser(Protocol):
    """每个语言前端都需要实现的协议."""

    language: str

    def parse(self, source: str, *, path: str = "<source>") -> ParseResult:
        """把源码解析为 :class:`ParseResult`.

        Args:
            source: 原始源码文本.
            path: 仅用于诊断输出的路径.

        Returns:
            解析结果；整体解析失败时 ``tree`` 为 ``None``.
        """
        ...  # pragma: no cover - 协议占位
