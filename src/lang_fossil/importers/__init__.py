"""导入器：把外部 linter 报告解析为统一 finding.

lang-fossil 不运行 clang-tidy / PMD / eslint，而是**消费**其输出，经
:mod:`lang_fossil.core.annotate` 为每条 finding 附加考古元数据
（era、category、provenance）.

每个导入器都是纯函数，把一份报告文件映射为路径规范化（posix、仓库
相对）的 :class:`ExternalFinding` 列表。支持的机器可读格式（见
``docs/rules-guide.md``）：

- eslint：JSON（默认 CLI 输出）
- clang-tidy：文本诊断（``file:line:col: severity: msg [rule]``）
- PMD：XML 报告（``-f xml``）
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SUPPORTED_TOOLS = ("eslint", "clang-tidy", "pmd")


@dataclass(frozen=True)
class ExternalFinding:
    """外部 linter 报告中的一条 finding.

    Attributes:
        tool: 来源工具（``eslint`` / ``clang-tidy`` / ``pmd``）.
        rule_id: 工具规则标识（如 ``no-var``）.
        path: 仓库相对文件路径（posix 分隔符）.
        line: 1 起始行号.
        column: 0 起始列号（尽力而为；工具未报告时为 0）.
        message: finding 描述.
        severity: 规范化的严重级（``error`` / ``warning`` / ``info``）.
    """

    tool: str
    rule_id: str
    path: str
    line: int
    column: int = 0
    message: str = ""
    severity: str = "warning"


def normalize_path(raw: str, root: Path) -> str:
    """把报告路径规范化为 posix 的 root 相对路径.

    绝对路径尽量对 ``root`` 相对化；已是相对路径的原样保留（posix
    分隔符）。

    Args:
        raw: 外部工具写出的路径.
        root: 用于相对化的仓库根.

    Returns:
        规范化后的仓库相对 posix 路径.
    """
    path = Path(raw)
    if path.is_absolute():
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            return path.as_posix()
    return path.as_posix()


def parse_report(tool: str, content: str, root: Path) -> list[ExternalFinding]:
    """把报告文本分派给 ``tool`` 对应的导入器.

    Args:
        tool: :data:`SUPPORTED_TOOLS` 之一.
        content: 报告原文.
        root: 用于路径规范化的仓库根.

    Returns:
        规范化的外部 finding 列表.

    Raises:
        ValueError: ``tool`` 不受支持或报告格式非法.
    """
    if tool == "eslint":
        from lang_fossil.importers import eslint

        return eslint.parse(content, root)
    if tool == "clang-tidy":
        from lang_fossil.importers import clang_tidy

        return clang_tidy.parse(content, root)
    if tool == "pmd":
        from lang_fossil.importers import pmd

        return pmd.parse(content, root)
    raise ValueError(f"unsupported linter tool {tool!r}; use one of {SUPPORTED_TOOLS}")
