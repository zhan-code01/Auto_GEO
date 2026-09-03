# -*- coding: utf-8 -*-
"""Action 按钮类型定义。

对应 PRD §11.3 共 13 种 Action 类型。前端根据 type 渲染对应弹窗/组件：
- 列表弹窗（show_*_list）
- 表单弹窗（show_*_form）
- 选择弹窗（select_*）
- 指标卡片（show_diagnosis）
- 文件上传（upload_files）
- 确认对话框（confirm）
"""
from __future__ import annotations

from typing import Literal


ActionInteraction = Literal["frontend_direct", "via_agent"]


# Action 类型清单 - 严格对齐 PRD §11.3 共 13 种
ACTION_TYPES: dict[str, dict] = {
    # ===== 列表弹窗（5 种）：分页表格展示 =====
    "show_client_list": {
        "interaction": "frontend_direct",
        "render": "list_modal",
        "desc": "展示客户列表",
    },
    "show_project_list": {
        "interaction": "frontend_direct",
        "render": "list_modal",
        "desc": "展示项目列表",
    },
    "show_question_list": {
        "interaction": "frontend_direct",
        "render": "list_modal",
        "desc": "展示问题列表（可选择问题生成文章）",
    },
    "show_article_list": {
        "interaction": "frontend_direct",
        "render": "list_modal",
        "desc": "展示文章列表（可选择文章发布）",
    },
    "show_binding_list": {
        "interaction": "frontend_direct",
        "render": "list_modal",
        "desc": "展示已绑定发布平台列表",
    },
    "show_publish_records": {
        "interaction": "frontend_direct",
        "render": "list_modal",
        "desc": "展示发布记录",
    },
    # ===== 表单弹窗（2 种）：结构化表单输入 =====
    "show_client_form": {
        "interaction": "via_agent",
        "render": "form_modal",
        "desc": "填写客户信息",
    },
    "show_project_form": {
        "interaction": "via_agent",
        "render": "form_modal",
        "desc": "填写项目信息",
    },
    # ===== 选择弹窗（3 种）：从选项中选择 =====
    "select_platform": {
        "interaction": "via_agent",
        "render": "select_modal",
        "desc": "选择发布平台",
    },
    "select_ai_platform": {
        "interaction": "via_agent",
        "render": "select_modal",
        "desc": "选择 AI 平台（豆包/通义千问/DeepSeek）",
    },
    "select_account": {
        "interaction": "via_agent",
        "render": "select_modal",
        "desc": "选择账号",
    },
    # ===== 指标卡片（1 种）：收录监控结果 =====
    "show_diagnosis": {
        "interaction": "frontend_direct",
        "render": "metric_card",
        "desc": "展示诊断指标（4 个核心指标）",
    },
    # ===== 文件上传（1 种） =====
    "upload_files": {
        "interaction": "via_agent",
        "render": "upload_modal",
        "desc": "上传文件",
    },
    # ===== 确认对话框（1 种） =====
    "confirm": {
        "interaction": "via_agent",
        "render": "confirm_dialog",
        "desc": "确认操作",
    },
    # ===== 智能体生成的业务动作（2 种） =====
    "generate_questions": {
        "interaction": "via_agent",
        "render": "confirm_dialog",
        "desc": "生成用户问题（基于项目/知识库）",
    },
    "generate_articles": {
        "interaction": "via_agent",
        "render": "confirm_dialog",
        "desc": "生成文章（基于已生成的问题）",
    },
    # ===== 添加账号弹窗（1 种） =====
    "show_add_account": {
        "interaction": "frontend_direct",
        "render": "form_modal",
        "desc": "添加账号（选择平台并启动浏览器授权）",
    },
}


def make_action(
    action_type: str,
    label: str,
    payload: dict | None = None,
    interaction: ActionInteraction | None = None,
) -> dict:
    """构造 Action 按钮。

    Args:
        action_type: Action 类型（必须在 ACTION_TYPES 中注册）
        label: 按钮文案
        payload: 按钮数据
        interaction: 交互方式，未指定时从 ACTION_TYPES 取默认值

    Raises:
        ValueError: 当 action_type 未在 ACTION_TYPES 注册时
    """
    spec = ACTION_TYPES.get(action_type)
    if spec is None:
        raise ValueError(
            f"未注册的 action 类型：{action_type}，"
            f"合法类型：{list(ACTION_TYPES.keys())}"
        )
    return {
        "type": action_type,
        "label": label,
        "payload": payload or {},
        "interaction": interaction or spec.get("interaction", "via_agent"),
    }


def is_frontend_direct(action: dict) -> bool:
    """判断 Action 是否前端直连。"""
    return action.get("interaction") == "frontend_direct"


def is_via_agent(action: dict) -> bool:
    """判断 Action 是否走智能体。"""
    return action.get("interaction") == "via_agent"
