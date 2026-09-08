"""Enrichment stage: optional git-based "carbon dating" of fossils.

Default-off (review verdict: blame dating is unreliable and opt-in). When
enabled, files are dated by their last commit year, which stratigraphy can
use to annotate eras.
"""

from __future__ import annotations

from pathlib import Path

from lang_fossil.config import LangFossilSettings
from lang_fossil.infra import git_service


def enrich_commit_years(
    root: Path, paths: list[str], settings: LangFossilSettings
) -> dict[str, int | None]:
    """Date files by their last commit year via read-only git commands.

    Args:
        root: Scan root (expected to be the repository root).
        paths: Repository-relative file paths.
        settings: Active settings; when ``settings.git.enabled`` is False
            the call is a no-op.

    Returns:
        Mapping path -> last commit year (or ``None``); empty when the
        enrichment is disabled or the directory is not a git repository.
    """
    if not settings.git.enabled or not paths:
        return {}
    if not git_service.is_repo(root):
        return {}

    years: dict[str, int | None] = {}
    for relpath in paths[: settings.git.blame_batch]:
        years[relpath] = git_service.last_commit_year(root, relpath)
    return years
