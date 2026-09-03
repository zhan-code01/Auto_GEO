# -*- coding: utf-8 -*-
"""Agent V2 模块 - 基于 LangGraph 的智能体重构。

废弃老版本 services/agent/orchestrator.py，采用：
- LangGraph 状态图驱动
- 三层记忆（会话短期 / 用户长期事实 / 用户偏好）
- 槽位（Slot）管理与依赖失效
- 双路径文章生成（from_questions 走 GATE / batch 走 adapter 同步封装）
- SSE 流式响应 + WebSocket 异步通知
"""
