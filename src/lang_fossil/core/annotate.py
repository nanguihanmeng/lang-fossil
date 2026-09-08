"""Annotation stage: attach archaeology metadata to external linter findings.

The `annotate` CLI command imports clang-tidy / PMD / eslint reports and
labels every finding with lang-fossil's archaeology metadata. Two channels
produce a label, in order:

1. **Alias channel**: a builtin rule whose ``provenance`` declares the
   external rule id (``ecosystem: eslint (no-var)``) is matched directly.
2. **Position channel**: when no alias matches, the finding's file is
   scanned with the builtin rules and any fossil on the *same line* labels
   the finding (a genuine archaeology signal for that location).

Findings with neither channel are kept and reported as ``unannotated``:
lang-fossil never invents a date for a construct it cannot date.
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

# Matches "ecosystem: <tool> (<rule>)" segments inside a provenance string.
_ALIAS_RE = re.compile(r"ecosystem:\s*([A-Za-z0-9_.+-]+?)\s*\(\s*([^()]+?)\s*\)")


@dataclass(frozen=True)
class Annotation:
    """The archaeology label attached to one external finding.

    Attributes:
        era: lang-fossil era for the location/rule (``unsafe`` = review
            finding, never dated).
        category: ``fossil`` (age-datable) or ``unsafe``.
        rule_id: Builtin rule id backing the label.
        provenance: Builtin rule provenance (source of the mapping).
        source: Which channel produced the label (``alias`` / ``position``).
    """

    era: str
    category: str
    rule_id: str
    provenance: str
    source: str


@dataclass(frozen=True)
class AnnotatedFinding:
    """An external finding plus its optional archaeology label."""

    finding: ExternalFinding
    annotation: Annotation | None = None


def build_annotator() -> Annotator:
    """Build an annotator over the builtin rules and zombie snapshot.

    Returns:
        A ready-to-use annotator.
    """
    registry = RuleRegistry.load_builtin()
    return Annotator(registry, Engine(registry, ZombieApiDB.load()))


class Annotator:
    """Labels external findings using the builtin rule set."""

    def __init__(self, registry: RuleRegistry, engine: Engine) -> None:
        """Index provenance aliases and keep the engine for position scans.

        Args:
            registry: Validated builtin rules.
            engine: Engine used to re-scan files for the position channel.
        """
        self._engine = engine
        self._aliases: dict[tuple[str, str], list[RuleSpec]] = {}
        for rule in registry:
            for tool, external_rule in _extract_aliases(rule):
                # Provenance keeps human casing ("PMD (LooseCoupling)") while
                # importer tool tags are lowercase; match case-insensitively so
                # a declared alias is never silently dead due to casing.
                self._aliases.setdefault((tool.lower(), external_rule.lower()), []).append(rule)
        self._file_fossils: dict[str, list[Fossil]] = {}
        self._parsers: dict[str, Parser] = {}

    def annotate(self, root: Path, findings: list[ExternalFinding]) -> list[AnnotatedFinding]:
        """Label a batch of external findings.

        Args:
            root: Repository root (file reads for the position channel).
            findings: Imported external findings.

        Returns:
            Findings in input order, each with an optional annotation.
        """
        annotated: list[AnnotatedFinding] = []
        for finding in findings:
            annotation = self._label(root, finding)
            annotated.append(AnnotatedFinding(finding=finding, annotation=annotation))
        return annotated

    def _label(self, root: Path, finding: ExternalFinding) -> Annotation | None:
        """Produce the best label for one finding (alias, then position)."""
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
        """Return non-meta builtin fossils on the finding's exact line."""
        path = finding.path
        if path not in self._file_fossils:
            self._file_fossils[path] = self._scan_file(root, path)
        # Prefer an age-datable fossil over an unsafe one on the same line.
        fossils = [
            f for f in self._file_fossils[path] if f.line == finding.line and f.era != ERA_META
        ]
        return sorted(fossils, key=lambda f: f.era == ERA_UNSAFE)

    def _scan_file(self, root: Path, path: str) -> list[Fossil]:
        """Run builtin rules over one file, returning its fossils.

        The position channel only reads files inside the repository root:
        external reports are not a trusted source, and a ``filePath`` of
        ``../secret`` or an absolute path must never escape the scan root
        (see the code-review note on report-driven path traversal).

        Args:
            root: Repository root.
            path: Finding path (posix, possibly attacker-influenced).

        Returns:
            Fossils for the file, or ``[]`` when the path resolves outside
            the root, the language is unsupported, or the file is unreadable.
        """
        language = sniff_language(Path(path))
        if language is None or language == HEADER_AMBIGUOUS:
            return []
        source_path = root / path
        resolved = source_path.resolve()
        root_resolved = root.resolve()
        if resolved != root_resolved and root_resolved not in resolved.parents:
            return []  # path escapes the scan root; never read outside it
        parser = self._parser_for(language)
        try:
            source = source_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        parse_result = parser.parse(source)
        return self._engine.run(path, source, parse_result)

    def _parser_for(self, language: str) -> Parser:
        """Return (and cache) the parser for a language."""
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
    """Extract ``(tool, external_rule)`` aliases from a rule's provenance.

    Args:
        rule: A builtin rule whose provenance may reference external rules.

    Returns:
        Alias pairs declared as ``ecosystem: <tool> (<rule>)``.
    """
    return [(tool, external_rule) for tool, external_rule in _ALIAS_RE.findall(rule.provenance)]


def _era_of(rule: RuleSpec) -> str:
    """Return the stratum label of a rule."""
    return ERA_UNSAFE if rule.category == "unsafe" else rule.era
