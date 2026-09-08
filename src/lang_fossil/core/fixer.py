"""``--fix`` 桥接：把化石映射到外部修复器命令.

lang-fossil 不自行实现 codemod：按文件分组桥接到成熟工具
（pyupgrade、eslint --fix），一次调用即可覆盖该文件内全部可修复化石.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lang_fossil.core.language import sniff_language
from lang_fossil.core.models import Fossil

_PYTHON_TOOL = ("pyupgrade", "--py3-plus")
_JS_TOOL = ("eslint", "--fix")
# 没有桥接修复器的语言不产生修复命令；规则自然不带 fix_hint（或虽有
# hint 但无工具，同样跳过）.
_TOOL_BY_LANGUAGE = {
    "python": _PYTHON_TOOL,
    "javascript": _JS_TOOL,
}

# 有桥接修复器的语言集合（供 CLI 说明桥接范围）.
FIXABLE_LANGUAGES = frozenset(_TOOL_BY_LANGUAGE)


@dataclass(frozen=True)
class FixCommand:
    """一次具体的外部修复器调用."""

    tool: str
    args: tuple[str, ...]
    paths: tuple[str, ...]
    rule_ids: tuple[str, ...]

    @property
    def run_args(self) -> tuple[str, ...]:
        """构造可执行的 argv.

        以 ``-`` 开头的路径加 ``--`` 选项结束符保护，避免形如选项的文件
        名被桥接工具当作参数解析（列表传参已排除 shell 注入）.

        Returns:
            完整参数向量：tool、工具参数、路径.
        """
        separator: tuple[str, ...] = ("--",) if any(p.startswith("-") for p in self.paths) else ()
        return (self.tool, *self.args, *separator, *self.paths)

    @property
    def command_line(self) -> str:
        """渲染完整命令行，供展示或执行.

        Returns:
            与 shell 无关的命令字符串.
        """
        return " ".join(self.run_args)


def build_fix_plan(fossils: list[Fossil]) -> list[FixCommand]:
    """把可修复化石按工具、按文件分组成修复命令.

    化石携带 ``fix_hint`` 即视为可修复。文件分组保证每个工具对每个
    路径只调用一次.

    Args:
        fossils: 扫描得到的化石.

    Returns:
        顺序确定的修复命令列表.
    """
    grouped: dict[tuple[str, tuple[str, ...]], set[str]] = {}
    for fossil in fossils:
        if not fossil.fix_hint:
            continue
        language = sniff_language(Path(fossil.path))
        tool = _TOOL_BY_LANGUAGE.get(language or "")
        if tool is None:
            continue  # 该语言尚无桥接修复器
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
    """列出带 fix_hint 但没有桥接修复器的语言.

    由 ``fix`` 命令上报，用户不会困惑为什么带提示的化石没有产生命令.

    Args:
        fossils: 扫描得到的化石.

    Returns:
        排序后的语言名列表.
    """
    hinted = {sniff_language(Path(fossil.path)) for fossil in fossils if fossil.fix_hint}
    return sorted(lang for lang in hinted if lang and lang not in FIXABLE_LANGUAGES)
