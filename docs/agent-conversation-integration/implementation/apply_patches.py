# -*- coding: utf-8 -*-
"""
AutoGEO Agent · 历史会话展示与记忆隔离 —— 后端实现应用器（阶段 1）

对应方案：docs/agent-conversation-integration/session-history-display-and-isolation.md

本脚本把方案 §7 阶段 1（后端）的全部改动以「精确字符串替换」的方式应用到
原项目文件，**不依赖 git apply / diff 格式**，因此：

  - 自动适配每个目标文件的换行符（CRLF / LF），不会因行尾不匹配而失败；
  - 幂等：已应用过的改动会自动跳过，可安全重复运行；
  - 可预检：``--check`` 只校验锚点是否命中，**不写任何文件**；
  - 可回滚：``--reverse`` 把改动原样还原（方案 §9 回滚）。

所有改动均为「追加或参数化」式，不破坏现有 /message、飞书、发布链路。

用法（在项目根目录下）：
    python docs/agent-conversation-integration/implementation/apply_patches.py --check     # 预检，不改文件
    python docs/agent-conversation-integration/implementation/apply_patches.py             # 应用
    python docs/agent-conversation-integration/implementation/apply_patches.py --reverse   # 回滚

退出码：全部成功或全部已应用 → 0；存在无法定位的锚点 → 1。
"""

import argparse
import sys
from pathlib import Path

# 项目根 = 本文件上溯三级（implementation → agent-conversation-integration → docs → 根）
ROOT = Path(__file__).resolve().parents[3]


