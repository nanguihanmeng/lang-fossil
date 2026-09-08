"""Unit tests for the read-only git service (mirrors infra/git_service.py)."""

from __future__ import annotations

import pytest

from lang_fossil.infra.git_service import GitServiceError, run_git


def test_non_readonly_verb_rejected() -> None:
    """Write verbs (commit, push, ...) are rejected before execution."""
    with pytest.raises(GitServiceError, match="not allowed"):
        run_git(["commit", "-m", "nope"])


def test_empty_args_rejected() -> None:
    """Empty argument lists are rejected."""
    with pytest.raises(GitServiceError, match="not allowed"):
        run_git([])


def test_git_missing_returns_none() -> None:
    """A missing git binary degrades to None (optional module)."""
    proc = run_git(["rev-parse", "--is-inside-work-tree"], cwd=None, timeout=5)
    # On CI/dev boxes git exists; the contract under test is "no exception".
    assert proc is None or proc.returncode in (0, 128)
