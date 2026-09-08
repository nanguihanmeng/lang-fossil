"""Direct tests for engine matchers not exercised by builtin rules."""

from __future__ import annotations

from lang_fossil.core.engine import Engine, _match_string_prefix
from lang_fossil.parsers.parso_py import ParsoPythonParser
from lang_fossil.rules.registry import MatchSpec, RuleSpec


class _StubRegistry:
    """Minimal registry stand-in returning one preset rule."""

    def __init__(self, rule: RuleSpec) -> None:
        """Store the single rule served for every language."""
        self._rule = rule

    def for_language(self, language: str) -> list[RuleSpec]:
        """Return the preset rule for any language."""
        return [self._rule]

    def __iter__(self):  # pragma: no cover - digest path not used here
        return iter([self._rule])


def _rule(match: MatchSpec) -> RuleSpec:
    """Build a minimal valid rule for matcher tests."""
    return RuleSpec.model_validate(
        {
            "id": "PF050",
            "language": "python",
            "era": "paleozoic",
            "removed_in": "python3",
            "message": "m",
            "match": match.model_dump(),
        }
    )


def test_string_prefix_matcher_hits_u_prefix() -> None:
    """The string-prefix matcher supports prefix/target spellings."""
    rule = _rule(MatchSpec(kind="string_prefix", target="u"))
    tree = ParsoPythonParser().parse('x = u"text"\ny = "plain"\n').tree
    assert tree is not None
    positions = _match_string_prefix(rule, tree)
    assert len(positions) == 1
    assert positions[0][0] == 1


def test_engine_runs_synthetic_string_prefix_rule() -> None:
    """End to end: a u-prefix rule fires through the Engine facade."""
    engine = Engine(_StubRegistry(_rule(MatchSpec(kind="string_prefix", target="u"))))
    source = 'x = u"text"\n'
    fossils = engine.run("a.py", source, ParsoPythonParser().parse(source))
    assert [f.rule_id for f in fossils] == ["PF050"]