# --------------------------------------------------------------------------------------
# 改动定义：每一项 = (id, 相对项目根的文件路径, find, replace, 说明)
# find / replace 中的换行统一用 \n；应用时按目标文件原始换行符写回。
# --------------------------------------------------------------------------------------
PATCHES = [
    # ------------------------------------------------------------------ 1. models.py
    {
        "id": "1-models-title",
        "file": "backend/database/models.py",
        "note": "ConversationSession 增加 title 列（列表展示用）",
        "find": """    expires_at = Column(DateTime, nullable=True, comment="过期时间")

    user = relationship("User", backref="conversation_sessions", foreign_keys=[system_user_id])""",
        "replace": """    expires_at = Column(DateTime, nullable=True, comment="过期时间")
    title = Column(String(120), nullable=True, comment="会话标题，用于列表展示")

    user = relationship("User", backref="conversation_sessions", foreign_keys=[system_user_id])""",
    },
    # ------------------------------------------------------------ 2. fix_database.py
    {
        "id": "2-fixdb-title",
        "file": "backend/scripts/fix_database.py",
        "note": "check_and_fix_database 同步补 conversation_sessions.title 列（项目铁律）",
        "find": """            except Exception as e:
                logger.warning(f"Failed to create auto_publish_tasks.triggered_by_user_id index: {e}")
                conn.rollback()

        logger.success("数据库表结构检查和修复完成")""",
        "replace": """            except Exception as e:
                logger.warning(f"Failed to create auto_publish_tasks.triggered_by_user_id index: {e}")
                conn.rollback()

        # === conversation_sessions 表：会话标题列（历史会话列表展示用） ===
        cursor.execute("PRAGMA table_info(conversation_sessions)")
        conv_existing = [col[1] for col in cursor.fetchall()]
        for conv_col_name, conv_col_def in [("title", "VARCHAR(120)")]:
            if conv_col_name not in conv_existing:
                logger.info(f"Adding missing conversation_sessions column: {conv_col_name}...")
                try:
                    cursor.execute(
                        f"ALTER TABLE conversation_sessions ADD COLUMN {conv_col_name} {conv_col_def}"
                    )
                    conn.commit()
                    logger.success(f"✓ conversation_sessions.{conv_col_name} 列添加成功")
                except Exception as e:
                    logger.error(f"Failed to add conversation_sessions.{conv_col_name}: {e}")
                    conn.rollback()

        logger.success("数据库表结构检查和修复完成")""",
    },
    # ----------------------------------------------------- 3a. orchestrator.py import
    {
        "id": "3a-orch-import",
        "file": "backend/services/agent/orchestrator.py",
        "note": "orchestrator 导入 ConversationSession（derive_execution_plan 类型注解用）",
        "find": """from sqlalchemy.orm import Session

from backend.database.models import User
from backend.services.agent.intent_recognizer import get_intent_recognizer""",
        "replace": """from sqlalchemy.orm import Session

from backend.database.models import ConversationSession, User
from backend.services.agent.intent_recognizer import get_intent_recognizer""",
    },
    # ------------------------------------------------- 3b. orchestrator.py 写入 title
    {
        "id": "3b-orch-title",
        "file": "backend/services/agent/orchestrator.py",
        "note": "首条用户消息截断生成 session.title（规则版，零 LLM 成本）",
        "find": """        memory.add_message(db, session.id, "user", request.message, {"trace_id": trace_id})

        recent_messages = memory.get_context_for_llm(db, session.id, max_messages=8)""",
        "replace": """        memory.add_message(db, session.id, "user", request.message, {"trace_id": trace_id})

        # 会话标题：首条用户消息截断生成，供历史列表展示（规则版，零 LLM 成本）。
        # 仅在会话尚无标题时写入，后续不覆盖，避免多轮对话把标题刷成最后一条。
        if not session.title:
            _title_raw = (request.message or "").strip().replace("\\n", " ")
            session.title = (_title_raw[:24] + "…") if len(_title_raw) > 24 else (_title_raw or "新对话")
            db.commit()

        recent_messages = memory.get_context_for_llm(db, session.id, max_messages=8)""",
    },
    # ------------------------------------- 3c. orchestrator.py 新增 derive_execution_plan
    {
        "id": "3c-orch-plan",
        "file": "backend/services/agent/orchestrator.py",
        "note": "新增 derive_execution_plan：复用业务解析为详情接口现算 execution_plan",
        "find": """            plan=plan,
        )

    async def handle_external_message(""",
        "replace": """            plan=plan,
        )

    def derive_execution_plan(
        self,
        db: Session,
        current_user: User,
        session: ConversationSession,
    ) -> Optional[Dict[str, Any]]:
        \"\"\"
        基于已持久化的 session 现算“展示用”执行计划（execution_plan）。

        复用 _resolve_business_slots / _missing_slots_and_questions 这两套既有
        业务解析逻辑，因此 missing_slots 是真实查库算出来的（而非 TaskPlanner
        的静态默认值），展示给前端的“是否可执行 / 缺什么”才准确。

        纯展示、无副作用：只在局部 slots 拷贝上计算，不写回 session.slots，
        因此适合在 GET 详情接口（只读）中调用。
        \"\"\"
        try:
            slots = self._resolve_business_slots(db, current_user, dict(session.slots or {}))
            missing, _ = self._missing_slots_and_questions(db, current_user, slots)
            intent = slots.get("intent") or session.current_intent or "unknown"
            return get_task_planner().build_plan(intent, slots, missing).dict()
        except Exception:
            return None

    async def handle_external_message(""",
    },
    # ----------------------------------------------------------- 4. schemas.py DTO
    {
        "id": "4-schemas-dto",
        "file": "backend/services/agent/schemas.py",
        "note": "新增展示 DTO：SessionListItem / SessionDetail",
        "find": """    task_id: Optional[int] = None
    article_id: Optional[int] = None
    params: Dict[str, Any] = Field(default_factory=dict)
    context: Dict[str, Any] = Field(default_factory=dict)
    execution_plan: Optional[Dict[str, Any]] = None""",
        "replace": """    task_id: Optional[int] = None
    article_id: Optional[int] = None
    params: Dict[str, Any] = Field(default_factory=dict)
    context: Dict[str, Any] = Field(default_factory=dict)
    execution_plan: Optional[Dict[str, Any]] = None


class SessionListItem(BaseModel):
    \"\"\"历史会话列表展示项（不含 slots，仅展示派生数据）。\"\"\"

    id: str
    title: Optional[str] = None
    status: str
    current_intent: Optional[str] = None
    last_message: Optional[str] = None
    last_message_role: Optional[str] = None
    updated_at: Optional[str] = None


class SessionDetail(BaseModel):
    \"\"\"会话详情展示契约。slots 仅在 include_slots=True（管理 / 调试）时填充。\"\"\"

    id: str
    title: Optional[str] = None
    status: str
    current_intent: Optional[str] = None
    execution_plan: Optional[Dict[str, Any]] = None
    slots: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None""",
    },
    # ---------------------------------------- 5a. conversation.py 详情接口加 include_slots
    {
        "id": "5a-conv-detail-param",
        "file": "backend/api/conversation.py",
        "note": "GET /sessions/{id} 增加 include_slots 开关（默认 false，不返回 slots）",
        "find": """@router.get("/sessions/{session_id}")
async def get_session_detail(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):""",
        "replace": """@router.get("/sessions/{session_id}")
async def get_session_detail(
    session_id: str,
    include_slots: bool = Query(False, description="是否返回原始 slots（管理/调试用，默认不返回）"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):""",
    },
    # ----------------------------- 5b. conversation.py 详情 return：execution_plan + 去 slots
    {
        "id": "5b-conv-detail-body",
        "file": "backend/api/conversation.py",
        "note": "详情返回 execution_plan（从 slots 现算）+ title，slots 仅 include_slots 时返回",
        "find": """    return {
        "success": True,
        "data": {
            "session": {
                "id": session.id,
                "status": session.status,
                "current_intent": session.current_intent,
                "slots": session.slots or {},
                "created_at": session.created_at.isoformat() if session.created_at else None,
                "updated_at": session.updated_at.isoformat() if session.updated_at else None,
            },""",
        "replace": """    # execution_plan：从 slots 现算（复用 orchestrator 业务解析，missing_slots 真实）。
    # 展示层只暴露派生字段，不暴露 account_ids / project_id 等内部 ID。
    try:
        execution_plan = get_conversation_orchestrator().derive_execution_plan(
            db, current_user, session
        )
    except Exception:
        execution_plan = None

    session_payload = {
        "id": session.id,
        "title": session.title,
        "status": session.status,
        "current_intent": session.current_intent,
        "execution_plan": execution_plan,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "updated_at": session.updated_at.isoformat() if session.updated_at else None,
    }
    if include_slots:
        session_payload["slots"] = session.slots or {}

    return {
        "success": True,
        "data": {
            "session": session_payload,""",
    },
    # ------------------------------------- 5c. conversation.py 列表：title/预览/排除归档
    {
        "id": "5c-conv-list",
        "file": "backend/api/conversation.py",
        "note": "GET /sessions 返回 title + last_message 预览，默认排除 archived，去掉 slots",
        "find": """    \"\"\"列出当前用户的 Agent 会话（按最近更新倒序），用于前端恢复历史会话。\"\"\"
    query = (
        db.query(ConversationSession)
        .filter(ConversationSession.system_user_id == current_user.id)
        .order_by(ConversationSession.updated_at.desc())
    )
    if status:
        query = query.filter(ConversationSession.status == status)
    total = query.count()
    sessions = query.offset(offset).limit(limit).all()
    return ApiResponse(
        data={
            "total": total,
            "items": [
                {
                    "id": s.id,
                    "status": s.status,
                    "current_intent": s.current_intent,
                    "slots": s.slots or {},
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                    "updated_at": s.updated_at.isoformat() if s.updated_at else None,
                }
                for s in sessions
            ],
        }
    )""",
        "replace": """    \"\"\"列出当前用户的 Agent 会话（按最近更新倒序），用于前端恢复历史会话。

    展示契约：默认排除 archived；只返回展示字段（title / 状态 / 最后消息预览），
    不返回原始 slots（隔离记忆层）。
    \"\"\"
    query = (
        db.query(ConversationSession)
        .filter(ConversationSession.system_user_id == current_user.id)
        .order_by(ConversationSession.updated_at.desc())
    )
    # 默认排除归档会话；显式传 status=archived 时才返回归档项
    if status:
        query = query.filter(ConversationSession.status == status)
    else:
        query = query.filter(ConversationSession.status != "archived")
    total = query.count()
    sessions = query.offset(offset).limit(limit).all()

    items = []
    for s in sessions:
        # 最后一条消息预览（同会话最新一条 conversation_messages）
        last_msg = (
            db.query(ConversationMessage)
            .filter(ConversationMessage.conversation_id == s.id)
            .order_by(ConversationMessage.created_at.desc(), ConversationMessage.id.desc())
            .first()
        )
        if last_msg and last_msg.content:
            _raw = last_msg.content
            last_text = (_raw[:60] + "…") if len(_raw) > 60 else _raw
        else:
            last_text = None
        items.append(
            {
                "id": s.id,
                "title": s.title,
                "status": s.status,
                "current_intent": s.current_intent,
                "last_message": last_text,
                "last_message_role": last_msg.role if last_msg else None,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
            }
        )

    return ApiResponse(data={"total": total, "items": items})""",
    },
    # --------------------------------------------- 5d. conversation.py 新增归档端点
    {
        "id": "5d-conv-archive",
        "file": "backend/api/conversation.py",
        "note": "新增 POST /sessions/{id}/archive：软归档，不删数据",
        "find": """    session = _get_owned_session(db, session_id, current_user)
    executor = get_agent_task_executor()
    execution = executor.cancel_task(db, current_user, session.slots or {})

    memory = get_agent_memory()
    memory.add_message(
        db,
        session.id,
        "assistant",
        execution.reply,
        {"status": execution.status, "task_id": execution.task_id, "action": "cancel"},
    )
    memory.update_session_status(db, session, _session_status_from_execution(execution.status))
    return ApiResponse(
        data={
            "success": execution.success,
            "status": execution.status,
            "reply": execution.reply,
            "task_id": execution.task_id,
        }
    )""",
        "replace": """    session = _get_owned_session(db, session_id, current_user)
    executor = get_agent_task_executor()
    execution = executor.cancel_task(db, current_user, session.slots or {})

    memory = get_agent_memory()
    memory.add_message(
        db,
        session.id,
        "assistant",
        execution.reply,
        {"status": execution.status, "task_id": execution.task_id, "action": "cancel"},
    )
    memory.update_session_status(db, session, _session_status_from_execution(execution.status))
    return ApiResponse(
        data={
            "success": execution.success,
            "status": execution.status,
            "reply": execution.reply,
            "task_id": execution.task_id,
        }
    )


@router.post("/sessions/{session_id}/archive", response_model=ApiResponse)
async def archive_session(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    \"\"\"归档会话：仅将 status 置为 archived，不删除任何数据。

    归档后会话不再出现在默认列表（仍可通过 status=archived 或直接进入会话 ID 查看）。
    不动 slots / messages，agent 内部记忆不受影响（展示与记忆隔离）。
    \"\"\"
    session = _get_owned_session(db, session_id, current_user)
    memory = get_agent_memory()
    memory.update_session_status(db, session, "archived")
    return ApiResponse(data={"id": session.id, "status": "archived"})""",
    },
]


