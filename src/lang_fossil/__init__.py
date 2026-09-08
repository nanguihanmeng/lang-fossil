"""lang-fossil: archaeology for codebases."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

__all__ = ["__version__"]


def _resolve_version() -> str:
    """Resolve the package version from installed metadata.

    Returns:
        The installed version string, or ``"0.0.0.dev0"`` when the package
        is used from a source checkout without installation.
    """
    try:
        return version("lang-fossil")
    except PackageNotFoundError:
        return "0.0.0.dev0"


__version__ = _resolve_version()
