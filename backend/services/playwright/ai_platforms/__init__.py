# -*- coding: utf-8 -*-
"""
AI平台检测器模块
用这个来检测AI平台的收录情况！
"""

from .base import AIPlatformChecker
from .doubao import DoubaoChecker
from .qianwen import QianwenChecker
from .deepseek import DeepSeekChecker

__all__ = [
    "AIPlatformChecker",
    "DoubaoChecker",
    "QianwenChecker",
    "DeepSeekChecker",
]