# --------------------------------------------------------------------------------------
# 应用 / 预检 / 回滚 引擎
# --------------------------------------------------------------------------------------
def detect_newline(raw_bytes: bytes) -> str:
    """探测文件原始换行符：含 \\r\\n 视作 CRLF，否则 LF。"""
    return "\r\n" if b"\r\n" in raw_bytes else "\n"


def load_file(path: Path):
    """返回 (归一化为 LF 的文本, 原始换行符)。"""
    raw = path.read_bytes()
    nl = detect_newline(raw)
    text = raw.decode("utf-8").replace("\r\n", "\n")
    return text, nl


def write_file(path: Path, text_lf: str, nl: str):
    """按原始换行符写回（LF 空间 → 还原为 nl）。"""
    out = text_lf.replace("\n", nl) if nl == "\r\n" else text_lf
    path.write_bytes(out.encode("utf-8"))


def apply_one(patch: dict, dry_run: bool, reverse: bool):
    """处理单个改动。返回 (状态字符串, 是否出错)。"""
    find = patch["find"]
    replace = patch["replace"]
    if reverse:
        find, replace = replace, find  # 回滚：交换方向

    path = ROOT / patch["file"]
    if not path.exists():
        print(f"  [缺失] {patch['id']}: 文件不存在 {patch['file']}")
        return "missing", True

    text, nl = load_file(path)

    if find not in text:
        # 可能已应用（正向）或已回滚（反向）
        other = patch["replace"] if not reverse else patch["find"]
        if other in text:
            tag = "已应用" if not reverse else "已回滚"
            print(f"  [跳过] {patch['id']}: {tag}，无需重复 — {patch['note']}")
            return "skipped", False
        print(f"  [失败] {patch['id']}: 找不到锚点，文件可能已被改动 — {patch['file']}")
        return "failed", True

    if dry_run:
        print(f"  [可应用] {patch['id']}: 锚点命中 — {patch['note']}")
        return "dry_ok", False

    new_text = text.replace(find, replace, 1)
    write_file(path, new_text, nl)
    print(f"  [完成] {patch['id']}: {patch['note']}  ({patch['file']})")
    return "applied", False


def main():
    parser = argparse.ArgumentParser(description="应用/预检/回滚 Agent 历史会话展示后端补丁")
    parser.add_argument("--check", action="store_true", help="只预检锚点，不写任何文件")
    parser.add_argument("--reverse", action="store_true", help="回滚（把改动还原）")
    args = parser.parse_args()

    action = "预检" if args.check else ("回滚" if args.reverse else "应用")
    print(f"\n=== {action} Agent 历史会话展示后端补丁（共 {len(PATCHES)} 项）===\n")

    errors = 0
    applied = 0
    skipped = 0
    for patch in PATCHES:
        status, err = apply_one(patch, dry_run=args.check, reverse=args.reverse)
        if err:
            errors += 1
        elif status == "applied":
            applied += 1
        elif status == "skipped":
            skipped += 1

    print(f"\n结果：应用 {applied} / 跳过(已处理) {skipped} / 失败 {errors}")
    if args.check:
        print("（预检模式：未修改任何文件）")
    if errors:
        print("\n有锚点未命中，请检查对应文件是否与补丁基线一致。")
        sys.exit(1)
    if not args.check:
        print("\n下一步：重启后端（首次会触发 fix_database 自动补 title 列），然后按 README 验收。")


if __name__ == "__main__":
    main()
