"""Unit tests for rule loading/validation (mirrors rules/registry.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from lang_fossil.rules.registry import RuleRegistry, RuleSpec


def test_builtin_registry_loads(builtin_registry: RuleRegistry) -> None:
    """All builtin packs load; every supported language is present."""
    assert len(builtin_registry) >= 10
    languages = {rule.language for rule in builtin_registry}
    assert languages == {"python", "javascript", "c", "cpp", "csharp", "java"}


def test_rule_ids_unique_and_patterned(builtin_registry: RuleRegistry) -> None:
    """Every builtin rule id matches the canonical pattern."""
    import re

    pattern = re.compile(r"^[A-Z]{2,4}\d{3}$")
    ids = [rule.id for rule in builtin_registry]
    assert len(ids) == len(set(ids))
    assert all(pattern.match(rule_id) for rule_id in ids)


def test_every_rule_carries_provenance(builtin_registry: RuleRegistry) -> None:
    """Provenance is mandatory data (spec: 规则携带来源标注)."""
    assert all(rule.provenance for rule in builtin_registry)


def test_yaml_samples_align_with_rules() -> None:
    """Sample corpus rule ids must exist in the builtin registry."""
    samples_path = (
        Path(__file__).parents[3]
        / "src"
        / "lang_fossil"
        / "rules"
        / "builtin"
        / "python"
        / "samples"
        / "samples.yaml"
    )
    import yaml

    data = yaml.safe_load(samples_path.read_text(encoding="utf-8"))
    known = {rule.id for rule in RuleRegistry.load_builtin()}
    for group in ("positive", "negative"):
        for sample in data["samples"][group]:
            assert sample["id"] in known, f"unknown sample rule id {sample['id']}"


def test_duplicate_rule_id_rejected() -> None:
    """Duplicate ids across packs fail fast."""
    rule = RuleSpec.model_validate(
        {
            "id": "PF090",
            "language": "python",
            "era": "paleozoic",
            "removed_in": "python3",
            "message": "m",
            "match": {"kind": "name", "target": "xrange"},
        }
    )
    with pytest.raises(ValueError, match="duplicate"):
        RuleRegistry([rule, rule])


def test_fossil_requires_version_label() -> None:
    """A fossil without deprecated_in/removed_in is rejected."""
    with pytest.raises(ValueError, match="must declare"):
        RuleSpec.model_validate(
            {
                "id": "PF091",
                "language": "python",
                "era": "paleozoic",
                "message": "m",
                "match": {"kind": "name", "target": "xrange"},
            }
        )


def test_unsafe_rules_require_unsafe_era_and_no_versions() -> None:
    """unsafe rules must use era 'unsafe' and carry no version labels."""
    with pytest.raises(ValueError, match="reserved era"):
        RuleSpec.model_validate(
            {
                "id": "CF099",
                "language": "c",
                "category": "unsafe",
                "era": "c99",
                "message": "m",
                "match": {"kind": "regex", "target": "x"},
            }
        )
    with pytest.raises(ValueError, match="cannot carry"):
        RuleSpec.model_validate(
            {
                "id": "CF098",
                "language": "c",
                "category": "unsafe",
                "era": "unsafe",
                "removed_in": "c99",
                "message": "m",
                "match": {"kind": "regex", "target": "x"},
            }
        )


def test_fossil_cannot_use_reserved_era() -> None:
    """A fossil rule must not claim the reserved 'unsafe' era."""
    with pytest.raises(ValueError, match="reserved era"):
        RuleSpec.model_validate(
            {
                "id": "CF097",
                "language": "c",
                "era": "unsafe",
                "removed_in": "c99",
                "message": "m",
                "match": {"kind": "regex", "target": "x"},
            }
        )


def test_valid_unsafe_rule_loads() -> None:
    """A consistent unsafe rule is accepted."""
    rule = RuleSpec.model_validate(
        {
            "id": "CF096",
            "language": "c",
            "category": "unsafe",
            "era": "unsafe",
            "message": "m",
            "match": {"kind": "regex", "target": "x"},
        }
    )
    assert rule.category == "unsafe"


def test_invalid_rule_id_rejected(tmp_path: Path) -> None:
    """Schema rejects ids outside the canonical pattern."""
    content = (
        "rules:\n"
        "  - id: bad\n"
        "    language: python\n"
        "    era: paleozoic\n"
        "    message: m\n"
        "    match:\n"
        "      kind: name\n"
        "      target: xrange\n"
    )
    path = tmp_path / "bad.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="rule id"):
        RuleRegistry.load_from_dir(tmp_path)


def test_unknown_fields_rejected(tmp_path: Path) -> None:
    """extra=forbid: typo'd keys are load-time errors, not silent no-ops."""
    content = (
        "rules:\n"
        "  - id: PF099\n"
        "    language: python\n"
        "    era: paleozoic\n"
        "    message: m\n"
        "    matsh:\n"
        "      kind: name\n"
        "      target: xrange\n"
    )
    path = tmp_path / "typo.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="rule #0"):
        RuleRegistry.load_from_dir(tmp_path)


def test_for_language_filtering(builtin_registry: RuleRegistry) -> None:
    """Rules are retrievable per language."""
    assert all(rule.language == "python" for rule in builtin_registry.for_language("python"))
    assert builtin_registry.for_language("cobol") == []
