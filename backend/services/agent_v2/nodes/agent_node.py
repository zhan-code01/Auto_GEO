# -*- coding: utf-8 -*-
"""AGENT 节点 - ReAct Agent 推理核心。

对应 PRD §4.4 ReAct 循环。使用 LangChain `ChatOpenAI.bind_tools` 实现**原生 Tool Calling**：
- LLM 看到结构化的 tool definitions（OpenAI function calling 格式）
- LLM 自主决策是否调用工具，输出 `response.tool_calls`
- 不再依赖 JSON 文本解析，避免意图识别错误

核心特点：
1. LLM 真正参与工具选择和参数生成（基于 tool schema，不是按 intent 硬映射）
2. 通过 task_context 实现多轮信息提取（用户分多轮提供信息时累积 slots）
   - LLM 在追问用户时通过 <task_context> 标签显式输出短期记忆更新
   - agent_node 解析标签后更新 state.task_context，并从 reply 中过滤标签
   - 对应 PRD §7.3 记忆流转示例：每轮推理都"从消息提取"并"更新短期记忆"
3. 防跳步第三层：Agent 推理时根据业务规则判断是否调用工具
4. messages 直接用 LangChain BaseMessage 对象，保留消息角色边界
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from loguru import logger

from backend.services.agent_v2.state import AgentState, TaskContext


# ================================================================
#  System Prompt
# ================================================================

SYSTEM_PROMPT = """你是 AutoGeo 智能助手，帮助用户管理客户、项目、生成文章、发布内容、监控收录。

## 你的能力
你可以调用工具来完成任务。根据用户消息判断是否需要调用工具：
- 如果用户请求明确且信息完整，直接调用对应工具
- 如果信息不完整，先追问用户补全必填信息，再调用工具
- 如果是闲聊或问候，直接回复，不调用工具

## 业务规则（防跳步第三层 - Agent 推理时判断）
1. 创建客户需要：company_name、industry、location、website 四个必填字段
2. 创建项目需要：client_id（客户必须已存在），若缺 client_id 先调用 list_clients
3. 生成问题需要：project_id（项目必须已存在），若缺 project_id 先调用 list_projects；**单次最多生成 30 个问题**，若用户要求超过 30 个（如"生成 40 个"），按 30 个生成并在回复中告知用户已按上限处理
4. 生成文章需要：project_id，且项目下必须有未生成文章的问题；若问题不足先调用 generate_questions；**单次最多生成 10 篇文章、最多基于 10 个问题生成**，若用户要求超过 10 个，按 10 个处理并在回复中告知用户已按上限处理
5. 发布文章需要：article_id 和 account_id；若缺 article_id 先调用 list_articles；若缺 account_id 先调用 list_bindings。展示文章列表时按项目分组，每个项目最多展示 2 篇，标注状态（草稿/生成中/未发布/已排期/发布中/发布成功/发布失败），已发布的文章也可以再次发布
6. 创建基线/复测需要：client_id 和 ai_platforms；若缺 ai_platforms 先追问用户选择
7. 收录监控核心：用用户问题去 AI 平台提问，分析回答，计算 4 个指标（keyword_hit_rate/company_hit_rate/avg_confidence/platform_count）
8. 绑定/发布平台时，如果用户没有指定具体平台，**不要自行编造平台列表**。应先调用 `list_bindings` 查看已绑定账号；若用户要求列出支持的平台，调用 `bind_platform` 并不传 platform，系统会返回完整可选平台
9. 判断账号登录/授权是否有效时，**严禁依据"距今天数"或"last_auth_time（授权时间）"推断过期**——各平台 cookie 有效期规则完全不同，按天数判断必然出错。只能依据：`status == -1`（确定失效）、`session_valid=False`（凭证缺失）。若 `last_check_time` 缺失或较久（>30 天），应如实说"状态较久未验证，建议点一键检测"，**不得断言已过期或登录超期**。真正的有效性只有"用会话在浏览器实际访问一次"才能确认。

## 新手指引流程（强约束 - 防跳步 / 防越界）
- 标准引导为 **6 步线性流程**，必须严格按顺序推进，不可跳过中间步骤：
  1. 建客户 → 2. 建项目 → 3. 生成问题 → 4. 生成文章 → 5. 绑定发布账号 → 6. 审核发布首篇
