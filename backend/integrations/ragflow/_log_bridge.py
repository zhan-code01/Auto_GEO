# -*- coding: utf-8 -*-
"""ragflow 目录下独立运维脚本（check_status / test_connection / test_integration）的日志桥接。

这些脚本以 ``python xxx.py`` 方式独立运行，不经过主应用的日志体系，
且不应强依赖 backend.config 的环境变量校验。因此这里做一套极简 loguru 配置：

- 控制台输出仍由脚本自身的 print 提供（log_print 保留原行为）；
- 日志文件按日期命名：logs/ragflow_cli_YYYY-MM-DD.log，每天午夜轮转，
  仅保留最近 3 天（loguru retention 自动清理）；
- logger 只写文件、不写控制台，避免与 print 双份重复显示。
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

from loguru import logger

_LOG_DIR = Path(__file__).resolve().parent / "logs"
_initialized = False


def _reconfigure_stdio_utf8() -> None:
    """把 stdout/stderr 重配成 UTF-8（Windows GBK 控制台下 ✓/✗ 等字符不乱码、不抛错）。

    与主应用 log_setup 的逻辑一致但独立实现，避免本目录脚本强依赖 backend.config。
    """
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name)
        encoding = (getattr(stream, "encoding", "") or "").lower().replace("-", "").replace("_", "")
        if getattr(stream, "buffer", None) and encoding != "utf8":
            setattr(
                sys,
                stream_name,
                io.TextIOWrapper(stream.buffer, encoding="utf-8", errors="replace"),
            )


def _ensure_init() -> None:
    """挂载文件 sink（幂等）。"""
    global _initialized
    if _initialized:
        return
    _reconfigure_stdio_utf8()
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        logger.remove()  # 移除 loguru 默认 stderr sink（控制台由 print 负责）
        logger.add(
            str(_LOG_DIR / "ragflow_cli_{time:YYYY-MM-DD}.log"),
            level="DEBUG",
            rotation="00:00",      # 每天午夜轮转
            retention="3 days",    # 仅保留最近 3 天
            encoding="utf-8",
            enqueue=False,         # 短命 CLI 脚本同步写入即可
            backtrace=True,
            diagnose=False,
            catch=True,
        )
    except Exception:
        pass  # 日志文件挂载失败不影响脚本本身运行
    _initialized = True


def log_print(*args, sep: str = " ") -> None:
    """控制台 print + 文件日志双写。

    兼容 print 的全部单/多参数形态；空消息（print()）只输出空行、不写日志。
    """
    _ensure_init()
    message = sep.join(str(arg) for arg in args)
    print(*args, sep=sep, flush=True)
    if message:
        logger.info(message)
