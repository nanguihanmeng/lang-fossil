"""基于 parso 的多语法版本 Python 前端.

parso ≥ 0.8.2 已从发行包移除历史 Python 2 语法文件，因此 Python 2.7
语法随包 vendor（``grammars/grammar27.txt``，取自 parso v0.7.1，MIT
许可），经 ``parso.load_grammar(path=...)`` 加载。以此兑现规范承诺：
Py2 语料在 Py3 解释器上可解析（规范附录 C，M0 PoC）.

策略：先用解释器自带语法解析；若报语法错误且源码嗅探为 Python 2，
改用 vendored 2.7 语法重试并保留错误更少的结果。早于 2.7 的源码超出
parso 支持范围，落入正则启发式规则（``match_mode: heuristic``）.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import parso

from lang_fossil.core.models import ParseResult

_PY2_VERSION = "2.7"
_PY2_GRAMMAR_PATH = Path(__file__).parent / "grammars" / "grammar27.txt"
_MIN_GRAMMAR_DIGITS = 2  # 语法文件名至少 2 位数字（"39"、"310"）

# 仅 Python 3 之前存在的构造；用于判断是否值得尝试 2.7 语法重试.
_PY2_HINTS = re.compile(
    r"^\s*print\s+[^(=]|"  # print 语句
    r"raise\s+\w+\s*,\s*|"  # raise E, msg
    r"^\s*exec\s+[^\s(]|"  # exec 语句
    r"[\s(]<{2}\s*\d|"  # print >> stream
    r"=\s*[uU][rR][\"']|"  # ur'' 字符串字面量
    r"[\w)\]]`|`[\w(]",  # 反引号 repr
    re.MULTILINE,
)


def _load_py2_grammar() -> Any:
    """加载 vendored 的 Python 2.7 语法.

    Returns:
        parso 语法对象；vendored 文件缺失时为 ``None``.
    """
    try:
        return parso.load_grammar(path=str(_PY2_GRAMMAR_PATH))
    except (OSError, ValueError):
        return None


def _load_default_grammar() -> Any:
    """加载解释器自带语法，失败时回退到最新可用语法.

    Returns:
        parso 语法对象；完全无法加载时为 ``None``.
    """
    try:
        return parso.load_grammar()
    except (OSError, NotImplementedError, ValueError):
        pass
    # 未来解释器可能超出 parso 内置语法范围：选取实际发行的最高语法文件.
    grammar_dir = Path(parso.__file__).parent / "python"
    candidates: list[tuple[int, int, Path]] = []
    for grammar_file in grammar_dir.glob("grammar*.txt"):
        digits = grammar_file.stem[len("grammar") :]
        if digits.isdigit() and len(digits) >= _MIN_GRAMMAR_DIGITS:
            candidates.append((int(digits[0]), int(digits[1:]), grammar_file))
    if not candidates:
        return None
    newest = max(candidates)
    try:
        return parso.load_grammar(path=str(newest[2]))
    except (OSError, ValueError, NotImplementedError):
        return None


class ParsoPythonParser:
    """多语法版本的 Python 解析器（主力前端）."""

    language = "python"

    def parse(self, source: str, *, path: str = "<source>") -> ParseResult:
        """解析 Python 源码，必要时回退 2.7 语法.

        Args:
            source: 原始源码文本.
            path: 仅用于诊断输出的路径.

        Returns:
            语法错误最少的解析结果；实际使用的语法版本记录在结果上.
        """
        modern = self._parse_with_version(source, None)
        modern_errors = list(modern["errors"])
        if not modern_errors or not _PY2_HINTS.search(source):
            return ParseResult(
                tree=modern["tree"],
                errors=tuple(modern_errors),
                language=self.language,
                grammar_version=str(modern["version"]),
            )

        legacy = self._parse_with_version(source, _PY2_VERSION)
        legacy_errors = list(legacy["errors"])
        if legacy["tree"] is not None and len(legacy_errors) < len(modern_errors):
            return ParseResult(
                tree=legacy["tree"],
                errors=tuple(legacy_errors),
                language=self.language,
                grammar_version=str(legacy["version"]),
            )
        return ParseResult(
            tree=modern["tree"],
            errors=tuple(modern_errors),
            language=self.language,
            grammar_version=str(modern["version"]),
        )

    def _parse_with_version(self, source: str, version: str | None) -> dict[str, Any]:
        """用指定语法版本解析并收集错误.

        Args:
            source: 原始源码文本.
            version: 语法版本（``None`` = 当前解释器；``"2.7"`` = vendored
                Py2 语法）.

        Returns:
            含 ``tree``（parso 节点或 ``None``）、``errors``（格式化的
            错误字符串列表）与 ``version``（标签）的字典.
        """
        if version is None:
            grammar = _load_default_grammar()
            label = "3.x"
        else:
            grammar = _load_py2_grammar()
            label = version
        if grammar is None:
            return {"tree": None, "errors": ["grammar unavailable"], "version": label}

        try:
            tree = grammar.parse(source)
        except (RecursionError, ValueError, NotImplementedError) as exc:
            # parso 自身不应抛异常；无论如何防御性降级.
            return {"tree": None, "errors": [f"parser failure: {exc}"], "version": label}

        errors: list[str] = []
        try:
            for error in grammar.iter_errors(tree):
                errors.append(
                    f"line {getattr(error, 'lineno', '?')},"
                    f" col {getattr(error, 'column', '?')}:"
                    f" {getattr(error, 'message', 'syntax error')}"
                )
        except (RecursionError, ValueError):  # pragma: no cover - 防御性
            errors.append("error collection failed")
        return {"tree": tree, "errors": errors, "version": label}
