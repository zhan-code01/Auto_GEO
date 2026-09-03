# -*- coding: utf-8 -*-
"""
Backend 包入口
确保 backend 目录可以被正确识别为 Python 包
"""

from backend.config import *

# 定义 __all__，让 "from backend.api import *" 正确工作
__all__ = [
    "account",
    "article",
    "publish",
    "keywords",
    "geo",
    "index_check",
    "reports",
    "notifications",
    "scheduler",
    "knowledge",
    "auth",
    "article_collection",
    "site_builder",
]
