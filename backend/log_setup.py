# -*- coding: utf-8 -*-
"""
集中式日志配置（loguru）—— 全项目唯一日志初始化入口。

``setup_logging()`` 在进程启动早期调用一次即可，负责：

1. 重配 stdout/stderr 为 UTF-8（Windows GBK 环境下中文/emoji 不乱码，
   且 Playwright 子进程依赖此编码；CLAUDE.md 明确要求不可去除该行为）。
2. 挂载三个核心 sink：
   - 控制台 stdout（彩色，LOG_LEVEL，默认 INFO）
   - 主日志文件  logs/auto_geo_YYYY-MM-DD.log        （LOG_FILE_LEVEL，默认 DEBUG，全面留底）
   - 错误日志文件 logs/auto_geo_error_YYYY-MM-DD.log （LOG_ERROR_LEVEL，默认 WARNING，快速排障）
3. 按天滚动 + 自动清理：
   - 文件名带日期后缀，每天午夜（00:00）loguru 自动轮转新开一个文件；
   - ``retention`` 设为 3 天：轮转时自动删除超过保留期的旧文件；
   - 启动时额外执行一次 ``cleanup_old_log_files()`` 全目录清扫（按修改时间兜底），
     确保「只保存最近 3 天日志」在任何重启/异常场景下都成立。
4. 文件 sink 默认 ``enqueue=True``（异步线程写入，不阻塞事件循环；受限环境自动回退同步）、
   UTF-8 编码、异常回溯完整（backtrace=True，diagnose=False 避免展开变量值）。
5. 标准库 ``logging`` 桥接：uvicorn / sqlalchemy / httpx / playwright / apscheduler 等
   第三方库的日志统一汇入 loguru（避免「有些日志进不了文件」的缺口）。
6. 请求上下文：通过 ``logger.configure(patcher=...)`` 为每条日志自动附带
   ``request_id`` / ``user``（默认 "-"），文件日志可按请求串联排查。
7. 兜底捕获未处理异常：``sys.excepthook`` / ``threading.excepthook``。

WebSocket 实时监控 sink 不在此处硬编码（它依赖 ws_manager），
由 main.py 通过 ``socket_sink`` 参数传入。

供管理后台使用的辅助函数（按日期命名的文件解析/读取/清空）：
``resolve_today_log_path`` / ``read_log_lines`` / ``clear_log_files``。
"""

from __future__ import annotations

import contextvars
import io
import logging
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from loguru import logger

from backend.config import (
    LOG_DIR,
    LOG_FILE,
    ERROR_LOG_FILE,
    WORKER_LOG_FILE,
    WORKER_ERROR_LOG_FILE,
    LOG_ROTATION,
    LOG_RETENTION,
    LOG_ERROR_RETENTION,
    LOG_RETENTION_DAYS,
    LOG_LEVEL,
    LOG_FILE_LEVEL,
    LOG_ERROR_LEVEL,
    LOG_STDLIB_BRIDGE_LEVEL,
)

# 控制台彩色格式：时间 | 级别 | 模块:函数:行 - 消息
_CONSOLE_FORMAT = (
    "<green>{time:HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)

# 文件格式：完整日期 + 请求上下文 + 线程名 + 模块:函数:行，异常附加完整 traceback
_FILE_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
    "req={extra[request_id]} | user={extra[user]} | "
    "{thread.name} | {name}:{function}:{line} - {message}\n{exception}"
)

# ==================== 请求上下文（contextvars，供 patcher 自动附带） ====================
current_request_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "log_request_id", default=None
)
current_user: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "log_user", default=None
)


def _patch_extra(record: dict) -> None:
    """为每条日志补齐 request_id / user 字段（未绑定上下文时显示 "-"）。"""
    extra = record["extra"]
    if not extra.get("request_id"):
        extra["request_id"] = current_request_id.get() or "-"
    if not extra.get("user"):
        extra["user"] = current_user.get() or "-"


# ==================== 标准库 logging -> loguru 桥接 ====================


