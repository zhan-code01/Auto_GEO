# -*- coding: utf-8 -*-
"""
Playwright发布适配器模块
用这个来管理所有平台的发布器！
"""

from .base import BasePublisher, PublisherRegistry, registry, get_publisher, list_publishers
from .zhihu import ZhihuPublisher
from .baijiahao import BaijiahaoPublisher
from .baijiahao_codegen import BaijiahaoCodegenPublisher
from .sohu import SohuPublisher
from .toutiaopro import ToutiaoProPublisher
from .xiaohongshu import XiaohongshuPublisher
from .douyin import DouyinPublisher
from .kuaishou import KuaishouPublisher
from .weibo import WeiboPublisher
from .bilibili import BilibiliPublisher
from .weixin import WeixinPublisher
from .jianshupro import JianshuProPublisher, JianshuPublisher
from .juejinpro import JuejinProPublisher, JuejinPublisher
from .penguin import PenguinPublisher
from .csdn import CsdnPublisher
from .csdn_codegen import CsdnCodegenPublisher
from .wangyi import WangyiPublisher
from .cnblogs import CnblogsPublisher
from .douban import DoubanPublisher
from .tieba import TiebaPublisher


def register_publishers(platforms_config):
    """
    注册所有平台发布器

    注意：这个函数需要在服务启动时调用！
    """
    for platform_id, config in platforms_config.items():
        publisher = None

        if platform_id == "zhihu":
            publisher = ZhihuPublisher(platform_id, config)
        elif platform_id == "baijiahao":
            publisher = BaijiahaoPublisher(platform_id, config)
        elif platform_id == "sohu":
            publisher = SohuPublisher(platform_id, config)
        elif platform_id == "toutiao":
            publisher = ToutiaoProPublisher(platform_id, config)
        elif platform_id == "xiaohongshu":
            publisher = XiaohongshuPublisher(platform_id, config)
        elif platform_id == "douyin":
            publisher = DouyinPublisher(platform_id, config)
        elif platform_id == "kuaishou":
            publisher = KuaishouPublisher(platform_id, config)
        elif platform_id == "weibo":
            publisher = WeiboPublisher(platform_id, config)
        elif platform_id == "bilibili":
            publisher = BilibiliPublisher(platform_id, config)
        elif platform_id == "weixin":
            publisher = WeixinPublisher(platform_id, config)
        elif platform_id == "jianshu":
            publisher = JianshuProPublisher(platform_id, config)
        elif platform_id == "juejin":
            publisher = JuejinProPublisher(platform_id, config)
        elif platform_id == "penguin":
            publisher = PenguinPublisher(platform_id, config)
        elif platform_id == "csdn":
            publisher = CsdnPublisher(platform_id, config)
        elif platform_id == "csdn_codegen":
            publisher = CsdnCodegenPublisher(platform_id, config)
        elif platform_id == "wangyi":
            publisher = WangyiPublisher(platform_id, config)
        elif platform_id == "cnblogs":
            publisher = CnblogsPublisher(platform_id, config)
        elif platform_id == "douban":
            publisher = DoubanPublisher(platform_id, config)
        elif platform_id == "tieba":
            publisher = TiebaPublisher(platform_id, config)

        if publisher:
            registry.register(platform_id, publisher)


__all__ = [
    "BasePublisher",
    "PublisherRegistry",
    "registry",
    "get_publisher",
    "list_publishers",
    "register_publishers",
    "ZhihuPublisher",
    "BaijiahaoPublisher",
    "SohuPublisher",
    "ToutiaoProPublisher",
    "XiaohongshuPublisher",
    "DouyinPublisher",
    "KuaishouPublisher",
    "WeiboPublisher",
    "BilibiliPublisher",
    "WeixinPublisher",
    "JianshuProPublisher",
    "JianshuPublisher",
    "JuejinProPublisher",
    "JuejinPublisher",
    "PenguinPublisher",
    "CsdnPublisher",
    "CsdnCodegenPublisher",
    "WangyiPublisher",
    "CnblogsPublisher",
    "DoubanPublisher",
    "TiebaPublisher",
]
