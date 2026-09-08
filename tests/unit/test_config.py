"""Unit tests for configuration (mirrors config.py; spec section 5.4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from lang_fossil.config import ConfigError, LangFossilSettings, load_settings


def test_defaults_load_without_toml(tmp_path: Path) -> None:
    """A missing TOML file degrades to all defaults."""
    settings = load_settings(toml_path=tmp_path / "missing.toml")
    assert settings.scan.workers == 0
    assert settings.git.enabled is False
    assert settings.cache.enabled is True


def test_namespace_isolation(tmp_path: Path) -> None:
    """Other [tool.*] sections never enter the model (extra=forbid safe)."""
    toml = tmp_path / "pyproject.toml"
    toml.write_text(
        "[tool.black]\nline-length = 88\n\n"
        "[tool.pytest.ini_options]\ntestpaths = ['tests']\n\n"
        "[tool.lang-fossil.scan]\nworkers = 4\n",
        encoding="utf-8",
    )
    settings = load_settings(toml_path=toml)
    assert settings.scan.workers == 4
    assert settings.scan.exclude  # defaults preserved


def test_missing_section_degrades(tmp_path: Path) -> None:
    """A pyproject without [tool.lang-fossil] yields defaults."""
    toml = tmp_path / "pyproject.toml"
    toml.write_text("[tool.black]\nline-length = 88\n", encoding="utf-8")
    settings = load_settings(toml_path=toml)
    assert settings.scan.workers == 0


def test_invalid_toml_raises(tmp_path: Path) -> None:
    """Invalid TOML is a hard config error."""
    toml = tmp_path / "pyproject.toml"
    toml.write_text("not [valid\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="Invalid TOML"):
        load_settings(toml_path=toml)


def test_cli_overrides_win(tmp_path: Path) -> None:
    """CLI overrides beat TOML values."""
    toml = tmp_path / "pyproject.toml"
    toml.write_text("[tool.lang-fossil.scan]\nworkers = 2\n", encoding="utf-8")
    settings = load_settings({"scan": {"workers": 8}}, toml_path=toml)
    assert settings.scan.workers == 8


def test_env_overrides_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Environment variables beat TOML (pydantic-settings layer)."""
    toml = tmp_path / "pyproject.toml"
    toml.write_text("[tool.lang-fossil.scan]\nworkers = 2\n", encoding="utf-8")
    monkeypatch.setenv("LANG_FOSSIL_SCAN__WORKERS", "6")
    settings = load_settings(toml_path=toml)
    assert settings.scan.workers == 6


def test_env_optional_scalar_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An Optional[T] field (max_fossil_index) honours its env variable."""
    monkeypatch.setenv("LANG_FOSSIL_MAX_FOSSIL_INDEX", "1.5")
    settings = load_settings(toml_path=tmp_path / "missing.toml")
    assert settings.max_fossil_index == 1.5


def test_invalid_env_scalar_is_loud(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An unparseable env value raises ConfigError instead of being ignored."""
    monkeypatch.setenv("LANG_FOSSIL_SCAN__WORKERS", "abc")
    with pytest.raises(ConfigError, match="LANG_FOSSIL_SCAN__WORKERS"):
        load_settings(toml_path=tmp_path / "missing.toml")


def test_ambiguous_headers_defaults(tmp_path: Path) -> None:
    """The header policy defaults to auto mode with no overrides."""
    settings = load_settings(toml_path=tmp_path / "missing.toml")
    assert settings.scan.ambiguous_headers.mode == "auto"
    assert settings.scan.ambiguous_headers.overrides == {}


def test_ambiguous_headers_from_toml(tmp_path: Path) -> None:
    """mode and glob overrides are read from the [tool.lang-fossil] section."""
    toml = tmp_path / "pyproject.toml"
    toml.write_text(
        "[tool.lang-fossil.scan.ambiguous_headers]\n"
        'mode = "cpp"\n'
        "[tool.lang-fossil.scan.ambiguous_headers.overrides]\n"
        '"legacy/*.h" = "c"\n',
        encoding="utf-8",
    )
    settings = load_settings(toml_path=toml)
    policy = settings.scan.ambiguous_headers
    assert policy.mode == "cpp"
    assert policy.overrides == {"legacy/*.h": "c"}


def test_unknown_key_raises(tmp_path: Path) -> None:
    """extra=forbid: typos in config keys are loud errors."""
    toml = tmp_path / "pyproject.toml"
    toml.write_text("[tool.lang-fossil]\nworkres = 4\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings(toml_path=toml)


def test_negative_threshold_rejected() -> None:
    """--max-fi must be >= 0 (validated twice: field + guard)."""
    with pytest.raises(Exception, match="max_fossil_index"):
        LangFossilSettings(max_fossil_index=-1.0)


def test_invalid_value_range(tmp_path: Path) -> None:
    """Out-of-range values are rejected with pydantic errors."""
    toml = tmp_path / "pyproject.toml"
    toml.write_text("[tool.lang-fossil.scan]\nworkers = 99\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings(toml_path=toml)
