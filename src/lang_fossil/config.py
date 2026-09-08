"""lang-fossil 的统一配置.

所有配置读取收敛于此（唯一出口）；业务模块只接收注入的
:class:`LangFossilSettings` 实例.

优先级（高到低）：CLI 参数 > 环境变量 > TOML ``[tool.lang-fossil]`` 节 >
模型默认值.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, Union, get_args, get_origin

try:  # PEP 604 联合类型（``X | None``）仅在 Python >= 3.10 运行时存在
    from types import UnionType as _PEP604Union
except ImportError:  # pragma: no cover - Python < 3.10
    _PEP604Union = ()  # type: ignore[assignment,misc]

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 默认排除目录.
_DEFAULT_EXCLUDES = [
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    "vendor_internal_marked",
]


class CacheSettings(BaseModel):
    """缓存子系统参数."""

    enabled: bool = True
    path: Path = Path(".lang-fossil/cache.db")
    timeout_seconds: float = Field(default=5.0, gt=0, description="单文件解析熔断阈值")


class AmbiguousHeaderSettings(BaseModel):
    """C/C++ 共用 ``.h`` 扩展名的判定策略.

    不做内容评分，由用户显式决定：``mode`` 全局生效，``overrides`` 中
    匹配（按仓库相对路径）的 glob 优先。``auto`` 模式参考同级目录：谁的
    ``.c``/``.cpp``(.cc/.cxx) 源文件多就判谁；目录内无 C 家族源文件时
    默认 ``c``.
    """

    mode: Literal["auto", "c", "cpp"] = "auto"
    overrides: dict[str, Literal["c", "cpp"]] = Field(default_factory=dict)


class ScanSettings(BaseModel):
    """扫描管线参数."""

    workers: int = Field(default=0, ge=0, le=16, description="0 = min(CPU, 8)")
    exclude: list[str] = Field(default_factory=lambda: list(_DEFAULT_EXCLUDES))
    parse_timeout: float = 5.0
    sample_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    ambiguous_headers: AmbiguousHeaderSettings = Field(default_factory=AmbiguousHeaderSettings)


class GitSettings(BaseModel):
    """通过 git 做富化（可选模块；见 PRD FR-5）."""

    enabled: bool = False  # 评审结论：碳定年默认关闭
    blame_batch: int = 200
    treat_squash_as_unreliable: bool = True


class LangFossilSettings(BaseSettings):
    """根设置.

    优先级：CLI > 环境变量 > TOML > 默认值。环境变量使用 ``LANG_FOSSIL_``
    前缀，``__`` 作为嵌套分隔符，例如 ``LANG_FOSSIL_SCAN__WORKERS=8``.
    """

    model_config = SettingsConfigDict(
        env_prefix="LANG_FOSSIL_",
        env_nested_delimiter="__",
        extra="forbid",
    )

    cache: CacheSettings = CacheSettings()
    scan: ScanSettings = ScanSettings()
    git: GitSettings = GitSettings()
    max_fossil_index: float | None = Field(default=None, ge=0)  # CI 门禁阈值

    @field_validator("max_fossil_index")
    @classmethod
    def _guard_threshold(cls, v: float | None) -> float | None:
        """提前拒绝负阈值并给出可读报错."""
        if v is not None and v < 0:
            raise ValueError("--max-fi must be >= 0")
        return v


class ConfigError(Exception):
    """配置无法加载或校验失败时抛出."""


def read_tool_section(toml_path: Path) -> dict[str, Any]:
    """读取 TOML 文件中的 ``[tool.lang-fossil]`` 表.

    命名空间隔离：只提取 ``tool.lang-fossil`` 表。用户文件中其余
    ``[tool.*]`` 节（``[tool.black]`` 等）不进入 pydantic 模型，
    因此不会触碰 ``extra="forbid"``.

    Args:
        toml_path: TOML 文件路径（通常是 ``pyproject.toml``）.

    Returns:
        解析出的 ``[tool.lang-fossil]`` 表；文件缺失或无该节时返回
        空字典（优雅降级）.

    Raises:
        ConfigError: 文件存在但不是合法 TOML.
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
    """使用当前解释器可用的最佳解析器解析 TOML.

    Args:
        content: TOML 原文.
        toml_path: 仅用于报错的文件路径.

    Returns:
        解析后的 TOML 文档.

    Raises:
        ConfigError: TOML 非法.
    """
    try:  # Python 3.11+
        import tomllib
    except ImportError:
        try:  # 可选 backport，非硬依赖
            import tomli as tomllib
        except ImportError:
            # 解释器上没有 TOML 解析器：降级为默认值.
            return {}

    try:
        parsed: dict[str, Any] = tomllib.loads(content)
    except Exception as exc:  # noqa: BLE001 - tomllib 抛 ValueError 子类
        raise ConfigError(f"Invalid TOML in {toml_path}: {exc}") from exc
    return parsed


