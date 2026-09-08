"""规则加载与 schema 校验.

规则是 YAML 文件，仅用 ``yaml.safe_load`` 加载（注入缓解），并经
pydantic 白名单 schema 校验：未知字段、坏 id、越界 severity 都在加载
期报错，而不是带病静默运行.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from lang_fossil.core.models import ERA_UNSAFE

_RULE_ID_PATTERN = re.compile(r"^[A-Z]{2,4}\d{3}$")

MatchKind = Literal["node", "name", "attribute", "string_prefix", "import", "regex"]


class MatchSpec(BaseModel):
    """规则匹配解析树或原始源码的方式."""

    model_config = ConfigDict(extra="forbid")

    kind: MatchKind
    target: str = Field(min_length=1)
    prefix: str | None = None  # 仅 kind="string_prefix" 有效
    regex_flags: str | None = None  # 仅 kind="regex" 有效，如 "i"

    @field_validator("prefix")
    @classmethod
    def _prefix_only_for_strings(cls, v: str | None) -> str | None:
        """拒绝在非 string-prefix 规则上使用 ``prefix``."""
        if v is not None:
            raise ValueError("'prefix' is only valid for kind='string_prefix'")
        return v


class RuleSpec(BaseModel):
    """一条已校验的规则定义.

    Attributes:
        id: 规则标识，如 ``PF001``.
        language: 目标语言.
        category: ``fossil`` 表示被语言标准移除/废弃的构造（可断代），
            ``unsafe`` 表示至今仍合法的不良实践（永不断代）.
        era: 地层时代。fossil 规则使用语言代际标签（如 ``c99``、
            ``cpp17``）；unsafe 规则必须使用保留 ``unsafe`` era.
        deprecated_in / removed_in: 佐证化石判定的可选标准版本标签
            （如 ``"c++17"``、``"c11"``）。fossil 至少其一必填；unsafe
            两者皆禁.
        message: 面向用户的发现描述.
        severity: ``info`` / ``warning`` / ``error``.
        provenance: 规则来源；映射到现有 lint 生态（如 ``pyupgrade``、
            ``eslint (no-var)``、``internal``）.
        source: 可选的官方引用 URL，佐证移除/废弃结论.
        fix_hint: 可选提示，供 ``--fix`` 桥接消费.
        match: 匹配规格.
        match_mode: ``ast`` 需要真实解析树；``heuristic`` 在源码行上
            运行（JS 与 Py2 之前的语料使用）.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    language: Literal["python", "javascript", "c", "cpp", "csharp", "java"]
    category: Literal["fossil", "unsafe"] = "fossil"
    era: str = Field(min_length=1)
    deprecated_in: str | None = None
    removed_in: str | None = None
    message: str = Field(min_length=1)
    severity: Literal["info", "warning", "error"] = "warning"
    provenance: str = "internal"
    source: str | None = None
    fix_hint: str | None = None
    match: MatchSpec
    match_mode: Literal["ast", "heuristic"] = "ast"

    @field_validator("id")
    @classmethod
    def _validate_id(cls, v: str) -> str:
        """强制严格、可 grep 的规则 id 格式."""
        if not _RULE_ID_PATTERN.match(v):
            raise ValueError(f"rule id {v!r} must match {_RULE_ID_PATTERN.pattern}")
        return v

    @model_validator(mode="after")
    def _guard_category_consistency(self) -> RuleSpec:
        """强制 category/era/版本的一致性.

        检测"至今合法"事物的规则绝不能冒充可断代的化石（历史性错误
        结论）；反之化石必须有版本标签佐证.

        Returns:
            校验通过的规则.

        Raises:
            ValueError: category/era/版本不匹配.
        """
        has_version = self.deprecated_in is not None or self.removed_in is not None
        if self.category == ERA_UNSAFE:
            if self.era != ERA_UNSAFE:
                raise ValueError("unsafe rules must use the reserved era 'unsafe'")
            if has_version:
                raise ValueError("unsafe rules cannot carry deprecated_in/removed_in")
            return self
        if self.era == ERA_UNSAFE:
            raise ValueError("fossil rules cannot use the reserved era 'unsafe'")
        if not has_version:
            raise ValueError(f"fossil rule {self.id} must declare deprecated_in or removed_in")
        return self


class RuleRegistry:
    """不可变的已校验规则集合."""

    def __init__(self, rules: list[RuleSpec]) -> None:
        """按语言索引存储规则.

        Args:
            rules: 已校验的规则列表（重复 id 会被拒绝）.
        """
        seen: set[str] = set()
        for rule in rules:
            if rule.id in seen:
                raise ValueError(f"duplicate rule id: {rule.id}")
            seen.add(rule.id)
        self._rules = rules
        self._by_language: dict[str, list[RuleSpec]] = {}
        for rule in rules:
            self._by_language.setdefault(rule.language, []).append(rule)

    @classmethod
    def load_builtin(cls) -> RuleRegistry:
        """加载随包分发的规则.

        Returns:
            包含全部内置规则包的注册表.

        Raises:
            ValueError: 任一内置文件未通过 schema 校验.
        """
        return cls.load_from_dir(Path(__file__).parent / "builtin")

    @classmethod
    def load_from_dir(cls, directory: Path) -> RuleRegistry:
        """加载目录下全部 ``*.yaml`` / ``*.yml`` 规则包.

        Args:
            directory: 规则包树根（``language/pack.yaml``）.

        Returns:
            所有合法规则的注册表.

        Raises:
            ValueError: 任一文件解析或校验失败；加载 fail-fast，损坏的
                规则包绝不静默扫描.
        """
        rules: list[RuleSpec] = []
        for path in sorted(directory.rglob("*.y*ml")):
            if "samples" in path.parts:
                continue  # 样本语料供测试消费，不作为规则加载
            rules.extend(cls._load_file(path))
        return cls(rules)

    @staticmethod
    def _load_file(path: Path) -> list[RuleSpec]:
        """加载并校验单个 YAML 规则包.

        Args:
            path: YAML 规则包路径.

        Returns:
            其中全部已校验规则.

        Raises:
            ValueError: YAML 语法错误或 schema 违规.
        """
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise ValueError(f"invalid YAML in {path}: {exc}") from exc
        if not isinstance(raw, dict) or not isinstance(raw.get("rules"), list):
            raise ValueError(f"{path} must be a mapping with a 'rules' list")

        rules: list[RuleSpec] = []
        for index, item in enumerate(raw["rules"]):
            try:
                rules.append(RuleSpec.model_validate(item))
            except Exception as exc:
                raise ValueError(f"{path}: rule #{index}: {exc}") from exc
        return rules

    def for_language(self, language: str) -> list[RuleSpec]:
        """返回某语言注册的全部规则.

        Args:
            language: 嗅探出的语言名.

        Returns:
            该语言的规则（可能为空）.
        """
        return self._by_language.get(language, [])

    def __iter__(self) -> Iterator[RuleSpec]:
        """遍历全部规则."""
        return iter(self._rules)

    def __len__(self) -> int:
        """返回规则总数."""
        return len(self._rules)
