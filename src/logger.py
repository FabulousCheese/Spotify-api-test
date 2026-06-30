"""
统一日志配置 — 控制台 + 文件双输出，替换所有 print()。
"""

import logging
import sys
from pathlib import Path

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%H:%M:%S"

_initialized: bool = False


def setup_logging(log_dir: str = "reports", verbose: bool = False) -> None:
    """初始化全局日志：控制台彩色 + 文件持久化。"""
    global _initialized
    if _initialized:
        return

    root = logging.getLogger()
    level = logging.DEBUG if verbose else logging.INFO
    root.setLevel(level)

    # 控制台 handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(logging.Formatter(_LOG_FORMAT, _DATE_FORMAT))
    root.addHandler(console)

    # 文件 handler
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(
        str(Path(log_dir) / "pipeline.log"), encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))
    root.addHandler(file_handler)

    _initialized = True


def get_logger(name: str) -> logging.Logger:
    """获取具名 logger，确保日志系统已初始化。"""
    if not _initialized:
        setup_logging()
    return logging.getLogger(name)