- **每一步完成后，只引导当前步骤的"下一步"，禁止跳步或引入越界动作**：
  - 建客户完成 → 引导「建项目」（可选先上传资料）
  - 建项目完成 → 引导「生成问题」（可选先上传资料）
  - 生成问题完成 → 引导「生成文章」
  - 生成文章完成 → 引导「绑定发布账号」
  - 绑定账号完成 → 引导「审核发布首篇」
  - 发布完成 → 引导结束（可提示查看发布记录）
  - 上传资料（可选步，非必须）→ 引导回到当前主线步骤（如刚建完客户则回到建项目）
- 「创建收录基线 / 收录监控」**不在**上述 6 步引导流程内，它是一个独立功能。除非用户主动提到"收录 / 基线 / 监控"，否则**任何阶段都不要在引导回复中主动提及或引导它**。
- **严禁**自己编造"接下来可以 / 接下来建议 / 需要我帮你继续哪一步"这类多选项列表（尤其不要把"生成文章""创建收录基线"等越界动作塞进列表）。下一步动作由系统卡片（action 按钮）负责呈现；你的文字回复只需用一两句话肯定本次操作结果，最多自然衔接"下一步该做什么"一句话，不要展开多个后续选项。

## 多轮信息提取（task_context）
当用户分多轮提供信息时（如创建客户），你需要维护 task_context 短期记忆：

1. **首次识别任务**：用户表达意图但信息不全时，开始新任务
2. **每轮追问时更新 task_context**：从用户最新消息中提取已提供的信息，累积到 slots
3. **计算 missing_slots**：根据任务必填字段，列出仍缺失的槽位
4. **信息齐全后调用工具**：所有必填槽位填满后，调用对应工具执行
5. **任务完成后置空**：工具执行成功后，task_context 会被自动清空

### task_context 输出格式（重要！）
**每当你在追问用户补全信息时（即不调用工具、直接回复的场景），必须在回复开头输出 `<task_context>` 标签**，格式如下：

<task_context>{"type": "create_client", "slots": {"company_name": "阿里云"}, "missing_slots": ["industry", "location", "website"]}</task_context>

字段说明：
- `type`: 任务类型，必须是以下之一：create_client / create_project / generate_questions / generate_articles / publish_article / bind_platform / create_baseline / run_recheck / upload_documents
- `slots`: 已收集的槽位键值对（从用户消息中提取，跨轮累积）
- `missing_slots`: 仍缺失的必填槽位名列表

### 各任务的必填槽位
- create_client: company_name, industry, location, website
- create_project: client_id, name, domain_keyword
- generate_questions: project_id
- generate_articles: project_id
- publish_article: article_id, account_id
- bind_platform: platform
- create_baseline: client_id, ai_platforms
- run_recheck: client_id, ai_platforms
- upload_documents: client_id

### 注意事项
- 标签必须放在回复最开头，标签后才是给用户的回复文本
- 调用工具时**不需要**输出 `<task_context>` 标签（工具参数即为完整 slots）
- 标签内的 JSON 必须合法（双引号、无尾逗号）
- 闲聊/问候场景**不需要**输出标签

## 工具调用规则
- 调用工具时不要在 content 中重复工具参数
- 工具结果会通过 ToolMessage 返回给你，你可以基于结果继续推理
- 如果工具返回 need_clarification，按其 suggestion 引导用户补充信息
- 如果工具返回 failed，向用户解释失败原因并给出建议

