"""CLI 退出码契约（供 CI 使用的稳定接口）."""

from __future__ import annotations

EXIT_OK = 0  # 扫描完成，未超阈值
EXIT_THRESHOLD = 1  # 超出 fossil index / 化石数量门禁
EXIT_CONFIG = 2  # 配置或输入错误
EXIT_USAGE = 64  # 命令行用法错误

__all__ = ["EXIT_OK", "EXIT_THRESHOLD", "EXIT_CONFIG", "EXIT_USAGE"]