class _InterceptHandler(logging.Handler):
    """把 stdlib logging 记录转发给 loguru，自动携带原始调用位置与异常信息。"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # 向上找调用帧，避免日志位置显示成本文件
        frame: Optional[object] = logging.currentframe()
        depth = 2
        while frame is not None and frame.f_code.co_filename == logging.__file__:  # type: ignore[union-attr]
            frame = frame.f_back  # type: ignore[union-attr]
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


_bridge_installed = False


def _install_stdlib_bridge() -> None:
    """将标准库 logging 的 root handler 替换为 loguru 桥接（幂等）。"""
    global _bridge_installed
    if _bridge_installed:
        return
    _bridge_installed = True
    reinstall_stdlib_bridge()


def reinstall_stdlib_bridge() -> None:
    """重新确保 root logging 只有 loguru 桥接 handler。

    部分库（如 ragflow_integration）在 import 时调用 ``logging.basicConfig()``，
    会在 root 上追加自己的 StreamHandler，导致同一行日志重复输出。
    在应用 lifespan 启动时（所有导入完成后）再调用一次即可清除这些残留。
    """
    root = logging.getLogger()
    root.handlers = [_InterceptHandler()]
    root.setLevel(LOG_STDLIB_BRIDGE_LEVEL)


# ==================== 未处理异常兜底 ====================


def _handle_uncaught_exception(exc_type, exc_value, exc_tb) -> None:
    logger.opt(exception=(exc_type, exc_value, exc_tb)).critical(
        "未捕获的异常（进程级 excepthook）"
    )


def _install_exception_hooks() -> None:
    sys.excepthook = _handle_uncaught_exception
    if hasattr(threading, "excepthook"):
        threading.excepthook = lambda args: _handle_uncaught_exception(
            args.exc_type, args.exc_value, args.exc_traceback
        )


# ==================== 文件路径解析（按日期命名） ====================


def _resolve_dated_path(pattern: str, when: Optional[datetime] = None) -> Path:
    """把含 {time:YYYY-MM-DD} 占位符的日志路径解析为具体某天的文件路径。"""
    day = (when or datetime.now()).strftime("%Y-%m-%d")
    return Path(pattern.replace("{time:YYYY-MM-DD}", day))


def _glob_pattern_for(pattern: str) -> str:
    """把含日期占位符的文件名转成可 glob 的通配文件名。"""
    return Path(pattern).name.replace("{time:YYYY-MM-DD}", "*")


def resolve_today_log_path(level: Optional[str] = None) -> Path:
    """返回「今天」的日志文件具体路径（供管理后台读取/清空使用）。

    level 为 ERROR/WARNING 时返回错误日志文件，否则返回主日志文件。
    """
    pattern = ERROR_LOG_FILE if (level or "").upper() in {"ERROR", "WARNING", "WARN"} else LOG_FILE
    return _resolve_dated_path(pattern)


def list_log_files(level: Optional[str] = None) -> list[Path]:
    """列出日志目录下全部日志文件（按名称倒序，新的在前）。"""
    try:
        pattern = (
            ERROR_LOG_FILE if (level or "").upper() in {"ERROR", "WARNING", "WARN"} else LOG_FILE
        )
        files = sorted(LOG_DIR.glob(_glob_pattern_for(pattern)), reverse=True)
        return [f for f in files if f.is_file()]
    except Exception:
        return []


def cleanup_old_log_files(keep_days: Optional[int] = None) -> int:
    """按文件修改时间清扫日志目录，删除超过保留期的旧日志文件（兜底保障）。

    返回值：删除的文件数量。异常一律吞掉 —— 清理失败不应影响业务。
    """
    days = int(keep_days or LOG_RETENTION_DAYS)
    if days <= 0:
        return 0
    cutoff = time.time() - days * 86400
    removed = 0
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        for path in LOG_DIR.glob("*.log*"):
            try:
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            except OSError:
                continue
    except Exception:
        return removed
    if removed:
        logger.debug(f"日志清理：已删除 {removed} 个超过 {days} 天的旧日志文件")
    return removed


# ==================== 文件 sink 挂载（可动态重建） ====================

_file_handler_ids: list[int] = []
_last_file_args: dict = {}


def _enqueue_available() -> bool:
    """探测 loguru ``enqueue=True`` 依赖的 multiprocessing 队列是否可用。

    队列基于命名管道实现；在无管道权限的受限环境（如沙箱）下创建会抛
    PermissionError。必须预先探测：若直接让 ``logger.add(enqueue=True)``
    失败，loguru 不会关闭已打开的文件句柄（0.7.3 的实现缺陷），
    导致该日志文件在 Windows 上永久被占用、无法清理。
    """
    try:
        import multiprocessing

        queue = multiprocessing.SimpleQueue()
        queue.close()
        return True
    except Exception:
        return False


def _add_file_sink(
    path: str,
    *,
    level: str,
    retention: str,
) -> Optional[int]:
    """挂载一个文件 sink。

    默认 ``enqueue=True``（异步线程写入，不阻塞事件循环）；在无法创建
    multiprocessing 队列的受限环境下回退 ``enqueue=False`` 同步写入，
    确保文件日志在任何环境都不丢失。返回 handler id，失败返回 None。
    """
    use_enqueue = _enqueue_available()
    if not use_enqueue:
        logger.debug(f"受限环境：multiprocessing 队列不可用，文件日志改用同步写入 ({path})")
    try:
        return logger.add(
            path,
            level=level,
            format=_FILE_FORMAT,
            rotation=LOG_ROTATION,   # "00:00" 每天午夜轮转
            retention=retention,     # 仅保留最近 3 天
            encoding="utf-8",
            enqueue=use_enqueue,
            backtrace=True,          # 异常完整回溯
            diagnose=False,          # 不展开变量值（安全 + 体积）
            catch=True,              # sink 自身异常不致进程崩溃
        )
    except Exception as exc:
        logger.warning(f"文件 sink 挂载失败 ({path}): {exc}")
        return None


def _mount_file_sinks(log_file: str, error_file: str) -> None:
    """挂载主日志 + 错误日志两个文件 sink，并登记 handler id（供重建/清空）。"""
    _file_handler_ids.clear()

    hid = _add_file_sink(log_file, level=LOG_FILE_LEVEL, retention=LOG_RETENTION)
    if hid is not None:
        _file_handler_ids.append(hid)

    hid = _add_file_sink(error_file, level=LOG_ERROR_LEVEL, retention=LOG_ERROR_RETENTION)
    if hid is not None:
        _file_handler_ids.append(hid)


# ==================== 主入口 ====================


def _reconfigure_stdio_utf8() -> None:
    """把 stdout/stderr 重配成 UTF-8（Windows GBK 兼容，emoji/中文不乱码）。

    幂等：已是 UTF-8 TextIOWrapper 的流不重复包装（main.py 顶部可能已预先处理过）。
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


