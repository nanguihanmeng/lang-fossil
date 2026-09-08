"""lang-fossil 的领域模型.

领域对象使用冻结 dataclass（见 PRD 5.1 节）；配置模型使用 pydantic
（见 :mod:`lang_fossil.config`）.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 保留 era / 规则标识符。这些字符串承载聚合语义（unsafe 发现构成独立
# 地层；meta 发现属于工具级诊断），集中一处确保所有比较拼写一致.
ERA_UNSAFE = "unsafe"
ERA_META = "meta"
RULE_ID_META = "LF-IO"


@dataclass(frozen=True)
class Fossil:
    """一条检出的历史遗留产物.

    Attributes:
        rule_id: 产生该化石的规则标识.
        path: 所在文件的仓库相对路径.
        line: 1 起始的行号.
        column: 0 起始的列号.
        message: 面向用户的描述.
        era: 地层时代标签（如 ``paleozoic``、``mesozoic``）.
        provenance: 规则来源（如 ``pyupgrade``、``internal``）.
        severity: ``info`` / ``warning`` / ``error`` 之一.
        fix_hint: 可选的外部修复器建议.
        last_commit_year: 文件最近提交年（可选 git 富化）；关闭/未知时
            为 ``None``.
    """

    rule_id: str
    path: str
    line: int
    column: int
    message: str
    era: str
    provenance: str
    severity: str = "warning"
    fix_hint: str | None = None
    # 可选 git 富化；关闭/未知时为 None。带默认值置于末尾，使缺少该键的
    # 旧缓存载荷仍可正常加载.
    last_commit_year: int | None = None


@dataclass(frozen=True)
class ParseResult:
    """单文件解析结果；解析失败一律降级，绝不中断.

    Attributes:
        tree: 语言专属的解析树，整体失败时为 ``None``.
        errors: 解析过程中收集的非致命错误.
        language: 嗅探出的语言（如 ``python``）.
        grammar_version: 解析使用的语法版本（如 ``"2.7"``）；启发式
            解析器为 ``"n/a"``.
        heuristic: 解析（或语言识别）仅为正则启发式时为 True.
    """

    tree: object | None
    errors: tuple[str, ...]
    language: str
    grammar_version: str
    heuristic: bool = False


@dataclass(frozen=True)
class FileEntry:
    """一个被选中待扫描的文件."""

    path: str
    language: str


@dataclass(frozen=True)
class CloneMatch:
    """winnowing 指纹检出的跨文件代码克隆.

    Attributes:
        path_a / line_a: 第一处出现位置.
        path_b / line_b: 第二处出现位置.
        fingerprint: 共享的 k-gram 哈希.
        token_count: 重复 token 序列长度.
    """

    path_a: str
    line_a: int
    path_b: str
    line_b: int
    fingerprint: str
    token_count: int


@dataclass(frozen=True)
class ScanResult:
    """一次完整扫描的聚合结果."""

    fossils: tuple[Fossil, ...]
    scanned_files: int
    scanned_lines: int
    skipped_files: int
    parse_errors: tuple[str, ...]
    clones: tuple[CloneMatch, ...] = field(default_factory=tuple)
