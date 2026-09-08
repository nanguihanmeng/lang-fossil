"""Rule loading and schema validation.

Rules are YAML files loaded with ``yaml.safe_load`` only (injection
mitigation) and validated against a pydantic whitelist schema: unknown
fields, bad identifiers, or out-of-range severities are rejected at load
time, not at scan time.
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
    """How a rule matches the parsed tree or raw source."""

    model_config = ConfigDict(extra="forbid")

    kind: MatchKind
    target: str = Field(min_length=1)
    prefix: str | None = None  # only for kind="string_prefix"
    regex_flags: str | None = None  # only for kind="regex", e.g. "i"

    @field_validator("prefix")
    @classmethod
    def _prefix_only_for_strings(cls, v: str | None) -> str | None:
        """Reject ``prefix`` on non string-prefix rules."""
        if v is not None:
            raise ValueError("'prefix' is only valid for kind='string_prefix'")
        return v


class RuleSpec(BaseModel):
    """A validated rule definition.

    Attributes:
        id: Rule identifier, e.g. ``PF001``.
        language: Target language.
        category: ``fossil`` for constructs removed/deprecated by a language
            standard (age-datable), ``unsafe`` for bad-practice patterns that
            are still legal today (never dated).
        era: Stratigraphic era. Fossil rules use a language-generation label
            (e.g. ``c99``, ``cpp17``); unsafe rules must use the reserved
            ``unsafe`` era.
        deprecated_in / removed_in: Optional standard version labels that
            substantiate a fossil finding (e.g. ``"c++17"``, ``"c11"``). A
            fossil rule must carry at least one; unsafe rules carry neither.
        message: Human-readable finding description.
        severity: ``info`` / ``warning`` / ``error``.
        provenance: Source of the rule; maps it to the existing lint
            ecosystem (e.g. ``pyupgrade``, ``eslint (no-var)``, ``internal``).
        source: Optional official reference URL (standard/library docs)
            substantiating the removal/deprecation claim.
        fix_hint: Optional hint consumed by the ``--fix`` bridge.
        match: Matching specification.
        match_mode: ``ast`` requires a real parse tree; ``heuristic`` rules
            run on raw lines (used for JS and pre-2.7 Python corpora).
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
        """Enforce a strict, greppable rule-id format."""
        if not _RULE_ID_PATTERN.match(v):
            raise ValueError(f"rule id {v!r} must match {_RULE_ID_PATTERN.pattern}")
        return v

    @model_validator(mode="after")
    def _guard_category_consistency(self) -> RuleSpec:
        """Enforce category/era/version coherence.

        A rule must never masquerade as an age-datable fossil when it detects
        something that is still legal (the historical false-conclusion bug);
        conversely a fossil must be substantiated by a version label.

        Returns:
            The validated rule.

        Raises:
            ValueError: On category/era/version mismatches.
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
    """Immutable collection of validated rules."""

    def __init__(self, rules: list[RuleSpec]) -> None:
        """Store rules indexed by language.

        Args:
            rules: Validated rule specs (duplicate ids are rejected).
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
        """Load rules bundled with the package.

        Returns:
            A registry containing all builtin rule packs.

        Raises:
            ValueError: If any builtin file fails schema validation.
        """
        return cls.load_from_dir(Path(__file__).parent / "builtin")

    @classmethod
    def load_from_dir(cls, directory: Path) -> RuleRegistry:
        """Load every ``*.yaml`` / ``*.yml`` rule pack under a directory.

        Args:
            directory: Root of a rule pack tree (``language/pack.yaml``).

        Returns:
            A registry of all valid rules found.

        Raises:
            ValueError: If a file fails to parse or validate; loading is
                fail-fast so a broken rule pack never scans silently.
        """
        rules: list[RuleSpec] = []
        for path in sorted(directory.rglob("*.y*ml")):
            if "samples" in path.parts:
                continue  # sample corpora are consumed by tests, not loaded as rules
            rules.extend(cls._load_file(path))
        return cls(rules)

    @staticmethod
    def _load_file(path: Path) -> list[RuleSpec]:
        """Load and validate a single YAML rule pack.

        Args:
            path: Path to the YAML file.

        Returns:
            The validated rules inside it.

        Raises:
            ValueError: On YAML syntax errors or schema violations.
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
        """Return all rules registered for a language.

        Args:
            language: Sniffed language name.

        Returns:
            Rules for that language (possibly empty).
        """
        return self._by_language.get(language, [])

    def __iter__(self) -> Iterator[RuleSpec]:
        """Iterate over all rules."""
        return iter(self._rules)

    def __len__(self) -> int:
        """Return the number of rules."""
        return len(self._rules)
