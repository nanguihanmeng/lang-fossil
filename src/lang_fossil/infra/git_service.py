"""Read-only git subprocess wrapper (optional enrichment module).

Security posture (spec section 2.3): git is invoked read-only, arguments are
always passed as a list (``shell=False``), and only whitelisted verbs are
accepted.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_READ_ONLY_VERBS = frozenset({"log", "blame", "rev-parse", "show", "status", "diff"})
_DEFAULT_TIMEOUT = 10.0


class GitServiceError(Exception):
    """Raised when git is unavailable or refuses a read-only query."""


def run_git(
    args: list[str],
    cwd: Path | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> subprocess.CompletedProcess[str] | None:
    """Run a read-only git command.

    Args:
        args: Git arguments; the first element must be a whitelisted verb.
        cwd: Working directory for the command.
        timeout: Kill the subprocess after this many seconds.

    Returns:
        The completed process, or ``None`` when git is not installed.

    Raises:
        GitServiceError: If the verb is not whitelisted or git times out.
    """
    if not args or args[0] not in _READ_ONLY_VERBS:
        raise GitServiceError(f"git verb not allowed: {args[:1]!r}")
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            shell=False,  # noqa: S603 - arguments are list-passed, never a shell string
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired as exc:
        raise GitServiceError(f"git {args[0]} timed out") from exc


def is_repo(cwd: Path) -> bool:
    """Check whether a directory is inside a git work tree.

    Args:
        cwd: Directory to probe.

    Returns:
        True if git reports a work tree (also False when git is missing).
    """
    proc = run_git(["rev-parse", "--is-inside-work-tree"], cwd=cwd)
    return bool(proc and proc.returncode == 0 and proc.stdout.strip() == "true")


def last_commit_year(cwd: Path, relpath: str) -> int | None:
    """Get the year of the last commit touching a file (blame dating).

    Args:
        cwd: Repository root.
        relpath: Repository-relative file path.

    Returns:
        The commit year, or ``None`` when unknown (not a repo, git missing,
        or untracked file).
    """
    proc = run_git(["log", "-1", "--format=%ad", "--date=format:%Y", "--", relpath], cwd=cwd)
    if proc is None or proc.returncode != 0:
        return None
    year = proc.stdout.strip()
    return int(year) if year.isdigit() else None