def setup_logging(
    socket_sink: Optional[Callable] = None,
    console: bool = True,
    log_file: Optional[str] = None,
    error_file: Optional[str] = None,
) -> None:
    """配置 loguru 的全部 sink。幂等：每次调用先 remove() 再重建。

    必须在任何日志输出前、且在导入会触发日志的模块前调用（进程启动最早处）。

    参数:
        socket_sink: 可选，WebSocket 实时广播回调（main.py 传入 socket_log_sink）。
        console: 是否挂载控制台 sink（GEO 测评 worker 的 stdout 承载 JSON 协议，须关闭）。
        log_file / error_file: 文件路径模式（默认取 config 的 LOG_FILE / ERROR_LOG_FILE；
            worker 传入 WORKER_LOG_FILE / WORKER_ERROR_LOG_FILE 以区分文件前缀）。
    """
    # 1. stdout/stderr UTF-8（必须在挂载 stdout sink 之前完成）
    _reconfigure_stdio_utf8()

    # 2. 清空默认 sink，避免 loguru 自带的 stderr handler 重复输出
    logger.remove()

    # 3. 全局 patcher：为每条日志自动补齐 request_id / user 上下文
    logger.configure(patcher=_patch_extra)

    # 4. 控制台 sink —— 彩色、LOG_LEVEL 级（可经 LOG_LEVEL 调高到 DEBUG）
    if console:
        logger.add(
            sys.stdout,
            level=LOG_LEVEL,
            colorize=True,
            format=_CONSOLE_FORMAT,
            backtrace=False,
            diagnose=False,
        )

    # 5. 文件 sink —— 按天滚动（文件名带日期），自动清理只保留最近 3 天
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    main_pattern = log_file or str(LOG_FILE)
    error_pattern = error_file or str(ERROR_LOG_FILE)
    _last_file_args = {"log_file": main_pattern, "error_file": error_pattern}
    _mount_file_sinks(main_pattern, error_pattern)

    # 6. WebSocket 实时广播 sink（可选，由 main.py 提供）
    if socket_sink is not None:
        logger.add(socket_sink, level="INFO", enqueue=False)

    # 7. 标准库 logging 桥接 + 未处理异常兜底 + 启动期旧文件清扫
    _install_stdlib_bridge()
    _install_exception_hooks()
    cleanup_old_log_files()

    logger.debug(
        f"日志系统已就绪: 控制台={LOG_LEVEL if console else 'OFF'}, "
        f"主文件={LOG_FILE_LEVEL}@{main_pattern}, "
        f"错误文件={LOG_ERROR_LEVEL}@{error_pattern}, "
        f"保留 {LOG_RETENTION_DAYS} 天, log_dir={LOG_DIR}"
    )


