"""Unified configuration for lang-fossil.

All configuration reads converge here (single exit point); business modules
only receive an injected :class:`LangFossilSettings` instance.

Precedence (high to low): CLI args > environment variables > TOML
``[tool.lang-fossil]`` section > model defaults.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, Union, get_args, get_origin

try:  # PEP 604 unions (``X | None``) exist at runtime only on Python >= 3.10
    from types import UnionType as _PEP604Union
except ImportError:  # pragma: no cover - Python < 3.10
    _PEP604Union = ()  # type: ignore[assignment,misc]

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_EXCLUDES = [
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    "vendor_internal_marked",
]


class CacheSettings(BaseModel):
    """Cache subsystem parameters."""

    enabled: bool = True
    path: Path = Path(".lang-fossil/cache.db")
    timeout_seconds: float = Field(
        default=5.0, gt=0, description="Per-file parse circuit-breaker threshold"
    )


class AmbiguousHeaderSettings(BaseModel):
    """Policy for resolving the ambiguous C/C++ ``.h`` extension.

    ``.h`` is shared by C and C++; no content scoring is performed. The user
    decides explicitly: ``mode`` applies everywhere unless a matching glob in
    ``overrides`` (matched against the repository-relative path) wins. In
    ``auto`` mode the sibling directory is consulted: the family with more
    ``.c``/``.cpp``(.cc/.cxx) sources wins, defaulting to ``c`` when the
    directory has no C-family sources.
    """

    mode: Literal["auto", "c", "cpp"] = "auto"
    overrides: dict[str, Literal["c", "cpp"]] = Field(default_factory=dict)


class ScanSettings(BaseModel):
    """Scan pipeline parameters."""

    workers: int = Field(default=0, ge=0, le=16, description="0 = min(CPU, 8)")
    exclude: list[str] = Field(default_factory=lambda: list(_DEFAULT_EXCLUDES))
    parse_timeout: float = 5.0
    sample_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    ambiguous_headers: AmbiguousHeaderSettings = Field(default_factory=AmbiguousHeaderSettings)


class GitSettings(BaseModel):
    """Enrichment via git (optional module; see PRD FR-5)."""

    enabled: bool = False  # review verdict: carbon dating is opt-in
    blame_batch: int = 200
    treat_squash_as_unreliable: bool = True


class LangFossilSettings(BaseSettings):
    """Root settings.

    Precedence: CLI args > env vars > TOML > defaults. Environment variables
    use the ``LANG_FOSSIL_`` prefix with ``__`` as the nested delimiter, e.g.
    ``LANG_FOSSIL_SCAN__WORKERS=8``.
    """

    model_config = SettingsConfigDict(
        env_prefix="LANG_FOSSIL_",
        env_nested_delimiter="__",
        extra="forbid",
    )

    cache: CacheSettings = CacheSettings()
    scan: ScanSettings = ScanSettings()
    git: GitSettings = GitSettings()
    max_fossil_index: float | None = Field(default=None, ge=0)  # CI gate threshold

    @field_validator("max_fossil_index")
    @classmethod
    def _guard_threshold(cls, v: float | None) -> float | None:
        """Reject negative thresholds early with a readable message."""
        if v is not None and v < 0:
            raise ValueError("--max-fi must be >= 0")
        return v


class ConfigError(Exception):
    """Raised when configuration cannot be loaded or validated."""


def read_tool_section(toml_path: Path) -> dict[str, Any]:
    """Read the ``[tool.lang-fossil]`` table from a TOML file.

    Namespace isolation: only the ``tool.lang-fossil`` table is extracted.
    Other ``[tool.*]`` sections in the user's file (``[tool.black]``, ...)
    never enter the pydantic model, so ``extra="forbid"`` is not affected by
    them.

    Args:
        toml_path: Path to the TOML file (typically ``pyproject.toml``).

    Returns:
        The parsed ``[tool.lang-fossil]`` table, or an empty dict when the
        file is missing or has no such section (graceful degradation).

    Raises:
        ConfigError: If the file exists but is not valid TOML.
    """
    try:
        content = toml_path.read_text(encoding="utf-8")
    except OSError:
        return {}

    parsed = _parse_toml(content, toml_path)
    tool_table = parsed.get("tool")
    if not isinstance(tool_table, dict):
        return {}
    section = tool_table.get("lang-fossil")
    return dict(section) if isinstance(section, dict) else {}


def _parse_toml(content: str, toml_path: Path) -> dict[str, Any]:
    """Parse TOML content using the best parser available.

    Args:
        content: Raw TOML text.
        toml_path: Path used only for error messages.

    Returns:
        The parsed TOML document.

    Raises:
        ConfigError: If the content is invalid TOML.
    """
    try:  # Python 3.11+
        import tomllib
    except ImportError:
        try:  # optional backport, not a hard dependency
            import tomli as tomllib
        except ImportError:
            # No TOML parser on this interpreter: degrade to defaults.
            return {}

    try:
        parsed: dict[str, Any] = tomllib.loads(content)
    except Exception as exc:  # noqa: BLE001 - tomllib raises ValueError subclasses
        raise ConfigError(f"Invalid TOML in {toml_path}: {exc}") from exc
    return parsed


def load_settings(
    cli_overrides: dict[str, Any] | None = None,
    toml_path: Path | None = None,
) -> LangFossilSettings:
    """Load settings from TOML, environment, and CLI overrides.

    Values are merged explicitly in precedence order (CLI > env > TOML >
    defaults) before a single pydantic validation pass.

    Args:
        cli_overrides: Explicit CLI arguments; win over everything.
        toml_path: Path to a config file with a ``[tool.lang-fossil]``
            section; defaults to ``pyproject.toml`` in the working directory.

    Returns:
        A fully validated settings object.

    Raises:
        ConfigError: On unknown keys or out-of-range values.
    """
    toml_conf = read_tool_section(toml_path or Path("pyproject.toml"))
    env_conf = _env_overrides()
    merged: dict[str, Any] = {}
    _deep_merge(merged, toml_conf)
    _deep_merge(merged, env_conf)
    _deep_merge(merged, cli_overrides or {})
    try:
        return LangFossilSettings(**merged)
    except Exception as exc:
        raise ConfigError(f"Invalid lang-fossil configuration: {exc}") from exc


_ENV_PREFIX = "LANG_FOSSIL_"
_TRUE_VALUES = {"1", "true", "yes", "on"}


def _env_overrides() -> dict[str, Any]:
    """Collect ``LANG_FOSSIL_*`` environment overrides as nested dicts.

    Only scalar fields are honored (bool/int/float/str); keys follow the
    ``LANG_FOSSIL_SECTION__FIELD`` double-underscore nesting convention.

    Returns:
        A nested dict suitable for deep-merging into the model kwargs.
    """
    overrides: dict[str, Any] = {}

    def _walk(model: type[BaseModel], path: list[str]) -> None:
        """Walk model fields recursively, collecting scalar env values."""
        for name, field_info in model.model_fields.items():
            annotation = field_info.annotation
            env_key = _ENV_PREFIX + "__".join([*path, name]).upper()
            raw = os.environ.get(env_key)
            if raw is not None:
                try:
                    coerced = _coerce(raw, annotation)
                except ValueError as exc:
                    raise ConfigError(f"{env_key}: {exc}") from exc
                if coerced is not None:
                    _set_nested(overrides, [*path, name], coerced)
            nested = _nested_model(annotation)
            if nested is not None:
                _walk(nested, [*path, name])

    _walk(LangFossilSettings, [])
    return overrides


def _set_nested(target: dict[str, Any], path: list[str], value: Any) -> None:
    """Set a value at a nested path, creating intermediate dicts.

    Args:
        target: Dict mutated in place.
        path: Field path segments (e.g. ``["scan", "workers"]``).
        value: The coerced value.
    """
    node = target
    for segment in path[:-1]:
        node = node.setdefault(segment, {})
    node[path[-1]] = value


def _nested_model(annotation: Any) -> type[BaseModel] | None:
    """Return the nested BaseModel type if the annotation is one.

    Args:
        annotation: A field annotation.

    Returns:
        The BaseModel subclass, or None for scalars/optionals.
    """
    origin = get_origin(annotation)
    target = origin if origin is not None else annotation
    if isinstance(target, type) and issubclass(target, BaseModel):
        return target
    return None


def _to_bool(raw: str) -> bool:
    """Interpret truthy env strings (1/true/yes/on)."""
    return raw.strip().lower() in _TRUE_VALUES


def _to_int(raw: str) -> int:
    """Parse an int env value.

    Args:
        raw: Raw environment value.

    Returns:
        The parsed integer.

    Raises:
        ValueError: When ``raw`` is not an integer.
    """
    return int(raw)


def _to_float(raw: str) -> float:
    """Parse a float env value.

    Args:
        raw: Raw environment value.

    Returns:
        The parsed float.

    Raises:
        ValueError: When ``raw`` is not a number.
    """
    return float(raw)


_CONVERTERS: dict[type, Callable[[str], Any]] = {
    bool: _to_bool,
    int: _to_int,
    float: _to_float,
    str: lambda raw: raw,
}


def _coerce(raw: str, annotation: Any) -> Any:
    """Coerce an env string to the annotated scalar type.

    Optional/Union annotations are unwrapped to their scalar member so e.g.
    ``LANG_FOSSIL_MAX_FOSSIL_INDEX`` (a ``float | None`` field) works.
    Converter failures propagate as :class:`ValueError` so the caller can turn
    them into a loud ``ConfigError`` instead of silently ignoring the value.

    Args:
        raw: Raw environment value.
        annotation: Target annotation.

    Returns:
        The coerced value, or None when the type is unsupported (e.g. a list).

    Raises:
        ValueError: When the raw value cannot be parsed for a scalar type.
    """
    base = get_origin(annotation) or annotation
    converter = _CONVERTERS.get(base)
    if converter is not None:
        return converter(raw)
    if base in (Union, _PEP604Union):  # Optional[T] / T | None
        for member in get_args(annotation):
            if member is type(None):
                continue
            member_converter = _CONVERTERS.get(member)
            if member_converter is not None:
                return member_converter(raw)
    return None


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> None:
    """Recursively merge ``override`` into ``base`` (nested dicts unite).

    Args:
        base: Target dict mutated in place.
        override: Values that win on conflict.
    """
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
