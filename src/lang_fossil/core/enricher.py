"""可选的 git 富化阶段：为化石做"碳定年".

默认关闭（评审结论：blame 测年不可靠，仅作可选项）。启用后按文件
最近提交年定年，供地层聚合标注年代维度使用.
"""

from __future__ import annotations

from pathlib import Path

from lang_fossil.config import LangFossilSettings
from lang_fossil.infra import git_service


def enrich_commit_years(
    root: Path, paths: list[str], settings: LangFossilSettings
) -> dict[str, int | None]:
    """通过只读 git 命令按最近提交年为文件定年.

    Args:
        root: 扫描根目录（应即仓库根）.
        paths: 仓库相对路径列表.
        settings: 当前设置；``settings.git.enabled`` 为 False 时直接空转.

    Returns:
        path -> 最近提交年（未知为 ``None``）；富化关闭或目录非 git 仓库
        时返回空映射.
    """
    if not settings.git.enabled or not paths:
        return {}
    if not git_service.is_repo(root):
        return {}

    years: dict[str, int | None] = {}
    for relpath in paths[: settings.git.blame_batch]:
        years[relpath] = git_service.last_commit_year(root, relpath)
    return years
