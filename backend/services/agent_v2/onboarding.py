# -*- coding: utf-8 -*-
"""新用户引导状态机（V2 统一引导）。

设计原则（见 docs/ONBOARDING_REDESIGN.md）：
- 引导 = 确定性状态机，不是 LLM 自由发挥。
- 每一步“该推什么、显示哪些按钮”由本模块按数据库实况算出，可测、可控。
- LLM 只负责理解话术 + 执行工具；按钮生成与进度持久化归代码。

关键发现：前端 AgentChat.vue 早已实现每一步对应的弹窗（show_client_form /
show_project_form / upload_files / generate_questions / generate_articles /
show_add_account / show_article_list），且 action 类型已在 actions.py 注册。
因此本模块只负责“算下一步该给哪些 action”，前端照现有机制渲染即可。

进度真相来源 = DB 实况 + UserAgentPreference.onboarding_dismissed +
UserAgentFact.onboarding_completed，不依赖会话上下文（MemorySaver 重启无妨）。
"""

from __future__ import annotations

from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from backend.database.models import (
    Account,
    Client,
    GeoArticle,
    Knowledge,
    KnowledgeCategory,
    Project,
    SmartArticleQuestion,
    UserAgentPreference,
)
from backend.services.agent_v2.actions import make_action
from backend.services.agent_v2.memory import FactStore


# ---------------------------------------------------------------------------
#  必需 6 步（顺序即进度条顺序；上传资料为可选，不计入完成判定）
#  deps：完成本步的前置步；next_actions 只返回“未做完且前置已满足”的步。
# ---------------------------------------------------------------------------
STEPS: list[dict[str, Any]] = [
    {
        "key": "client",
        "label": "建客户",
        "action": ("show_client_form", "新建客户", {}),
        "deps": [],
    },
    {
        "key": "project",
        "label": "建项目",
        "action": ("show_project_form", "新建项目", {}),
        "deps": ["client"],
    },
    {
        "key": "questions",
        "label": "规划问题",
        "action": ("generate_questions", "生成问题", {"count": 1}),
        "deps": ["project"],
    },
    {
        "key": "articles",
        "label": "生成文章",
        "action": ("generate_articles", "生成文章", {"count": 1}),
        "deps": ["questions"],
    },
    {
        "key": "account",
        "label": "绑定发布账号",
        "action": ("show_add_account", "绑定发布账号", {}),
        "deps": ["articles"],
    },
    {
        "key": "publish",
        "label": "审核发布首篇",
        "action": ("show_article_list", "去发布", {}),
        "deps": ["account"],
    },
]


# ---------------------------------------------------------------------------
#  单步完成判定（查 DB 实况）
# ---------------------------------------------------------------------------
def _client_done(db: Session, user_id: int) -> bool:
    return db.query(Client).filter(Client.user_id == user_id).count() > 0


def _project_done(db: Session, user_id: int) -> bool:
    return db.query(Project).filter(Project.user_id == user_id).count() > 0


def _questions_done(db: Session, user_id: int) -> bool:
    return (
        db.query(SmartArticleQuestion)
        .filter(SmartArticleQuestion.user_id == user_id, SmartArticleQuestion.is_deleted.is_(False))
        .count()
        > 0
    )


def _articles_done(db: Session, user_id: int) -> bool:
    """文章已生成（生成后状态非 draft 即视为已生成）。"""
    return db.query(GeoArticle).filter(GeoArticle.user_id == user_id, GeoArticle.publish_status != "draft").count() > 0


def _account_done(db: Session, user_id: int) -> bool:
    return db.query(Account).filter(Account.user_id == user_id, Account.deleted_at.is_(None)).count() > 0


def _publish_done(db: Session, user_id: int) -> bool:
    return (
        db.query(GeoArticle).filter(GeoArticle.user_id == user_id, GeoArticle.publish_status == "published").count() > 0
    )


_DONE_CHECKS = {
    "client": _client_done,
    "project": _project_done,
    "questions": _questions_done,
    "articles": _articles_done,
    "account": _account_done,
    "publish": _publish_done,
}


def _latest_project_id(db: Session, user_id: int) -> int | None:
    """引导流程中“当前项目”的启发式：取该用户最新的（未删除）项目。

    引导是线性流程（建客户→建项目→…），进行到“生成问题/文章”时通常只有一个项目。
    取最新创建的项目作为目标，使生成的 action 自带 project_id，前端点击即可直达工具。
    """
    proj = db.query(Project).filter(Project.user_id == user_id).order_by(Project.id.desc()).first()
    return proj.id if proj else None


def _latest_client(db: Session, user_id: int) -> Client | None:
    """取该用户最新创建的客户，用于引导期"上传资料"等动作自动带入选定客户。"""
    return db.query(Client).filter(Client.user_id == user_id).order_by(Client.id.desc()).first()


def _client_has_knowledge(db: Session, client_id: int) -> bool:
    """判断指定客户是否已有知识库资料（上传过文件）。"""
    return (
        db.query(Knowledge)
        .join(KnowledgeCategory, Knowledge.category_id == KnowledgeCategory.id)
        .filter(KnowledgeCategory.client_id == client_id)
        .count()
    ) > 0