def load_settings(
    cli_overrides: dict[str, Any] | None = None,
    toml_path: Path | None = None,
) -> LangFossilSettings:
    """从 TOML、环境变量与 CLI 覆盖加载设置.

    按优先级显式合并（CLI > 环境变量 > TOML > 默认值）后做单次 pydantic
    校验.

    Args:
        cli_overrides: 显式 CLI 参数；优先于一切.
        toml_path: 含 ``[tool.lang-fossil]`` 节的配置文件路径；默认为
            工作目录下的 ``pyproject.toml``.

    Returns:
        完成校验的设置对象.

    Raises:
        ConfigError: 出现未知键或越界值.
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
    """收集 ``LANG_FOSSIL_*`` 环境变量覆盖，组织为嵌套字典.

    仅接受标量字段（bool/int/float/str）；键遵循
    ``LANG_FOSSIL_SECTION__FIELD`` 双下划线嵌套约定.

    Returns:
        适合深合并进模型 kwargs 的嵌套字典.
    """
    overrides: dict[str, Any] = {}

    def _walk(model: type[BaseModel], path: list[str]) -> None:
        """递归遍历模型字段，收集标量环境变量值."""
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
    """在嵌套路径上设值，必要时创建中间字典.

    Args:
        target: 原地修改的目标字典.
        path: 字段路径段（如 ``["scan", "workers"]``）.
        value: 强转后的值.
    """
    node = target
    for segment in path[:-1]:
        node = node.setdefault(segment, {})
    node[path[-1]] = value


def _nested_model(annotation: Any) -> type[BaseModel] | None:
    """若注解是嵌套 BaseModel 则返回其类型.

    Args:
        annotation: 字段注解.

    Returns:
        BaseModel 子类；标量/可选类型返回 None.
    """
    origin = get_origin(annotation)
    target = origin if origin is not None else annotation
    if isinstance(target, type) and issubclass(target, BaseModel):
        return target
    return None


def _to_bool(raw: str) -> bool:
    """解释真值环境变量字符串（1/true/yes/on）."""
    return raw.strip().lower() in _TRUE_VALUES


def _to_int(raw: str) -> int:
    """解析整数环境变量.

    Args:
        raw: 原始环境变量值.

    Returns:
        解析出的整数.

    Raises:
        ValueError: ``raw`` 不是整数.
    """
    return int(raw)


def _to_float(raw: str) -> float:
    """解析浮点环境变量.

    Args:
        raw: 原始环境变量值.

    Returns:
        解析出的浮点数.

    Raises:
        ValueError: ``raw`` 不是数字.
    """
    return float(raw)


_CONVERTERS: dict[type, Callable[[str], Any]] = {
    bool: _to_bool,
    int: _to_int,
    float: _to_float,
    str: lambda raw: raw,
}


def _coerce(raw: str, annotation: Any) -> Any:
    """把环境变量字符串强转为注解标量类型.

    Optional/Union 注解会解包到其标量成员，使 ``LANG_FOSSIL_MAX_FOSSIL_INDEX``
    （``float | None`` 字段）生效。强转失败以 :class:`ValueError` 传播，
    由调用方转为显式 ``ConfigError`` 而非静默忽略.

    Args:
        raw: 原始环境变量值.
        annotation: 目标注解.

    Returns:
        强转后的值；类型不支持（如 list）时返回 None.

    Raises:
        ValueError: 标量类型解析失败.
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
    """递归把 ``override`` 合并进 ``base``（嵌套字典取并集）.

    Args:
        base: 原地修改的目标字典.
        override: 冲突时胜出的值.
    """
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
