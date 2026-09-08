"""只读 git 子进程封装（可选富化模块）.

安全姿态（规范 2.3 节）：git 只读调用、参数始终以列表传递
（``shell=False``）、动词白名单。红线：白名单约束的是动词，参数也必须
来自代码常量——扩展调用前须确认不含 ``--output=`` 之类的写盘参数.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_READ_ONLY_VERBS = frozenset({"log", "blame", "rev-parse", "show", "status", "diff"})
_DEFAULT_TIMEOUT = 10.0  # 子进程超时（秒）


class GitServiceError(Exception):
    """git 不可用或只读查询被拒时抛出."""


def run_git(
    args: list[str],
    cwd: Path | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> subprocess.CompletedProcess[str] | None:
    """执行只读 git 命令.

    Args:
        args: git 参数；首元素必须是白名单动词.
        cwd: 命令工作目录.
        timeout: 超时后终止子进程.

    Returns:
        已完成的进程；git 未安装时返回 ``None``.

    Raises:
        GitServiceError: 动词不在白名单或 git 超时.
    """
    if not args or args[0] not in _READ_ONLY_VERBS:
        raise GitServiceError(f"git verb not allowed: {args[:1]!r}")
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            shell=False,  # noqa: S603 - 参数列表传递，绝非 shell 字符串
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired as exc:
        raise GitServiceError(f"git {args[0]} timed out") from exc


def is_repo(cwd: Path) -> bool:
    """检查目录是否位于某个 git 工作树内.

    Args:
        cwd: 探测目录.

    Returns:
        git 报告存在工作树则为 True（git 缺失时也为 False）.
    """
    proc = run_git(["rev-parse", "--is-inside-work-tree"], cwd=cwd)
    return bool(proc and proc.returncode == 0 and proc.stdout.strip() == "true")


def last_commit_year(cwd: Path, relpath: str) -> int | None:
    """获取文件最近一次提交的年份（blame 测年）.

    Args:
        cwd: 仓库根.
        relpath: 仓库相对文件路径.

    Returns:
        提交年份；未知（非仓库、git 缺失或未跟踪文件）时为 ``None``.
    """
    proc = run_git(["log", "-1", "--format=%ad", "--date=format:%Y", "--", relpath], cwd=cwd)
    if proc is None or proc.returncode != 0:
        return None
    year = proc.stdout.strip()
    return int(year) if year.isdigit() else None