## 回复规则
- 直接回复时，content 写入最终给用户的回复（不含 <task_context> 标签后的部分）
- 回复要简洁清晰，避免冗长
- 如果需要展示列表/表单/选择器，可以在 reply 中说明，前端会根据 actions 渲染
- **禁止在回复中暴露内部 ID**（如客户ID、项目ID、文章ID等），只展示名称等可读信息
- **回复格式要紧凑**：列表项之间不要加空行；段落之间最多空一行；不要使用大段空白占位
- **发布文章选择列表格式**：当用户想发布文章但缺少 article_id 时，调用 list_articles 后按项目分组展示，每项目最多 2 篇，格式为 `项目名称：1、文章标题（状态） 2、文章标题（状态）`；某项目下无文章时显示 `项目名称：无`；只有一篇时只显示 `1、文章标题（状态）`。状态必须标注：草稿、生成中、未发布、已排期、发布中、发布成功、发布失败。已发布的文章也可再次发布，不要排除。工具返回的 reply 字段已是按上述格式组织好的现成文本，请直接原样呈现给用户，不要重新组织、不要省略任何项目或状态、不要过滤已发布文章。
"""


# ================================================================
#  task_context 标签解析
# ================================================================

# 匹配 <task_context>{...}</task_context> 标签（DOTALL 让 . 匹配换行）
_TASK_CONTEXT_PATTERN = re.compile(
    r"<task_context>\s*(\{.*?\})\s*</task_context>",
    re.DOTALL,
)

# 匹配回复中的内部 ID 模式（用于清理后处理）
_ID_PATTERNS = [
    re.compile(r'(客户\s*ID[：:]\s*\d+)', re.IGNORECASE),
    re.compile(r'(项目\s*ID[：:]\s*\d+)', re.IGNORECASE),
    re.compile(r'(问题\s*ID[：:]\s*\d+)', re.IGNORECASE),
    re.compile(r'(文章\s*ID[：:]\s*\d+)', re.IGNORECASE),
    re.compile(r'(ID[：:]\s*\d+)', re.IGNORECASE),
    re.compile(r'\(ID[：:]\s*\d+\)', re.IGNORECASE),
    re.compile(r'（ID[：:]\s*\d+）', re.IGNORECASE),
]

# 匹配连续空行（3 个及以上换行符）
_MULTI_NEWLINE_PATTERN = re.compile(r'\n{3,}')

# 匹配 bullet/数字列表项之间的空行（•/-/* 或 1. 等标记开头的列表）
_LIST_ITEM_BLANK_PATTERN = re.compile(
    r'((?:^|\n)[ \t]*(?:[•\-\*]|\d+\.)[ \t]+[^\n]+)\n+(?=[ \t]*(?:[•\-\*]|\d+\.)[ \t]+)',
    re.MULTILINE,
)

# 各任务的必填槽位（与 System Prompt 中保持一致）
_REQUIRED_SLOTS: dict[str, list[str]] = {
    "create_client": ["company_name", "industry", "location", "website"],
    "create_project": ["client_id", "name", "domain_keyword"],
    "generate_questions": ["project_id"],
    "generate_articles": ["project_id"],
    "publish_article": ["article_id", "platform"],
    "bind_platform": ["platform"],
    "create_baseline": ["client_id", "ai_platforms"],
    "run_recheck": ["client_id", "ai_platforms"],
    "upload_documents": ["client_id"],
}


# ================================================================
#  Agent 节点
# ================================================================

async def agent_node(state: AgentState) -> dict:
    """ReAct Agent 推理节点。

    使用 LangChain `ChatOpenAI.bind_tools` 实现原生 Tool Calling：
    - LLM 读取 messages（对话历史）+ user_facts（长期记忆）+ task_context（短期记忆）
    - LLM 基于工具 schema 自主决策：调用工具 → 输出 tool_calls；直接回复 → 输出 content
    - 返回 tool_calls（路由到 tools 节点）或 reply（路由到 END）
    """
    from backend.services.agent_v2.tools import build_langchain_tools
    from backend.services.ai_generation_service import get_chat_model

    messages = state.get("messages", []) or []
    user_facts = state.get("user_facts", {}) or {}
    task_context = state.get("task_context")
    user_id = state.get("user_id")

    # 构建 LangChain 消息列表（保留角色边界）
    lc_messages: list[BaseMessage] = [SystemMessage(content=SYSTEM_PROMPT)]

    # 注入长期记忆（user_facts）作为系统上下文
    facts_text = _format_user_facts(user_facts)
    if facts_text:
        lc_messages.append(SystemMessage(content=facts_text))

    # 注入短期记忆（task_context）
    if task_context:
        tc_text = _format_task_context(task_context)
        if tc_text:
            lc_messages.append(SystemMessage(content=tc_text))

    # 加入对话历史（限制最近 20 条避免 token 超限）
    history_msgs = _to_langchain_messages(messages[-20:])
    lc_messages.extend(history_msgs)

    logger.info(
        f"[AGENT] user={user_id} msgs={len(lc_messages)} "
        f"task_context={'yes' if task_context else 'no'} calling LLM with bind_tools..."
    )

    # 调用 LLM：bind_tools 让 LLM 看到结构化 tool definitions，通过原生 Tool Calling 决策
    try:
        llm = get_chat_model()
        tools = build_langchain_tools()
        llm_with_tools = llm.bind_tools(tools)
        response: AIMessage = await llm_with_tools.ainvoke(lc_messages)
    except Exception as e:
        logger.error(f"[AGENT] LLM 调用失败: {e}", exc_info=True)
        return {
            "reply": "抱歉，我暂时无法处理您的请求，请稍后重试。",
            "status": "failed",
            "tool_calls": [],
            "thinking": f"LLM 调用失败: {type(e).__name__}: {e}",
        }

    # 提取思考过程（content 即为思考/回复文本，可能含 <task_context> 标签）
    raw_thinking = (response.content or "").strip()
    tool_calls_raw = response.tool_calls or []

    # 从 content 中解析 LLM 显式输出的 task_context（多轮信息提取核心）
    parsed_tc = _parse_task_context_from_content(raw_thinking)
    # 从回复中移除 <task_context> 标签，得到给用户看的纯净文本
    clean_thinking = _strip_task_context_tag(raw_thinking)

    logger.info(
        f"[AGENT] LLM 决策: tool_calls={len(tool_calls_raw)} "
        f"thinking_len={len(clean_thinking)} "
        f"parsed_tc={'yes' if parsed_tc else 'no'}"
    )

    # 第三层防护：检查工具是否合法
    from backend.services.agent_v2.tools import VALID_TOOLS
    valid_tool_calls: list[dict] = []
    for tc in tool_calls_raw:
        tool_name = tc.get("name", "")
        tool_args = tc.get("args", {}) or {}
        tool_call_id = tc.get("id", "")

        if tool_name not in VALID_TOOLS:
            logger.warning(f"[AGENT] LLM 调用了非法工具: {tool_name}")
            # 不阻断，跳过非法工具，让 LLM 在下一轮看到 ToolMessage 后修正
            continue

        logger.info(f"[AGENT] 调用工具: {tool_name} args={tool_args}")
        valid_tool_calls.append({
            "name": tool_name,
            "args": tool_args,
            "id": tool_call_id,
        })

    # 维护 task_context：
    # - 优先使用 LLM 通过 <task_context> 标签显式输出的（多轮追问场景）
    # - 其次从工具调用推断（任务型工具调用场景）
    # - 其他情况保持当前 task_context
    new_task_context = _infer_task_context(valid_tool_calls, task_context, parsed_tc)

    if parsed_tc:
        logger.info(
            f"[AGENT] task_context 已更新: type={parsed_tc.get('type')} "
            f"slots={list(parsed_tc.get('slots', {}).keys())} "
            f"missing={parsed_tc.get('missing_slots', [])}"
        )

    if valid_tool_calls:
        # 有工具调用 → 路由到 tools 节点
        # 同时把 AIMessage（含 tool_calls）追加到 messages，让 tools_node 能拿到 tool_call_id
        # messages 里存清理后的 content（不含 <task_context> 标签），
        # task_context 已通过 state 单独管理，不需要在 messages 中重复
        # 注意：不设置 reply/actions，让 last_non_empty / add_list reducer 保留之前的值
        return {
            "tool_calls": valid_tool_calls,
            "messages": [_aimessage_to_dict(response, clean_thinking)],
            "thinking": clean_thinking,
            "task_context": new_task_context,
        }

    # 无工具调用 → 直接回复，路由到 END
    reply = clean_thinking or "您好，有什么可以帮您的吗？"
    # 清理回复：移除内部 ID 暴露 + 修复多余空行
    reply = _clean_reply(reply)

    return {
        "reply": reply,
        "tool_calls": [],
        "messages": [_aimessage_to_dict(response, clean_thinking)],
        "status": "completed",
        "thinking": clean_thinking,
        "task_context": new_task_context,
    }


# ================================================================
#  辅助函数
# ================================================================

def _to_langchain_messages(messages: list) -> list[BaseMessage]:
    """把消息列表转换成 LangChain BaseMessage 列表。

    兼容两种输入格式（add_messages reducer 会把 dict 转成 BaseMessage，
    但 Checkpoint 序列化/反序列化后可能仍是 dict）：
    - BaseMessage 对象：直接使用（避免不必要的转换）
    - dict：按 role 转换成对应的 BaseMessage

    保留消息角色边界，让 LLM 能正确理解对话结构。
    """
    result: list[BaseMessage] = []
    for msg in messages:
        # 已经是 BaseMessage → 直接使用
        if isinstance(msg, BaseMessage):
            result.append(msg)
            continue

        # dict 格式 → 按 role 转换
        if not isinstance(msg, dict):
            logger.warning(f"[AGENT] 跳过未知消息类型: {type(msg).__name__}")
            continue

        role = msg.get("role", "user")
        content = msg.get("content", "")
        if not content and role != "tool":
            continue
        if role == "user":
            result.append(HumanMessage(content=content))
        elif role == "assistant":
            # AIMessage 可能带 tool_calls（用于多轮 Tool Calling 上下文）
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                result.append(AIMessage(
                    content=content,
                    tool_calls=[
                        {
                            "name": tc.get("name", ""),
                            "args": tc.get("args", {}) or {},
                            "id": tc.get("id", ""),
                            "type": "tool_call",
                        }
                        for tc in tool_calls
                    ],
                ))
            else:
                result.append(AIMessage(content=content))
        elif role == "system":
            result.append(SystemMessage(content=content))
        elif role == "tool":
            # ToolMessage 需要 tool_call_id 关联到对应的 AIMessage.tool_calls
            result.append(ToolMessage(
                content=content,
                tool_call_id=msg.get("tool_call_id", ""),
            ))
    return result


def _aimessage_to_dict(msg: AIMessage, content_override: str | None = None) -> dict:
    """把 AIMessage 转换回 dict 格式存入 state.messages。

    保留 tool_calls 信息，让 tools_node 能拿到 tool_call_id，
    也让下一轮 agent_node 能正确还原 AIMessage。

    Args:
        msg: AIMessage 对象
        content_override: 可选，覆盖 content（用于存清理后的文本，不含 <task_context> 标签）
    """
    result: dict[str, Any] = {
        "role": "assistant",
        "content": content_override if content_override is not None else (msg.content or ""),
    }
    if msg.tool_calls:
        result["tool_calls"] = [
            {
                "name": tc.get("name", ""),
                "args": tc.get("args", {}) or {},
                "id": tc.get("id", ""),
            }
            for tc in msg.tool_calls
        ]
    return result


def _format_user_facts(facts: dict) -> str:
    """格式化用户事实为 prompt 文本。"""
    parts = []
    if facts.get("company_name"):
        parts.append(f"常用公司：{facts['company_name']}")
    if facts.get("industry"):
        parts.append(f"行业：{facts['industry']}")
    if facts.get("common_platforms"):
        parts.append(f"常用发布平台：{', '.join(facts['common_platforms'])}")
    if not parts:
        return ""
    return "用户事实（长期记忆）：" + "；".join(parts) + "。"


def _clean_reply(text: str) -> str:
    """清理回复文本：移除内部 ID 暴露 + 修复多余空行。

    1. 移除客户ID、项目ID、问题ID、文章ID等内部标识
    2. 将 3 个及以上连续换行压缩为 2 个（美观输出）
    3. 压缩 bullet/数字列表项之间的空行，让列表更紧凑
    """
    if not text:
        return text
    # 移除内部 ID
    for pattern in _ID_PATTERNS:
        text = pattern.sub("", text)
    # 压缩列表项之间的空行（•/-/* 或 1. 等标记开头的列表）
    text = _LIST_ITEM_BLANK_PATTERN.sub(r"\1\n", text)
    # 压缩连续空行（3+ 换行 → 2 换行）
    text = _MULTI_NEWLINE_PATTERN.sub("\n\n", text)
    # 清理行尾多余空格
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return text.strip()


def _format_task_context(task_context: dict) -> str:
    """格式化 task_context 为 prompt 文本。"""
    tc_type = task_context.get("type", "unknown")
    slots = task_context.get("slots", {}) or {}
    missing = task_context.get("missing_slots", []) or []
    parts = [f"当前任务类型：{tc_type}"]
    if slots:
        slots_text = ", ".join(f"{k}={v}" for k, v in slots.items())
        parts.append(f"已收集：{slots_text}")
    if missing:
        parts.append(f"仍缺失：{', '.join(missing)}")
    return "短期记忆（task_context）：" + "；".join(parts) + "。"


# 任务型工具集合：调用这些工具意味着开始一个新任务
# 查询型工具（list_*/get_*）不改变 task_context，因为它们是辅助查询
_TASK_TYPE_TOOLS: set[str] = {
    "create_client", "create_project",
    "generate_questions", "generate_articles",
    "publish_article", "bind_platform",
    "create_baseline", "run_recheck",
    "upload_documents",
}


def _parse_task_context_from_content(content: str) -> dict | None:
    """从 LLM 回复内容中解析 <task_context>{...}</task_context> 标签。

    多轮信息提取的核心：LLM 在追问用户时通过此标签显式输出短期记忆更新，
    agent_node 解析后更新 state.task_context。

    对应 PRD §7.3 记忆流转示例：
        轮次 2: 用户"公司叫阿里云" → Agent 追问 + 输出 task_context 标签
        agent_node 解析标签 → state.task_context.slots = {company_name: "阿里云"}

    Returns:
        解析出的 task_context dict（含 type/slots/missing_slots/created_at），
        如果没有标签或解析失败则返回 None
    """
    match = _TASK_CONTEXT_PATTERN.search(content or "")
    if not match:
        return None
    try:
        tc_json = match.group(1).strip()
        tc = json.loads(tc_json)
        # 基本校验
        if not isinstance(tc, dict):
            return None
        tc_type = tc.get("type")
        if not tc_type or tc_type not in _REQUIRED_SLOTS:
            logger.warning(f"[AGENT] task_context 标签 type 非法: {tc_type}")
            return None
        # 规范化字段
        tc.setdefault("slots", {})
        tc.setdefault("missing_slots", [])
        # 基于 _REQUIRED_SLOTS 自动校验 missing_slots
        required = _REQUIRED_SLOTS[tc_type]
        slots = tc.get("slots", {}) or {}
        tc["missing_slots"] = [k for k in required if k not in slots or slots[k] in (None, "")]
        # 保留已有 created_at（跨轮累积时复用），否则生成新的
        if not tc.get("created_at"):
            tc["created_at"] = datetime.now(timezone.utc).isoformat()
        return tc
    except (json.JSONDecodeError, AttributeError, TypeError) as e:
        logger.warning(f"[AGENT] 解析 <task_context> 标签失败: {e}")
        return None


def _strip_task_context_tag(content: str) -> str:
    """从回复内容中移除 <task_context>...</task_context> 标签。

    标签内的信息已通过 _parse_task_context_from_content 提取到 state.task_context，
    不需要展示给用户。同时清理标签前后多余的空白。
    """
    cleaned = _TASK_CONTEXT_PATTERN.sub("", content or "")
    return cleaned.strip()


def _infer_task_context(
    tool_calls: list[dict],
    current_tc: dict | None,
    parsed_tc: dict | None = None,
) -> dict | None:
    """根据 LLM 输出推断 task_context 更新。

    优先级（对应 PRD §7.3 多轮信息提取）：
    1. LLM 通过 <task_context> 标签显式输出的 task_context（最可靠）
       → 适用于追问用户、多轮信息累积场景
    2. LLM 调用任务型工具时，从工具参数推断 task_context
       → 适用于信息齐全直接调用工具的场景
    3. 其他情况保持当前 task_context
       → 查询型工具调用、闲聊等不改变当前任务

    task_context 由 Checkpointer 自动持久化，跨轮保持。
    任务完成（工具返回 completed/failed）时由 tools_node 清空。
    """
    # 优先使用 LLM 显式输出的 task_context
    if parsed_tc:
        return parsed_tc

    if not tool_calls:
        # 不调用工具且无显式 task_context → 保持当前 task_context
        return current_tc

    # 取第一个工具调用作为当前任务
    first_call = tool_calls[0]
    tool_name = first_call.get("name", "")
    tool_args = first_call.get("args", {}) or {}

    # 只有任务型工具才更新 task_context
    if tool_name in _TASK_TYPE_TOOLS:
        # 如果当前已有同类型 task_context，保留 created_at（避免重置时间）
        # 同时合并已有 slots（LLM 调用工具时可能只传部分参数，复用已收集的）
        created_at = (
            current_tc.get("created_at")
            if current_tc and current_tc.get("type") == tool_name
            else datetime.now(timezone.utc).isoformat()
        )
        # 合并已有 slots：当前 task_context 的 slots + 工具参数（工具参数优先）
        merged_slots: dict[str, Any] = {}
        if current_tc and current_tc.get("type") == tool_name:
            merged_slots.update(current_tc.get("slots", {}) or {})
        merged_slots.update(tool_args)
        # 计算缺失槽位
        required = _REQUIRED_SLOTS.get(tool_name, [])
        missing = [k for k in required if k not in merged_slots or merged_slots[k] in (None, "")]
        return {
            "type": tool_name,
            "slots": merged_slots,
            "missing_slots": missing,
            "created_at": created_at,
        }

    # 查询型工具 → 保持当前 task_context
    return current_tc
