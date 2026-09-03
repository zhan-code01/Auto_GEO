# -*- coding: utf-8 -*-
"""Agent V2 适配器层。

包装现有 services 供工具层调用，隔离智能体与底层服务。
对应 PRD 第三章 3.3 节 adapters/ 目录。
"""
from backend.services.agent_v2.adapters.account_adapter import AccountAdapter
from backend.services.agent_v2.adapters.article_adapter import ArticleAdapter
from backend.services.agent_v2.adapters.client_adapter import ClientAdapter
from backend.services.agent_v2.adapters.knowledge_adapter import KnowledgeAdapter
from backend.services.agent_v2.adapters.project_adapter import ProjectAdapter
from backend.services.agent_v2.adapters.publish_adapter import PublishAdapter
from backend.services.agent_v2.adapters.question_pool_adapter import QuestionPoolAdapter

__all__ = [
    "AccountAdapter",
    "ArticleAdapter",
    "ClientAdapter",
    "KnowledgeAdapter",
    "ProjectAdapter",
    "PublishAdapter",
    "QuestionPoolAdapter",
]
