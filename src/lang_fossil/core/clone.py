"""基于 winnowing 的代码克隆指纹（P1 差异化能力）.

检测跨文件复制粘贴："同一块化石出现在三个地层"。token 流哈希为
k-gram，经典 winnowing 算法（Schleimer 等，2007）选出带保证的最小
指纹集：任何超过窗口长度的重复都可检出.

状态：实验性的考古信号——跨地层重复的遗留代码，不是通用查重工具；
专业查重属于 PMD-CPD 等工具的领域.
"""

from __future__ import annotations

import hashlib
import re

from lang_fossil.core.models import CloneMatch

_TOKEN_RE = re.compile(r"[A-Za-z_]\w*|\d+(?:\.\d+)?|\"[^\"]*\"|'[^']*'|[^\s\w]")

# 分词前剥离的注释语法（Python + JS 约定）.
_LINE_COMMENT_RE = re.compile(r"#[^\n]*|//[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)

_DEFAULT_K = 8  # k-gram 长度（token 数）
_DEFAULT_W = 4  # winnowing 窗口（哈希数）
_MAX_PAIRS = 200  # 报告上限，保持报告可用
_MIN_CLONE_SITES = 2  # 一个指纹至少出现在 2 处才算克隆


def tokenize(source: str) -> list[tuple[str, int]]:
    """把源码分词为带行号的规范化 token.

    注释与空白因不匹配任何 token 而被隐式丢弃；标识符统一小写.

    Args:
        source: 原始源码文本（任意大括号/缩进语言）.

    Returns:
        ``(token, line)`` 元组列表.
    """
    tokens: list[tuple[str, int]] = []
    line = 1
    last_end = 0
    stripped = _LINE_COMMENT_RE.sub(" ", _BLOCK_COMMENT_RE.sub(" ", source))
    for match in _TOKEN_RE.finditer(stripped):
        value = match.group(0)
        line += stripped.count("\n", last_end, match.start())
        last_end = match.end()
        if re.match(r"[A-Za-z_]", value):
            value = value.lower()
        tokens.append((value, line))
    return tokens


def _kgram_hashes(tokens: list[tuple[str, int]], k: int) -> list[tuple[str, int]]:
    """对每个 k-gram 计算稳定哈希.

    Args:
        tokens: :func:`tokenize` 的 token 流.
        k: k-gram 长度.

    Returns:
        ``(指纹, 首 token 行号)`` 元组列表；token 不足 ``k`` 个返回空.
    """
    if len(tokens) < k:
        return []
    hashes: list[tuple[str, int]] = []
    parts = [value for value, _line in tokens]
    for index in range(len(tokens) - k + 1):
        gram = " ".join(parts[index : index + k])
        digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=8).hexdigest()
        hashes.append((digest, tokens[index][1]))
    return hashes


def _winnow(hashes: list[tuple[str, int]], w: int) -> list[tuple[str, int]]:
    """选出 winnowing 指纹集（每窗口取最右最小值）.

    Args:
        hashes: :func:`_kgram_hashes` 的哈希列表.
        w: 窗口大小.

    Returns:
        选中的 ``(指纹, 行号)`` 列表.
    """
    if not hashes:
        return []
    if len(hashes) <= w:
        return [min(hashes, key=lambda item: (item[0], -item[1]))]
    selected: list[tuple[str, int]] = []
    last_index = -1
    for start in range(len(hashes) - w + 1):
        window = hashes[start : start + w]
        # 最右最小值：保证 winnowing 的间隔性质.
        best_index = start + max(
            i for i, item in enumerate(window) if item[0] == min(x[0] for x in window)
        )
        if best_index != last_index:
            selected.append(hashes[best_index])
            last_index = best_index
    return selected


def detect_clones(
    files: list[tuple[str, str]],
    k: int = _DEFAULT_K,
    w: int = _DEFAULT_W,
) -> list[CloneMatch]:
    """在一组源码文件间检测跨文件克隆.

    Args:
        files: ``(路径, 源码)`` 元组列表.
        k: token 数表示的 k-gram 长度.
        w: winnowing 窗口大小.

    Returns:
        克隆匹配，每个文件对一条，封顶 ``_MAX_PAIRS`` 条.
    """
    fingerprint_index: dict[str, list[tuple[str, int]]] = {}
    for path, source in files:
        tokens = tokenize(source)
        for fingerprint, line in _winnow(_kgram_hashes(tokens, k), w):
            fingerprint_index.setdefault(fingerprint, []).append((path, line))

    matches: list[CloneMatch] = []
    seen: set[tuple[str, int, str, int]] = set()
    for fingerprint, locations in fingerprint_index.items():
        if len(locations) < _MIN_CLONE_SITES:
            continue
        for i, (path_a, line_a) in enumerate(locations):
            for path_b, line_b in locations[i + 1 :]:
                if path_a == path_b and line_a == line_b:
                    continue
                pair = (path_a, line_a, path_b, line_b)
                mirror = (path_b, line_b, path_a, line_a)
                if pair in seen or mirror in seen:
                    continue
                seen.add(pair)
                matches.append(
                    CloneMatch(
                        path_a=path_a,
                        line_a=line_a,
                        path_b=path_b,
                        line_b=line_b,
                        fingerprint=fingerprint,
                        token_count=k,
                    )
                )

    # 同一段重复代码会产生多个共享指纹（winnowing 每窗口选一个），
    # 折叠为每个文件对最早的锚点一条.
    # ponytail: 文件对粒度；同一文件对的第二段独立重复会被漏报，
    # 出现真实需求再升级.
    earliest: dict[frozenset[str], CloneMatch] = {}
    for match in matches:
        key = frozenset((match.path_a, match.path_b))
        current = earliest.get(key)
        if current is None or (match.line_a, match.line_b) < (current.line_a, current.line_b):
            earliest[key] = match
    ordered = sorted(earliest.values(), key=lambda m: (m.path_a, m.line_a))
    return ordered[:_MAX_PAIRS]
