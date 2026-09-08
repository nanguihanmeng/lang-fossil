"""语言嗅探：供发现阶段、规则包与 --fix 桥接共用.

分类基于扩展名。C/C++ 共用的 ``.h`` 存在歧义，由配置策略解析而非内容
评分：扫描设置携带 ``ambiguous_headers`` 策略（mode 加 glob overrides），
发现阶段据此判定每个头文件的语言归属（见 :mod:`lang_fossil.core.scanner`）.
"""

from __future__ import annotations

from pathlib import Path

# 规范的语言标识符。与 RuleSpec.language 及 scanner 的 parsers 注册表保持同步.
SUPPORTED_LANGUAGES = ("python", "javascript", "c", "cpp", "csharp", "java")

# 由通用逐行解析器（HeuristicParser）支持的语言；Python 除外——它有真正的
# 语法树前端（parso/ast）。派生自唯一的 SUPPORTED_LANGUAGES，新增语言不会
# 在 scanner 的解析器注册表中被遗漏.
HEURISTIC_LANGUAGES = tuple(lang for lang in SUPPORTED_LANGUAGES if lang != "python")

# C/C++ 歧义头文件扩展名标记；由 ambiguous_headers 配置策略解析.
HEADER_AMBIGUOUS = "c_header"

# 扩展名 -> 语言的唯一映射；.h 的值是歧义标记.
_LANG_BY_EXT = {
    ".py": "python",
    ".pyw": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".c": "c",
    ".h": HEADER_AMBIGUOUS,  # 由 ambiguous_headers 策略解析
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".hxx": "cpp",
    ".cs": "csharp",
    ".java": "java",
}


def sniff_language(path: Path) -> str | None:
    """按扩展名嗅探文件语言.

    Args:
        path: 候选文件路径.

    Returns:
        语言标识；C/C++ 共用的 ``.h`` 返回 ``HEADER_AMBIGUOUS``（待配置
        解析）；不支持的扩展名返回 ``None``.
    """
    return _LANG_BY_EXT.get(path.suffix.lower())


__all__ = [
    "HEADER_AMBIGUOUS",
    "HEURISTIC_LANGUAGES",
    "SUPPORTED_LANGUAGES",
    "sniff_language",
]
