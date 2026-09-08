"""CLI exit code contract (stable API for CI usage)."""

from __future__ import annotations

EXIT_OK = 0  # scan completed, threshold not exceeded
EXIT_THRESHOLD = 1  # fossil index / fossil gate exceeded
EXIT_CONFIG = 2  # configuration or input error
EXIT_USAGE = 64  # command-line usage error

__all__ = ["EXIT_OK", "EXIT_THRESHOLD", "EXIT_CONFIG", "EXIT_USAGE"]
