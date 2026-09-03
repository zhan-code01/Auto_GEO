# -*- coding: utf-8 -*-
"""
文章收集器模块
"""

from typing import Dict, Any

from .base import (
    BaseCollector,
    CollectedArticle,
    CollectorRegistry,
    collector_registry,
    get_collector,
    list_collectors,
)
from .zhihu import ZhihuCollector
from .toutiao import ToutiaoCollector


def register_collectors(platforms_config: Dict[str, Any]):
    """
    注册所有收集器

    Args:
        platforms_config: 平台配置
    """
    # 知乎
    if "zhihu" in platforms_config:
        collector_registry.register("zhihu", ZhihuCollector("zhihu", platforms_config["zhihu"]))

    # 今日头条
    if "toutiao" in platforms_config:
        collector_registry.register("toutiao", ToutiaoCollector("toutiao", platforms_config["toutiao"]))


__all__ = [
    "BaseCollector",
    "CollectedArticle",
    "CollectorRegistry",
    "collector_registry",
    "get_collector",
    "list_collectors",
    "register_collectors",
    "ZhihuCollector",
    "ToutiaoCollector",
]
