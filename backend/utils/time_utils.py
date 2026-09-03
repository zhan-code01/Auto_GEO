# -*- coding: utf-8 -*-
"""统一业务时间口径：北京时间（UTC+8）的 naive datetime。

数据库中 publish_time / check_time / baseline_at / last_check_time 等业务时间戳
一律以「北京时间、无时区信息（naive）」落库。这样无论服务运行在本机、容器（UTC）
还是任意时区的服务器上，统计「今日 / 近 N 天」都不会因服务器 TZ 漂移而算错。

严禁再用 datetime.now()（服务器本地时间）写业务时间戳：Windows 本机恰好是东八区、
生产容器里 TZ=Asia/Shanghai 也恰好一致，一旦换到 UTC 服务器就会整体偏 8 小时。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def beijing_now() -> datetime:
    """返回当前北京时间（naive，无时区信息），与落库口径一致。"""
    return (datetime.now(timezone.utc) + timedelta(hours=8)).replace(tzinfo=None)


def beijing_today_start() -> datetime:
    """返回北京时间的「今日 00:00:00」（naive）。"""
    return beijing_now().replace(hour=0, minute=0, second=0, microsecond=0)