def _checklist(done: dict[str, bool]) -> list[dict[str, Any]]:
    return [{"key": s["key"], "label": s["label"], "done": bool(done[s["key"]])} for s in STEPS]


# ---------------------------------------------------------------------------
#  对外主函数
# ---------------------------------------------------------------------------
def compute_onboarding_state(db: Session, user_id: int, is_admin: bool = False) -> dict[str, Any]:
    """计算新用户引导状态。

    返回结构（前端数据源）：
    {
      "active": bool,            # 是否处于引导中（需要展示进度条/卡片）
      "dismissed": bool,         # 用户是否已跳过
      "completed": bool,         # 必需 6 步是否全完成
      "checklist": [{key,label,done}],   # 进度条
      "next_actions": [action],  # 对话内“下一步”卡片（已注册 action）
      "optional_actions": [action],  # 可选增强（如上传资料），不计入完成
      "can_skip": bool,          # 是否展示“跳过引导”
    }
    """
    # admin 不引导
    if is_admin:
        return {
            "active": False,
            "dismissed": True,
            "completed": True,
            "checklist": _checklist({k: True for k in _DONE_CHECKS}),
            "next_actions": [],
            "optional_actions": [],
            "can_skip": False,
        }

    pref = db.query(UserAgentPreference).filter(UserAgentPreference.system_user_id == user_id).first()
    dismissed = bool(pref and pref.onboarding_dismissed)

    fact_store = FactStore(db)
    completed = fact_store.is_onboarding_completed(user_id)

    # 计算每一步实况
    done = {key: check(db, user_id) for key, check in _DONE_CHECKS.items()}

    # 必需全完成 → 持久化 completed（幂等）
    if all(done.values()) and not completed:
        fact_store.set_onboarding_completed(user_id, True)
        completed = True
        logger.info(f"[Onboarding] 新用户引导全部完成: user_id={user_id} done={done}")

    logger.debug(
        f"[Onboarding] 引导状态计算: user_id={user_id} dismissed={dismissed} completed={completed} done={done}"
    )
    checklist = _checklist(done)

    # 已完成：不再推卡片
    if completed:
        return {
            "active": False,
            "dismissed": dismissed,
            "completed": True,
            "checklist": checklist,
            "next_actions": [],
            "optional_actions": [],
            "can_skip": False,
        }

    # 已跳过：不推卡片（但返回 checklist 供前端隐藏进度条）
    if dismissed:
        return {
            "active": False,
            "dismissed": True,
            "completed": False,
            "checklist": checklist,
            "next_actions": [],
            "optional_actions": [],
            "can_skip": False,
        }

    # 计算下一步动作：未做完 且 所有前置已满足
    next_actions: list[dict[str, Any]] = []
    for step in STEPS:
        if done[step["key"]]:
            continue
        if all(done[d] for d in step["deps"]):
            atype, label, payload = step["action"]
            next_actions.append(make_action(atype, label, dict(payload)))

    # 为“生成问题/文章”动作注入 project_id（引导期通常只有一个进行中的项目），
    # 使卡片点击后直达工具、无需 LLM 再去猜 project_id；生成问题默认 1 个。
    project_id = _latest_project_id(db, user_id)
    for act in next_actions:
        if act.get("type") in ("generate_questions", "generate_articles") and project_id is not None:
            act.setdefault("payload", {})["project_id"] = project_id
            if act["type"] == "generate_questions":
                # 工具槽位名为 question_count，引导默认 1 个问题
                act["payload"]["question_count"] = act["payload"].get("count", 1)

    # 为“新建项目”动作注入最新客户信息，避免弹窗里还要再选/再填客户。
    latest_client = _latest_client(db, user_id)
    if latest_client is not None:
        for act in next_actions:
            if act.get("type") == "show_project_form":
                act.setdefault("payload", {})["client_id"] = latest_client.id
                act["payload"]["company_name"] = latest_client.company_name or latest_client.name or ""

    # 可选：客户已建、项目未建 → 提示一次“上传资料(可选)”
    # 自动注入最新客户信息，避免用户重复填写公司名称；
    # 若该客户已上传过知识库资料，则不再重复提示。
    optional_actions: list[dict[str, Any]] = []
    if done["client"] and not done["project"]:
        latest_client = _latest_client(db, user_id)
        if latest_client is not None and not _client_has_knowledge(db, latest_client.id):
            upload_payload: dict[str, Any] = {
                "client_id": latest_client.id,
                "company_name": latest_client.company_name or latest_client.name or "",
            }
            optional_actions.append(make_action("upload_files", "上传资料(可选)", upload_payload))

    return {
        "active": True,
        "dismissed": False,
        "completed": False,
        "checklist": checklist,
        "next_actions": next_actions,
        "optional_actions": optional_actions,
        "can_skip": True,
    }


def set_onboarding_dismissed(db: Session, user_id: int, value: bool = True) -> None:
    """持久化“跳过引导”。落在 UserAgentPreference（与 V1 同一个字段）。"""
    pref = db.query(UserAgentPreference).filter(UserAgentPreference.system_user_id == user_id).first()
    if not pref:
        pref = UserAgentPreference(system_user_id=user_id)
        db.add(pref)
    pref.onboarding_dismissed = value
    db.commit()
    logger.info(f"[Onboarding] 引导跳过状态更新: user_id={user_id} dismissed={value}")
