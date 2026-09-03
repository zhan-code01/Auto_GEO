# -*- coding: utf-8 -*-
"""平台标识助手 - Agent V2 共用。

解决两个老问题：
1. 中文平台名 / 别名 → 平台 ID 的解析（"绑定抖音" 直接抽到 platform=douyin）。
2. 区分「发布平台」与「AI 鉴权专用平台」：
   - backend.config.PLATFORMS 是发布平台集合（知乎/百家号/抖音…）；
   - backend.config.AI_PLATFORMS 是 GEO 评测采集用的 AI 鉴权账号（doubao/qianwen/deepseek），
     普通用户不应在「我绑了哪些平台」里看到它们。
   所以 is_publish_platform(pid) 等价于 pid in PLATFORMS。
"""
from __future__ import annotations

from typing import Optional

from backend.config import AI_PLATFORMS, PLATFORMS


# 发布平台 ID 列表（用于过滤 AI 鉴权专用平台）
PUBLISH_PLATFORM_IDS: list[str] = list(PLATFORMS.keys())
# AI 鉴权专用平台 ID 列表
AI_PLATFORM_IDS: list[str] = list(AI_PLATFORMS.keys())


def is_publish_platform(platform_id: Optional[str]) -> bool:
    """是否为可发布的平台（排除 doubao/qianwen/deepseek 等 AI 鉴权专用）。"""
    return bool(platform_id) and platform_id in PLATFORMS


def is_ai_platform(platform_id: Optional[str]) -> bool:
    """是否为 AI 鉴权专用平台。"""
    return bool(platform_id) and platform_id in AI_PLATFORMS


# 中文名 / 别名 → 平台 ID 映射
_ALIAS: dict[str, str] = {}


def _register(alias: str, pid: str) -> None:
    if alias:
        _ALIAS[alias.strip().lower()] = pid


# 1) 平台自带 name
for _pid, _info in {**PLATFORMS, **AI_PLATFORMS}.items():
    _register(_pid, _pid)
    if isinstance(_info, dict):
        _name = _info.get("name")
        if _name:
            _register(_name, _pid)

# 2) 人工补充的常见别名
_MANUAL_ALIASES: dict[str, str] = {
    "抖音": "douyin",
    "抖音号": "douyin",
    "douyin": "douyin",
    "头条": "toutiao",
    "今日头条": "toutiao",
    "头条号": "toutiao",
    "知乎": "zhihu",
    "小红书": "xiaohongshu",
    "红书": "xiaohongshu",
    "小红薯": "xiaohongshu",
    "xhs": "xiaohongshu",
    "百家号": "baijiahao",
    "百度百家": "baijiahao",
    "微信": "weixin",
    "微信公众号": "weixin",
    "公众号": "weixin",
    "搜狐": "sohu",
    "搜狐号": "sohu",
    "网易": "wangyi",
    "网易号": "wangyi",
    "企鹅号": "penguin",
    "腾讯": "penguin",
    "贴吧": "tieba",
    "百度贴吧": "tieba",
    "文库": "wenku",
    "百度文库": "wenku",
    "字节": "zijie",
    "字节号": "zijie",
    "豆包": "doubao",
    "doubao": "doubao",
    "千问": "qianwen",
    "通义千问": "qianwen",
    "qianwen": "qianwen",
    "deepseek": "deepseek",
    "深度求索": "deepseek",
    "csdn": "csdn",
    "csdn博客": "csdn",
    "快手": "kuaishou",
    "快手号": "kuaishou",
    "kuaishou": "kuaishou",
    "简书": "jianshu",
    "简书号": "jianshu",
    "jianshu": "jianshu",
    "掘金": "juejin",
    "juejin": "juejin",
    "b站": "bilibili",
    "bilibili": "bilibili",
    "哔哩哔哩": "bilibili",
}
for _a, _p in _MANUAL_ALIASES.items():
    _register(_a, _p)


def resolve_platform(text: Optional[str]) -> Optional[str]:
    """从自然语言文本中解析平台 ID。

    先精确匹配（整句就是平台名/ID），再子串匹配（如「绑定抖音账号」→ douyin）。
    返回平台 ID 或 None。
    """
    if not text:
        return None
    t = text.strip().lower()
    if not t:
        return None
    # 精确
    if t in _ALIAS:
        return _ALIAS[t]
    # 子串（优先更长别名）
    best: Optional[str] = None
    best_len = 0
    for alias, pid in _ALIAS.items():
        if not alias:
            continue
        if alias in t and len(alias) > best_len:
            best = pid
            best_len = len(alias)
    return best


def get_platform_name(platform_id: Optional[str]) -> Optional[str]:
    """把平台 ID 转成中文展示名。

    优先从 config.PLATFORMS / AI_PLATFORMS 的 name 字段取，
    找不到时回退到常见别名列表中找第一个中文名。
    """
    if not platform_id:
        return None
    # 1) 先从 PLATFORMS 取 name
    for source in (PLATFORMS, AI_PLATFORMS):
        info = source.get(platform_id)
        if isinstance(info, dict):
            name = info.get("name")
            if name:
                return name
        elif isinstance(info, str) and info:
            return info
    # 2) 从别名表反向找第一个中文名（兼容未配置 name 的平台）
    for alias, pid in _ALIAS.items():
        if pid == platform_id and any("\u4e00" <= ch <= "\u9fff" for ch in alias):
            return alias
    return platform_id