def setup_worker_logging() -> None:
    """GEO 测评 worker 专用日志初始化：只写文件、不写控制台。

    worker 的 stdout 承载 JSON 事件协议（emit 函数），绝不能混入日志；
    日志文件使用 auto_geo_worker_YYYY-MM-DD.log 前缀，与后端主进程区分。
    """
    setup_logging(console=False, log_file=str(WORKER_LOG_FILE), error_file=str(WORKER_ERROR_LOG_FILE))


# ==================== 管理后台辅助 ====================


def read_log_lines(level: Optional[str] = None, limit: int = 200, offset: int = 0) -> dict:
    """读取最近日志行，供管理后台 /api/admin/logs 使用。

    - 默认读主日志（DEBUG 级全量）；level 为 ERROR/WARNING 时读错误日志。
    - 优先读今天的文件；今天尚无文件时回退到目录中最新的一份。
    - level 非空时按关键字过滤（大小写不敏感），与旧接口行为保持一致。
    """
    level_up = (level or "").upper()
    prefer_error = level_up in {"ERROR", "WARNING", "WARN"}
    files = list_log_files(level if prefer_error else None)
    if not files:
        return {"total": 0, "items": []}

    # 优先今天的文件（列表已按名称倒序；若今天存在它必然排第一），否则最新一份
    today = resolve_today_log_path(level if prefer_error else None)
    read_path = today if today.exists() else files[0]

    try:
        lines = read_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return {"total": 0, "items": []}

    if level_up:
        lines = [line for line in lines if level_up in line.upper()]

    total = len(lines)
    items = [{"line": line} for line in lines[::-1][offset : offset + limit]]
    return {"total": total, "items": items}


def clear_log_files() -> int:
    """清空系统日志：删除今天的日志文件内容并重建 sink，同时清扫过期文件。

    通过先移除再重建文件 sink 的方式实现，避免 Windows 下文件被 loguru 占用
    导致删除/截断失败。返回处理的文件数量。
    """
    # 1. 先排空异步写入队列，避免移除 sink 后仍有残留写入
    try:
        logger.complete()
    except Exception:
        pass

    # 2. 移除并重建文件 sink（句柄关闭后即可安全删除）
    for hid in _file_handler_ids:
        try:
            logger.remove(hid)
        except Exception:
            pass
    _file_handler_ids.clear()

    removed = 0
    for pattern in (LOG_FILE, ERROR_LOG_FILE):
        today = _resolve_dated_path(pattern)
        try:
            if today.exists():
                today.unlink()
                removed += 1
        except OSError as exc:
            logger.warning(f"删除今日日志文件失败（将在重建 sink 后重试截断）: {today} - {exc}")

    # 3. 清扫过期文件 + 重建 sink（重建后新的一天日志从空文件开始）
    removed += cleanup_old_log_files()
    args = _last_file_args or {"log_file": str(LOG_FILE), "error_file": str(ERROR_LOG_FILE)}
    _mount_file_sinks(args["log_file"], args["error_file"])
    return removed
