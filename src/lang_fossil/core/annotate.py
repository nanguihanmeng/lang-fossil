"""标注阶段：为外部 linter finding 附加考古元数据.

``annotate`` CLI 命令导入 clang-tidy / PMD / eslint 报告，为每条
finding 附加 lang-fossil 的考古元标签。两个通道按序产出标签：

1. **alias 通道**：内置规则的 ``provenance`` 声明了外部规则 id
   （``ecosystem: eslint (no-var)``）时直接匹配.
2. **position 通道**：无别名时，对 finding 所在文件运行内置规则，
   *同一行* 上的化石为该位置提供考古标注（真实的位置级断代信号）.

两个通道皆无信号的 finding 保留并报告为 ``unannotated``：
lang-fossil 绝不为无法断代的构造捏造年代.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from lang_fossil.core.engine import Engine
from lang_fossil.core.language import HEADER_AMBIGUOUS, sniff_language
from lang_fossil.core.models import ERA_META, ERA_UNSAFE, Fossil
from lang_fossil.core.zombie_api import ZombieApiDB
from lang_fossil.importers import ExternalFinding
from lang_fossil.parsers.base import Parser
from lang_fossil.parsers.heuristic import HeuristicParser
from lang_fossil.parsers.parso_py import ParsoPythonParser
from lang_fossil.rules.registry import RuleRegistry, RuleSpec

# 匹配 provenance 字符串中 "ecosystem: <tool> (<rule>)" 片段.
_ALIAS_RE = re.compile(r"ecosystem:\s*([A-Za-z0-9_.+-]+?)\s*\(\s*([^()]+?)\s*\)")


@dataclass(frozen=True)
class Annotation:
    """附加到外部 finding 的考古标签.

    Attributes:
        era: 该位置/规则的 lang-fossil era（``unsafe`` = 审查发现，
            永不断代）.
        category: ``fossil``（可断代）或 ``unsafe``.
        rule_id: 支撑标签的内置规则 id.
        provenance: 内置规则的 provenance（映射来源）.
        source: 产生标签的通道（``alias`` / ``position``）.
    """

    era: str
    category: str
    rule_id: str
    provenance: str
    source: str


@dataclass(frozen=True)
class AnnotatedFinding:
    """外部 finding 及其可选考古标签."""

    finding: ExternalFinding
    annotation: Annotation | None = None


def build_annotator() -> Annotator:
    """基于内置规则与僵尸快照构建标注器.

    Returns:
        可用的标注器.
    """
    registry = RuleRegistry.load_builtin()
    return Annotator(registry, Engine(registry, ZombieApiDB.load()))


class Annotator:
    """使用内置规则集为外部 finding 打标签."""

    def __init__(self, registry: RuleRegistry, engine: Engine) -> None:
        """索引 provenance 别名，并保留引擎供位置扫描使用.

        Args:
            registry: 已校验的内置规则.
            engine: 位置通道重扫文件用的引擎.
        """
        self._engine = engine
        self._aliases: dict[tuple[str, str], list[RuleSpec]] = {}
        for rule in registry:
            for tool, external_rule in _extract_aliases(rule):
                # provenance 保留人类书写的大小写（"PMD (LooseCoupling)"），
                # 导入器工具标签为小写；匹配大小写不敏感，避免声明过的
                # 别名因大小写而静默失效.
                self._aliases.setdefault((tool.lower(), external_rule.lower()), []).append(rule)
        self._file_fossils: dict[str, list[Fossil]] = {}
        self._parsers: dict[str, Parser] = {}

    def annotate(self, root: Path, findings: list[ExternalFinding]) -> list[AnnotatedFinding]:
        """为一批外部 finding 打标签.

        Args:
            root: 仓库根（position 通道的文件读取基准）.
            findings: 已导入的外部 finding.

        Returns:
            按输入顺序排列、各带可选标注的 finding.
        """
        annotated: list[AnnotatedFinding] = []
        for finding in findings:
            annotation = self._label(root, finding)
            annotated.append(AnnotatedFinding(finding=finding, annotation=annotation))
        return annotated

    def _label(self, root: Path, finding: ExternalFinding) -> Annotation | None:
        """为单条 finding 产出最佳标签（先 alias，后 position）."""
        alias = self._aliases.get((finding.tool.lower(), finding.rule_id.lower()))
        if alias:
            rule = alias[0]
            return Annotation(
                era=_era_of(rule),
                category=rule.category,
                rule_id=rule.id,
                provenance=rule.provenance,
                source="alias",
            )
        for fossil in self._fossils_on_line(root, finding):
            return Annotation(
                era=fossil.era,
                category=ERA_UNSAFE if fossil.era == ERA_UNSAFE else "fossil",
                rule_id=fossil.rule_id,
                provenance=fossil.provenance,
                source="position",
            )
        return None

    def _fossils_on_line(self, root: Path, finding: ExternalFinding) -> list[Fossil]:
        """返回 finding 精确行上的非 meta 内置化石."""
        path = finding.path
        if path not in self._file_fossils:
            self._file_fossils[path] = self._scan_file(root, path)
        # 同行上可断代的 fossil 优先于 unsafe.
        fossils = [
            f for f in self._file_fossils[path] if f.line == finding.line and f.era != ERA_META
        ]
        return sorted(fossils, key=lambda f: f.era == ERA_UNSAFE)

    def _scan_file(self, root: Path, path: str) -> list[Fossil]:
        """对一个文件运行内置规则，返回其化石.

        position 通道只读取扫描根内的文件：外部报告不是可信来源，
        ``../secret`` 之类的 ``filePath`` 或绝对路径绝不允许逃出扫描根
        （见代码审查报告的"报告驱动路径穿越"条目）.

        Args:
            root: 仓库根.
            path: finding 路径（posix，可能被外部影响）.

        Returns:
            该文件的化石；路径逃出根、语言不支持或文件不可读时为 ``[]``.
        """
        language = sniff_language(Path(path))
        if language is None or language == HEADER_AMBIGUOUS:
            return []
        source_path = root / path
        resolved = source_path.resolve()
        root_resolved = root.resolve()
        if resolved != root_resolved and root_resolved not in resolved.parents:
            return []  # 路径逃出扫描根；绝不读取根外文件
        parser = self._parser_for(language)
        try:
            source = source_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        parse_result = parser.parse(source)
        return self._engine.run(path, source, parse_result)

    def _parser_for(self, language: str) -> Parser:
        """返回（并缓存）某语言的解析器."""
        cached = self._parsers.get(language)
        if cached is not None:
            return cached
        if language == "python":
            parser: Parser = ParsoPythonParser()
        else:
            parser = HeuristicParser(language)
        self._parsers[language] = parser
        return parser


def _extract_aliases(rule: RuleSpec) -> list[tuple[str, str]]:
    """从规则的 provenance 提取 ``(tool, external_rule)`` 别名.

    Args:
        rule: provenance 可能引用外部规则的内置规则.

    Returns:
        以 ``ecosystem: <tool> (<rule>)`` 声明的别名对.
    """
    return [(tool, external_rule) for tool, external_rule in _ALIAS_RE.findall(rule.provenance)]


def _era_of(rule: RuleSpec) -> str:
    """返回规则的地层标签."""
    return ERA_UNSAFE if rule.category == "unsafe" else rule.era
