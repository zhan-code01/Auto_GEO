# AutoGeo 智能体架构设计文档

> **版本**: v2.0  
> **最后更新**: 2026-08-06  
> **状态**: 已确认  
> **维护者**: 开发团队

---

## 目录

1. [项目概述](#1-项目概述)
2. [核心架构](#2-核心架构)
3. [技术栈](#3-技术栈)
4. [LangGraph 框架详解](#4-langgraph-框架详解)
5. [State 设计](#5-state-设计)
6. [Checkpoint 机制](#6-checkpoint-机制)
7. [记忆系统](#7-记忆系统)
8. [工具系统](#8-工具系统)
9. [业务流程](#9-业务流程)
10. [防跳步机制](#10-防跳步机制)
11. [前端交互设计](#11-前端交互设计)
12. [长任务处理](#12-长任务处理)
13. [不稳定环节与风险](#13-不稳定环节与风险)
14. [实施计划](#14-实施计划)
15. [附录](#15-附录)

---

## 1. 项目概述

### 1.1 项目背景

AutoGeo 是一个自动化内容生成和发布平台，核心功能包括：
- 客户管理
- 项目管理
- 用户问题生成
- 文章生成
- 多平台发布
- 收录监控（AI 可见度评估）

### 1.2 智能体目标

构建一个**对话式智能助手**，通过自然语言交互完成以下任务：
- 引导用户完成业务流程（创建客户 → 生成问题 → 生成文章 → 发布）
- 多轮对话收集信息（如创建客户时需要公司名称、行业、地址、官网）
- 主动引导用户按最佳实践操作
- 支持长任务（多步骤任务自动编排）
- 收录监控：用用户问题去 AI 平台提问，评估 AI 可见度

### 1.3 设计原则

1. **轻量级架构**：单 Agent + ReAct 循环，避免过度工程化
2. **状态持久化**：使用 Checkpoint 支持多轮对话和中断恢复
3. **工具驱动**：通过工具封装业务逻辑，Agent 负责推理和决策
4. **防跳步机制**：三层防护确保业务规则不被违反
5. **用户友好**：弹窗、表单等交互方式降低使用门槛
6. **复用现有 API**：工具直接调用 service 层，不重写 API

---

## 2. 核心架构

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                         前端层                                   │
│  Vue 3 + TypeScript + Element Plus + Electron                   │
│  - 对话界面（自然语言交互）                                      │
│  - 渲染 Agent 回复和 actions                                     │
│  - 处理弹窗、表单等交互                                          │
│  - 展示 Agent 思考过程（如"正在查询客户列表..."）                │
└─────────────────────────────────────────────────────────────────┘
                              ↓ SSE / WebSocket
┌─────────────────────────────────────────────────────────────────┐
│                         API 层                                   │
│  FastAPI                                                         │
│  - 接收用户消息                                                  │
│  - 流式返回 Agent 回复                                           │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                       Agent 层                                   │
│  LangGraph + ReAct Agent                                         │
│  ┌──────────┐      ┌──────────┐      ┌──────────┐              │
│  │  Agent   │ ───> │  Tools   │ ───> │  Agent   │              │
│  │  (LLM)   │ <─── │ (执行)   │ <─── │  (LLM)   │              │
│  └──────────┘      └──────────┘      └──────────┘              │
│       ↑                                  ↑                       │
│       └────────── State ─────────────────┘                       │
│                      ↓                                           │
│              Checkpoint (持久化)                                 │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                        LLM 层                                    │
│  DeepSeek / OpenAI / 其他                                        │
│  - 意图识别                                                      │
│  - 信息提取                                                      │
│  - 决策推理                                                      │
│  - 回复生成                                                      │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                       工具层（18 个工具）                         │
│  直接调用 Service 层（不经过 HTTP）                              │
│  - 客户管理、项目管理、智能文章、账户绑定、发布、收录监控        │
│  - Pydantic 参数验证                                             │
│  - 前置条件校验                                                  │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                       数据层                                     │
│  PostgreSQL + SQLAlchemy                                         │
│  - 业务数据（客户、项目、文章等）                                │
│  - Checkpoint 持久化                                             │
│  - 长期记忆（user_facts）                                        │
│  - 对话历史（conversation_messages）                             │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 核心组件

| 组件 | 职责 | 技术实现 |
|------|------|----------|
| **LangGraph** | Agent 编排、状态管理、Checkpoint | StateGraph + PostgresSaver |
| **ReAct Agent** | 推理、决策、回复 | LLM + Tool Calling |
| **State** | 保存对话历史、任务上下文、用户事实 | TypedDict |
| **Checkpoint** | 持久化 State，支持跨请求保持 | PostgresSaver |
| **Tools** | 直接调用 Service 层执行业务逻辑 | @tool 装饰器 + Pydantic |
| **Pydantic** | 参数验证、必填控制 | BaseModel + Field |
| **Actions** | 前端交互指令（弹窗、表单等） | 结构化 JSON |

### 2.3 关键设计决策

| 决策 | 选择 | 原因 |
|------|------|------|
| 工具调用方式 | 直接调用 Service 层 | 同进程性能更好，不经过 HTTP 序列化 |
| 弹窗触发方式 | Agent 返回 action，前端渲染 | 解耦前后端，Agent 只需返回结构化数据 |
| 上下文管理 | Checkpoint + 三层记忆 | LangGraph 自动管理，支持中断恢复 |
| 思考过程展示 | 前端展示 Agent 思考过程 | 用户体验更好，类似 ChatGPT 的 thinking 状态 |
| 文章生成入口 | 只有一个 generate_articles | 避免重复工具，简化设计 |

---

## 3. 技术栈

### 3.1 核心技术栈

| 技术 | 版本 | 用途 | 稳定性 |
|------|------|------|--------|
| **LangGraph** | 0.2+ | Agent 编排框架 | 较稳定 |
| **LangChain** | 0.2+ | 工具调用、LLM 封装 | 较稳定 |
| **DeepSeek** | - | LLM 推理 | 不稳定（API 可能波动） |
| **Pydantic** | 2.0+ | 参数验证 | 非常稳定 |
| **FastAPI** | 0.100+ | API 服务 | 非常稳定 |
| **PostgreSQL** | 14+ | 数据存储 | 非常稳定 |
| **Vue 3** | 3.3+ | 前端框架 | 非常稳定 |
| **TypeScript** | 5.0+ | 前端类型系统 | 非常稳定 |
| **Element Plus** | 2.4+ | UI 组件库 | 稳定 |
| **Electron** | 25+ | 桌面端 | 稳定 |

### 3.2 不稳定环节

| 环节 | 风险等级 | 主要问题 | 缓解措施 |
|------|----------|----------|----------|
| **LLM 推理** | 中等 | 意图误解、信息提取错误 | 优化 prompt、few-shot、置信度阈值 |
| **多轮对话状态管理** | 中等 | 记忆丢失、状态错乱 | Checkpoint、持久化、状态转换 |
| **工具调用错误处理** | 低 | 执行失败、前置条件不满足 | 错误处理、重试机制 |
| **前端交互** | 中等 | 组件复杂、状态同步 | 组件化、状态管理、错误处理 |

---

## 4. LangGraph 框架详解

### 4.1 LangGraph 是什么

LangGraph 是一个用于构建**有状态、多步骤 Agent** 的框架，核心特性：
- **状态图（StateGraph）**：定义节点和边，描述 Agent 的执行流程
- **状态管理（State）**：保存 Agent 的完整状态
- **Checkpoint**：自动持久化状态，支持中断恢复
- **条件路由**：根据状态决定下一步行动

### 4.2 为什么选择 LangGraph

| 方案 | 优点 | 缺点 | 适用场景 |
|------|------|------|----------|
| **LangChain Agent** | 简单 | 无 Checkpoint，状态管理弱 | 简单任务 |
| **LangGraph** | 状态管理强，支持 Checkpoint | 学习曲线稍陡 | 复杂多步骤任务 |
| **自研框架** | 完全控制 | 工作量大 | 特殊需求 |

**选择 LangGraph 的理由**：
1. **Checkpoint 支持**：自动保存对话状态，支持多轮对话和中断恢复
2. **状态管理**：自动管理 Agent 和 Tools 之间的状态传递
3. **生产级框架**：已经过生产验证，稳定可靠

### 4.3 LangGraph 核心概念

#### StateGraph（状态图）

```python
from langgraph.graph import StateGraph

builder = StateGraph(AgentState)
builder.add_node("agent", agent_node)
builder.add_node("tools", tool_node)
builder.add_edge("agent", "tools")
builder.add_edge("tools", "agent")
builder.set_entry_point("agent")
graph = builder.compile(checkpointer=checkpointer)
```

#### 节点（Node）

```python
def agent_node(state: AgentState) -> AgentState:
    """Agent 节点：LLM 推理"""
    messages = state["messages"]
    task_context = state["task_context"]
    response = llm.invoke(messages)
    return {
        "messages": messages + [response],
        "tool_calls": response.tool_calls
    }

def tool_node(state: AgentState) -> AgentState:
    """Tools 节点：执行工具"""
    tool_calls = state["tool_calls"]
    results = []
    for tool_call in tool_calls:
        result = execute_tool(tool_call)
        results.append(result)
    return {"tool_results": results}
```

#### Checkpoint

```python
from langgraph.checkpoint.postgres import PostgresSaver

checkpointer = PostgresSaver(engine)
graph = builder.compile(checkpointer=checkpointer)

config = {"configurable": {"thread_id": "session-123"}}
result = graph.invoke(state, config=config)
```

### 4.4 LangGraph 在 AutoGeo 中的应用

```python
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres import PostgresSaver

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    task_context: dict | None
    user_facts: dict
    tool_calls: list[dict]
    reply: str | None
    actions: list[dict] | None

def agent_node(state: AgentState) -> AgentState:
    messages = state["messages"]
    task_context = state["task_context"]
    user_facts = state["user_facts"]
    prompt = build_prompt(messages, task_context, user_facts)
    response = llm.invoke(prompt)
    return {
        "messages": messages + [response],
        "tool_calls": response.tool_calls,
        "reply": response.content,
        "actions": response.actions
    }

def tool_node(state: AgentState) -> AgentState:
    tool_calls = state["tool_calls"]
    results = []
    for tool_call in tool_calls:
        result = execute_tool(tool_call)
        results.append(result)
    return {"tool_results": results}

builder = StateGraph(AgentState)
builder.add_node("agent", agent_node)
builder.add_node("tools", tool_node)

def should_continue(state: AgentState) -> str:
    if state.get("tool_calls"):
        return "tools"
    return END

builder.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
builder.add_edge("tools", "agent")
builder.set_entry_point("agent")

checkpointer = PostgresSaver(engine)
graph = builder.compile(checkpointer=checkpointer)
```

---

## 5. State 设计

### 5.1 State 的作用

1. **状态管理**：保存 Agent 的完整状态
2. **Checkpoint 支持**：State 是 Checkpoint 的基础
3. **工具调用循环**：Agent 和 Tools 之间传递信息
4. **条件路由**：根据 State 决定下一步行动

### 5.2 State 结构定义

```python
from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    """AutoGeo Agent 状态定义"""
    
    # ===== 对话历史（工作记忆） =====
    messages: Annotated[list, add_messages]
    # 自动管理，保存所有对话消息
    # 示例: [{"role": "user", "content": "帮我创建一个客户"}]
    
    # ===== 任务上下文（短期记忆） =====
    task_context: dict | None
    # 保存当前任务的状态，用于多轮对话
    # 示例: {
    #   "type": "create_client",
    #   "slots": {"company_name": "阿里云"},
    #   "missing_slots": ["industry", "location", "website"]
    # }
    
    # ===== 用户事实（长期记忆） =====
    user_facts: dict
    # 保存用户的事实性知识，跨会话持久化
    # 示例: {
    #   "last_client_id": 123,
    #   "last_project_id": 456,
    #   "bound_platforms": ["douyin", "baijiahao"]
    # }
    
    # ===== 工具调用相关 =====
    tool_calls: list[dict]
    # LangGraph 自动管理，保存 Agent 决定调用的工具
    # 示例: [{"name": "create_client", "args": {"company_name": "阿里云"}}]
    
    tool_results: list[dict]
    # 工具执行结果
    # 示例: [{"success": True, "client_id": 123}]
    
    # ===== 输出 =====
    reply: str | None
    # Agent 的回复内容
    # 示例: "客户创建成功！客户ID: 123"
    
    actions: list[dict] | None
    # 交互按钮（弹窗、表单等）
    # 示例: [{"type": "show_client_list", "label": "查看客户列表", "payload": {...}}]
```

### 5.3 State 的流转

```
用户消息 → Agent 节点 → 更新 State → 条件路由
              ↑                          ↓
              └──── Tools 节点 ←─────────┘
```

**详细流程**：

1. **用户发送消息** → State 更新: `messages` 新增用户消息
2. **Agent 节点推理** → 读取 State，LLM 推理，更新 State
3. **条件路由** → 有 `tool_calls` 进入 Tools 节点，否则结束
4. **Tools 节点执行** → 执行工具，更新 `tool_results`
5. **回到 Agent 节点** → 读取结果，LLM 推理，更新 `reply`

---

## 6. Checkpoint 机制

### 6.1 Checkpoint 是什么

Checkpoint 是 LangGraph 的**状态持久化机制**，用于：
- 在对话过程中自动保存 Agent 的状态
- 支持中断和恢复对话
- 支持跨会话保持上下文
- 支持回溯到历史状态

### 6.2 Checkpoint 的使用方式

```python
from langgraph.checkpoint.postgres import PostgresSaver

checkpointer = PostgresSaver(engine)
graph = builder.compile(checkpointer=checkpointer)

# 运行图（传入 thread_id）
config = {"configurable": {"thread_id": "session-123"}}
result = graph.invoke(state, config=config)

# 下次请求时，自动加载 Checkpoint
result = graph.invoke(new_state, config=config)
```

### 6.3 Checkpoint 在 AutoGeo 中的应用

#### 场景 1：多轮对话创建客户

```
轮次 1: 用户: 帮我创建一个客户
  Checkpoint 保存: task_context = {type: "create_client", slots: {}}

轮次 2: 用户: 公司叫阿里云
  Checkpoint 更新: task_context.slots = {company_name: "阿里云"}

轮次 3: 用户: 做云计算的，在杭州
  Checkpoint 更新: task_context.slots = {company_name, industry, location}

轮次 4: 用户: 官网是 www.aliyun.com
  Checkpoint 更新: task_context = null（任务完成）
```

#### 场景 2：对话中断恢复

```
轮次 1: 用户: 帮我创建一个客户
  Checkpoint 保存

用户关闭浏览器（对话中断）

第二天用户回来:
  用户: 继续创建客户
  LangGraph 自动加载 Checkpoint
  Agent 知道之前在创建客户，继续追问
```

### 6.4 Checkpointer 选择

| Checkpointer | 存储位置 | 持久化 | 并发支持 | 适用场景 |
|--------------|----------|--------|----------|----------|
| **MemorySaver** | 内存 | 否 | 否 | 开发环境 |
| **SqliteSaver** | SQLite | 是 | 有限 | 单机部署 |
| **PostgresSaver** | PostgreSQL | 是 | 是 | 生产环境 |

**AutoGeo 选择**：PostgresSaver（生产环境）

### 6.5 Checkpoint 优化

#### 限制 messages 长度

```python
def trim_messages(messages: list, max_length: int = 20) -> list:
    """只保留最近 N 条消息"""
    if len(messages) > max_length:
        return messages[-max_length:]
    return messages
```

---

## 7. 记忆系统

### 7.1 三层记忆模型

```
┌─────────────────────────────────────────┐
│          工作记忆 (Working Memory)        │
│  - 对话历史 (messages)                   │
│  - 由 Checkpoint 自动管理               │
│  - 生命周期：单次会话                     │
└─────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────┐
│         短期记忆 (Short-term Memory)      │
│  - 当前任务状态 (task_context)           │
│  - 由 Checkpoint 自动管理               │
│  - 生命周期：任务完成后清除               │
└─────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────┐
│         长期记忆 (Long-term Memory)       │
│  - 用户事实 (user_facts)                 │
│  - 手动管理（工具执行后更新）            │
│  - 生命周期：永久                         │
└─────────────────────────────────────────┘
```

### 7.2 各层记忆详解

#### 7.2.1 工作记忆（Working Memory）

**存储内容**：对话历史（messages）  
**存储位置**：Checkpoint（自动管理）  
**生命周期**：单次会话  
**用途**：LLM 需要看到完整的对话历史才能理解上下文，支持多轮对话

#### 7.2.2 短期记忆（Short-term Memory）

**存储内容**：当前任务状态（task_context）  
**存储位置**：Checkpoint（自动管理）  
**生命周期**：任务完成后清除  
**用途**：多轮对话中，Agent 需要知道当前在做什么任务，保存用户分多轮提供的信息

```python
task_context = {
    "type": "create_client",
    "slots": {
        "company_name": "阿里云",
        "industry": "云计算"
    },
    "missing_slots": ["location", "website"]
}
```

#### 7.2.3 长期记忆（Long-term Memory）

**存储内容**：用户事实（user_facts）  
**存储位置**：数据库（user_facts 表）  
**生命周期**：永久  
**用途**：保存用户的事实性知识，支持个性化推荐

```python
user_facts = {
    "last_client_id": 123,
    "last_project_id": 456,
    "bound_platforms": ["douyin", "baijiahao"],
    "preferred_article_count": 5,
    "has_uploaded_documents": True
}
```

### 7.3 记忆流转示例

**场景**：用户创建客户

```
轮次 1:
  用户: 我想创建一个新客户
  Agent 推理:
    - 读取短期记忆: task_context = null
    - 读取长期记忆: user_facts = {}
    - 判断: 需要创建客户，但缺少必填信息
    - 决策: 追问
  Agent: 好的，请提供公司名称、所属行业、所在地、公司官网
  记忆更新: task_context = {type: "create_client", slots: {}}

轮次 2:
  用户: 公司叫阿里云，做云计算的
  Agent 推理:
    - 读取短期记忆: task_context.slots = {}
    - 从消息提取: company_name = "阿里云", industry = "云计算"
    - 更新短期记忆: task_context.slots = {company_name, industry}
    - 判断: 还缺 location 和 website
    - 决策: 追问
  Agent: 还需要所在地和公司官网
  记忆更新: task_context.slots = {company_name, industry}

轮次 3:
  用户: 在杭州，官网是 www.aliyun.com
  Agent 推理:
    - 读取短期记忆: task_context.slots = {company_name, industry}
    - 从消息提取: location = "杭州", website = "www.aliyun.com"
    - 更新短期记忆: task_context.slots = {company_name, industry, location, website}
    - 判断: 所有必填槽位已填充
    - 决策: 执行工具
  Agent 调用: create_client(...)
  工具返回: {success: true, client_id: 123}
  Agent: 客户创建成功！
  记忆更新: 
    - task_context = null（任务完成）
    - user_facts.last_client_id = 123（长期记忆更新）
```

---

## 8. 工具系统

### 8.1 工具设计原则

1. **职责单一**：每个工具只做一件事
2. **直接调用 Service 层**：不经过 HTTP，性能更好
3. **参数验证**：使用 Pydantic 验证参数类型和必填
4. **前置条件校验**：工具执行前检查业务规则
5. **结构化返回**：返回统一的结果格式
6. **复用现有 API**：所有工具封装已有的 Service 层方法

### 8.2 工具定义方式

```python
from langchain_core.tools import tool
from pydantic import BaseModel, Field

class CreateClientInput(BaseModel):
    """创建客户的输入参数"""
    company_name: str = Field(description="公司名称，必填")
    industry: str = Field(description="所属行业，必填")
    location: str = Field(description="所在地，必填")
    website: str = Field(description="公司官网，必填")

@tool(args_schema=CreateClientInput)
def create_client(company_name: str, industry: str, location: str, website: str) -> dict:
    """创建客户。当用户想要创建新客户时调用此工具。"""
    # 直接调用 Service 层
    from backend.services.client_service import ClientService
    service = ClientService(db)
    client = service.create_client(company_name, industry, location, website)
    return {
        "success": True,
        "client_id": client.id,
        "message": f"客户 {company_name} 创建成功"
    }
```

### 8.3 工具清单（18 个）

#### 8.3.1 客户管理（3 个工具）

| 工具名 | 用途 | 对应前端 API | 对应后端路由 | 前端交互 |
|--------|------|-------------|-------------|----------|
| `create_client` | 创建客户 | `clientApi.create` | `POST /api/clients` | 信息完整→直接创建；不全→按钮触发表单弹窗 |
| `list_clients` | 查询客户列表 | `clientApi.getList` | `GET /api/clients` | **列表弹窗**（分页表格） |
| `get_client_detail` | 查询客户详情 | `clientApi.getDetail` | `GET /api/clients/{id}` | 文字回复 |

#### 8.3.2 项目管理（3 个工具）

| 工具名 | 用途 | 对应前端 API | 对应后端路由 | 前端交互 |
|--------|------|-------------|-------------|----------|
| `create_project` | 创建项目 | `geoKeywordApi.createProject` | `POST /api/keywords/projects` | 同 create_client 逻辑 |
| `list_projects` | 查询项目列表 | `geoKeywordApi.getProjects` | `GET /api/keywords/projects` | **列表弹窗**（分页表格） |
| `get_project_detail` | 查询项目详情 | `geoKeywordApi.getProject` | `GET /api/keywords/projects/{id}` | 文字回复 |

#### 8.3.3 智能文章生成（4 个工具）

| 工具名 | 用途 | 对应前端 API | 对应后端路由 | 前端交互 |
|--------|------|-------------|-------------|----------|
| `generate_questions` | 生成用户问题 | `smartArticleApi.generateQuestions` | `POST /api/smart-articles/question-batches` | 文字回复"任务已提交" |
| `list_questions` | 查询问题列表 | `smartArticleApi.getQuestions` | `GET /api/smart-articles/questions` | **列表弹窗**（分页，可选择问题生成文章） |
| `generate_articles` | 智能文章生成（唯一入口） | `smartArticleApi.generate` | `POST /api/smart-articles/generate` | 文字回复"任务已提交" |
| `list_articles` | 查询文章列表 | `smartArticleApi.getArticles` | `GET /api/smart-articles/articles` | **列表弹窗**（分页，可选择文章发布） |

**说明**：只有一个文章生成入口 `generate_articles`，对应前端保留的 `smartArticleApi.generate` 接口。

#### 8.3.4 账户绑定（2 个工具）

| 工具名 | 用途 | 对应前端 API | 对应后端路由 | 前端交互 |
|--------|------|-------------|-------------|----------|
| `bind_platform` | 绑定平台账户 | `accountApi.startAuth` | `POST /api/accounts/auth/start` | **平台选择弹窗**（选择要绑定的平台） |
| `list_bindings` | 查询已绑定账户 | `accountApi.getList` | `GET /api/accounts` | 文字回复已绑定平台列表 |

#### 8.3.5 文章发布（2 个工具）

| 工具名 | 用途 | 对应前端 API | 对应后端路由 | 前端交互 |
|--------|------|-------------|-------------|----------|
| `publish_article` | 发布文章（单篇单平台） | `publishApi.create` | `POST /api/publish/create` | **选择弹窗**（选文章 + 账号） |
| `list_publish_records` | 查询发布记录 | `publishApi.getRecords` | `GET /api/publish/records` | **列表弹窗**（发布记录） |

**说明**：MVP 只支持单篇文章发布到单个平台，简化上手难度。

#### 8.3.6 收录监控（3 个工具）

| 工具名 | 用途 | 对应前端 API | 对应后端路由 | 前端交互 |
|--------|------|-------------|-------------|----------|
| `create_baseline` | 创建基线（使用前） | `geoEvaluationApi.createBaseline` | `POST /api/geo-evaluation/projects/{id}/baseline` | **AI 平台选择弹窗**（豆包/通义千问/DeepSeek） |
| `run_recheck` | 执行复测（使用后） | `geoEvaluationApi.runRecheck` | `POST /api/geo-evaluation/projects/{id}/recheck` | **AI 平台选择弹窗**（同上） |
| `get_diagnosis` | 获取诊断指标 | `geoEvaluationApi.getDiagnosis` | `GET /api/geo-evaluation/projects/{id}/diagnosis` | **指标卡片**（展示 4 个核心指标） |

**收录监控核心逻辑**：
- 用**用户问题**去 AI 平台提问（不是监测特定文章）
- 分析 AI 回答，计算 4 个核心指标
- 对比基线（使用前）和复测（使用后）的变化

**4 个核心指标**：
1. **关键词命中率** (`keyword_hit_rate`) - 用户问题的关键词在 AI 回答中的命中情况
2. **公司名提及率** (`company_hit_rate`) - 公司名称在 AI 回答中被提及的比例
3. **平均置信度** (`avg_confidence`) - AI 回答的置信度评分
4. **覆盖平台** (`platform_count`) - 监测的 AI 平台数量

#### 8.3.7 资料管理（1 个工具）

| 工具名 | 用途 | 对应前端 API | 对应后端路由 | 前端交互 |
|--------|------|-------------|-------------|----------|
| `upload_documents` | 上传客户资料 | `clientApi.uploadFiles` | `POST /api/knowledge/upload` | **文件上传弹窗** |

### 8.4 工具汇总

| 模块 | 工具数 | 工具列表 |
|------|--------|---------|
| 客户管理 | 3 | create_client, list_clients, get_client_detail |
| 项目管理 | 3 | create_project, list_projects, get_project_detail |
| 智能文章 | 4 | generate_questions, list_questions, generate_articles, list_articles |
| 账户绑定 | 2 | bind_platform, list_bindings |
| 文章发布 | 2 | publish_article, list_publish_records |
| 收录监控 | 3 | create_baseline, run_recheck, get_diagnosis |
| 资料管理 | 1 | upload_documents |
| **合计** | **18** | |

### 8.5 工具的前置条件校验（三层防护）

**第一层：工具 docstring（LLM 推理时）**

```python
@tool
def generate_articles(question_ids: list[int]) -> dict:
    """从指定问题生成文章。
    
    前置条件：
    - question_ids 必须存在
    - question_ids 中的问题必须未生成过文章
    
    如果没有问题，请先调用 generate_questions 工具生成问题。
    """
    ...
```

**第二层：工具执行时校验**

```python
@tool
def generate_articles(question_ids: list[int]) -> dict:
    questions = db.query(Question).filter(Question.id.in_(question_ids)).all()
    invalid = [q.id for q in questions if q.has_article]
    if invalid:
        return {
            "success": False,
            "error_type": "questions_not_ready",
            "message": f"以下问题已生成过文章: {invalid}",
            "suggestion": "请先规划新问题，或选择其他问题"
        }
    ...
```

**第三层：Agent 推理时判断**

Agent 在推理时检查业务规则，如果前置条件不满足，不会调用工具，而是主动引导用户。

### 8.6 工具返回格式

```python
# 成功
{
    "success": True,
    "data": {...},
    "message": "操作成功"
}

# 失败
{
    "success": False,
    "error_type": "validation_error",
    "message": "参数错误",
    "suggestion": "请检查参数"
}

# 前置条件不满足
{
    "success": False,
    "error_type": "questions_not_ready",
    "message": "以下问题已生成过文章: [1, 2, 3]",
    "suggestion": "请先规划新问题，或选择其他问题"
}
```

---

## 9. 业务流程

### 9.1 核心业务流程

```
创建客户
    ↓
（推荐）上传客户资料 ← 可以在任何时候进行
    ↓
新增项目
    ↓
生成用户问题
    ↓
生成文章（唯一入口：generate_articles）
    ↓
绑定账户 ← 可以在任何时候进行
    ↓
发布文章（单篇单平台）
```

### 9.2 收录监控流程

```
选择项目
    ↓
选择 AI 平台（豆包/通义千问/DeepSeek）
    ↓
创建基线（使用前）或 执行复测（使用后）
    ↓
系统用用户问题去 AI 平台提问
    ↓
分析 AI 回答，计算 4 个核心指标
    ↓
展示指标卡片（关键词命中率、公司名提及率、平均置信度、覆盖平台）
```

### 9.3 发布流程

```
选择文章（列表弹窗）
    ↓
选择目标平台/账号（选择弹窗）
    ↓
创建发布任务（单篇单平台）
    ↓
文字回复"任务已创建"
```

### 9.4 Agent 引导逻辑

#### 9.4.1 创建客户后的引导

```
用户: 帮我创建一个客户
Agent: 好的，请提供公司名称、所属行业、所在地、公司官网
用户: （提供信息）
Agent: 客户创建成功！

推荐您上传一些客户资料，这样生成的问题和文章会更贴合客户业务。
您可以现在上传，也可以稍后再上传。

[上传资料] [稍后再说]
```

#### 9.4.2 生成文章后的引导

```
用户: 帮我生成5篇文章
Agent: 已为项目生成5篇文章，任务已提交。

文章生成完成后，您可以绑定平台账户并发布文章。

[绑定平台] [稍后再说]
```

#### 9.4.3 收录监控的引导

```
用户: 帮我监控收录情况
Agent: 请问要监控哪个项目？
用户: 阿里云ECS项目
Agent: 请选择要监测的 AI 平台：

[选择 AI 平台]  ← 弹窗：豆包、通义千问、DeepSeek

用户选择后：
Agent: 好的，正在为阿里云ECS项目创建基线，监测平台：豆包、通义千问。
      系统将使用项目中的用户问题去这些平台提问，分析 AI 回答中的收录情况。
      任务已提交，完成后会展示 4 个核心指标。
```

---

## 10. 防跳步机制

### 10.1 三层防护

```
┌─────────────────────────────────────────┐
│  第一层：工具 docstring 约束             │
│  - 在 docstring 中明确前置条件           │
│  - LLM 在推理时会读取 docstring         │
└─────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────┐
│  第二层：工具执行时校验                  │
│  - 工具在执行前检查前置条件              │
│  - 不满足时返回结构化错误                │
└─────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────┐
│  第三层：Agent 推理时判断                │
│  - Agent 在推理时检查业务规则            │
│  - 如果前置条件不满足，不会调用工具      │
│  - 主动引导用户完成前置步骤              │
└─────────────────────────────────────────┘
```

### 10.2 实际场景

**场景**：用户说"生成5篇文章"

```
Agent 推理:
  - 意图: generate_articles
  - 参数: count=5
  - 检查前置条件: 需要 project_id 或 question_ids
  - 判断: 缺少必要信息
  - 决策: 追问

Agent: 请问是为哪个项目生成文章？或者您想从哪些问题生成？

用户: 阿里云项目

Agent 推理:
  - 更新参数: project_id="阿里云项目"
  - 检查前置条件: project_id 已提供
  - 决策: 执行工具

Agent 调用: generate_articles(project_id=123, article_count=5)
工具执行:
  - 检查 project_id 是否存在 → 存在
  - 提交文章生成任务
  - 返回: {success: true, batch_id: 456}

Agent: 已为阿里云项目生成5篇文章，任务已提交。
```

---

## 11. 前端交互设计

### 11.1 Action 结构

Agent 的回复不仅包含文本，还包含**结构化的 actions**。前端根据 actions 的类型渲染不同的交互组件。

```python
{
    "reply": "请选择要发布到的平台",
    "actions": [
        {
            "type": "select_platform",           # action 类型
            "label": "选择平台",                  # 按钮文案
            "payload": {
                "title": "选择发布平台",          # 弹窗标题
                "options": [                     # 下拉框选项
                    {"value": "douyin", "label": "抖音", "account": "account1"},
                    {"value": "baijiahao", "label": "百家号", "account": "account2"}
                ],
                "multiple": False,               # 是否多选
                "confirm_text": "确认发布"        # 确认按钮文案
            },
            "interaction": "modal"               # 交互方式：弹窗
        }
    ]
}
```

### 11.2 前端弹窗类型（4 种）

| 弹窗类型 | 使用场景 | 说明 |
|----------|---------|------|
| **列表弹窗** | list_clients, list_projects, list_questions, list_articles, list_publish_records | 分页表格展示，可选择操作 |
| **表单弹窗** | create_client, create_project（信息不全时按钮触发） | 结构化表单输入 |
| **选择弹窗** | bind_platform, publish_article, create_baseline, run_recheck | 从选项中选择 |
| **指标卡片** | get_diagnosis（展示 4 个核心指标） | 展示关键词命中率、公司名提及率、平均置信度、覆盖平台 |

### 11.3 支持的 Action 类型

| type | 用途 | 前端渲染 |
|------|------|----------|
| `show_client_list` | 展示客户列表 | 列表弹窗 |
| `show_project_list` | 展示项目列表 | 列表弹窗 |
| `show_question_list` | 展示问题列表 | 列表弹窗（可选择问题生成文章） |
| `show_article_list` | 展示文章列表 | 列表弹窗（可选择文章发布） |
| `show_publish_records` | 展示发布记录 | 列表弹窗 |
| `show_client_form` | 填写客户信息 | 表单弹窗 |
| `show_project_form` | 填写项目信息 | 表单弹窗 |
| `select_platform` | 选择平台 | 选择弹窗 |
| `select_ai_platform` | 选择 AI 平台 | 选择弹窗（豆包/通义千问/DeepSeek） |
| `select_account` | 选择账号 | 选择弹窗 |
| `show_diagnosis` | 展示诊断指标 | 指标卡片（4 个核心指标） |
| `upload_files` | 上传文件 | 文件上传弹窗 |
| `confirm` | 确认操作 | 确认对话框 |

### 11.4 表单引导（创建客户）

```python
{
    "reply": "好的，请填写客户信息",
    "actions": [
        {
            "type": "show_client_form",
            "label": "填写客户信息",
            "payload": {
                "title": "创建客户",
                "fields": [
                    {"name": "company_name", "label": "公司名称", "type": "text", "required": True},
                    {"name": "industry", "label": "所属行业", "type": "select", "required": True},
                    {"name": "location", "label": "所在地", "type": "text", "required": True},
                    {"name": "website", "label": "公司官网", "type": "text", "required": True}
                ],
                "confirm_text": "创建客户"
            },
            "interaction": "modal"
        }
    ]
}
```

### 11.5 指标卡片（收录监控结果）

```python
{
    "reply": "阿里云ECS项目的收录监控结果如下：",
    "actions": [
        {
            "type": "show_diagnosis",
            "label": "查看诊断结果",
            "payload": {
                "project_name": "阿里云ECS",
                "metrics": {
                    "keyword_hit_rate": 75.5,       # 关键词命中率 (%)
                    "company_hit_rate": 60.2,       # 公司名提及率 (%)
                    "avg_confidence": 0.82,         # 平均置信度 (0-1)
                    "platform_count": 3             # 覆盖平台数
                },
                "baseline": {                        # 基线对比（如果有）
                    "keyword_hit_rate": 45.0,
                    "company_hit_rate": 30.0,
                    "avg_confidence": 0.65,
                    "platform_count": 2
                }
            },
            "interaction": "card"
        }
    ]
}
```

### 11.6 前端渲染流程

```
用户: 帮我创建一个客户
Agent: 好的，请填写客户信息
      [填写客户信息]  ← 点击后弹出表单

弹窗内容:
┌─────────────────────────────┐
│  创建客户                      │
├─────────────────────────────┤
│  公司名称: [________________] │
│  所属行业: [下拉框 ▼]         │
│  所在地:   [________________] │
│  公司官网: [________________] │
│                              │
│  [取消]  [创建客户]           │
└─────────────────────────────┘

用户填写后，前端将表单数据发送回 Agent:
用户: （通过表单提交）
      company_name: 阿里云
      industry: 云计算
      location: 杭州
      website: www.aliyun.com

Agent: 客户创建成功！
```

### 11.7 Agent 思考过程展示

前端展示 Agent 的思考过程，类似 ChatGPT 的 thinking 状态：

```
用户: 帮我发布文章到抖音

Agent 思考过程（展示给用户）:
  🔍 正在查询文章列表...
  🔍 正在检查已绑定的平台...
  ✓ 找到 5 篇可发布的文章
  ✓ 抖音平台已绑定

Agent: 请选择要发布的文章：
      [选择文章]  ← 点击后弹出列表弹窗
```

---

## 12. 长任务处理

### 12.1 长任务的本质

长任务是**多个工具的组合使用**，Agent 通过推理自动编排工具调用顺序。

### 12.2 长任务示例

**场景**：用户说"帮我给阿里云的ECS项目生成5篇文章，发布到抖音"

```
Agent 推理:
  1. 理解意图: 生成文章并发布（组合任务）
  2. 提取参数: 客户=阿里云, 项目=ECS, count=5, 平台=抖音
  3. 规划步骤:
     a. 查询客户 → list_clients(keyword="阿里云")
        返回: client_id=123
     b. 查询项目 → list_projects(client_id=123)
        返回: project_id=456 (ECS项目)
     c. 检查绑定 → list_bindings(platform="douyin")
        返回: account_id=789
     d. 生成问题 → generate_questions(project_id=456, question_count=5)
        返回: batch_id=100
     e. 生成文章 → generate_articles(project_id=456, article_count=5)
        返回: batch_id=101
     f. 发布文章 → publish_article(article_id=文章ID, account_id=789)
        返回: task_id=999
  4. 返回结果: "已为阿里云ECS项目生成5篇文章并发布到抖音，任务ID: 999"
```

### 12.3 长任务的关键

1. **工具粒度合理**：每个工具职责单一，可以组合
2. **Agent 推理能力**：能够理解复杂任务并拆解步骤
3. **Checkpoint 保存中间状态**：如果第 5 步失败，可以从第 5 步重试
4. **错误处理**：某一步失败时，能够回滚或重试

---

## 13. 不稳定环节与风险

### 13.1 风险矩阵

| 环节 | 风险等级 | 主要问题 | 缓解措施 |
|------|----------|----------|----------|
| **LLM 推理** | 中等 | 意图误解、信息提取错误 | 优化 prompt、few-shot、置信度阈值 |
| **多轮对话状态管理** | 中等 | 记忆丢失、状态错乱 | Checkpoint、持久化、状态转换 |
| **工具调用错误处理** | 低 | 执行失败、前置条件不满足 | 错误处理、重试机制 |
| **前端交互** | 中等 | 组件复杂、状态同步 | 组件化、状态管理、错误处理 |

### 13.2 最不稳定环节

#### LLM 推理

**问题**：
- LLM 可能误解用户意图
- LLM 可能提取错误的信息
- LLM 可能调用错误的工具

**缓解措施**：
1. **优化 prompt**：明确说明每个工具的用途和参数
2. **Few-shot examples**：提供示例对话
3. **置信度阈值**：低于阈值时追问确认
4. **工具 docstring**：清晰描述工具的前置条件和参数

#### 多轮对话状态管理

**问题**：
- 短期记忆（task_context）可能丢失或错乱
- 用户中途切换任务时，状态恢复困难
- 长时间对话后，LLM 可能忘记之前的上下文

**缓解措施**：
1. **Checkpoint 机制**：LangGraph 自动保存状态
2. **task_context 持久化**：保存到数据库，跨会话恢复
3. **明确的状态转换**：任务完成时清除 task_context

### 13.3 测试策略

1. **单元测试**：测试每个工具的参数验证和前置条件校验
2. **集成测试**：测试 Agent 的推理和工具调用
3. **端到端测试**：测试完整的业务流程（创建客户 → 生成文章 → 发布）
4. **压力测试**：测试高并发场景下的稳定性

---

## 14. 实施计划

### 14.1 阶段 1：基础设施搭建

**目标**：搭建 LangGraph 框架，实现最简的 ReAct 循环

**任务**：
- 引入 LangGraph 依赖
- 定义 AgentState 结构
- 实现最简的 Agent 节点和 Tools 节点
- 配置 Checkpoint（PostgresSaver）
- 搭建 FastAPI API 服务

### 14.2 阶段 2：工具封装

**目标**：实现 18 个业务工具

**任务**：
- 定义工具的 Pydantic 模型
- 封装已有的 Service 层方法
- 实现前置条件校验
- 编写工具文档（docstring）
- 单元测试

### 14.3 阶段 3：多轮信息提取

**目标**：实现多轮对话中的信息提取和任务上下文管理

**任务**：
- 优化 Agent prompt，明确信息提取规则
- 实现 task_context 的更新逻辑
- 测试多轮对话场景（如创建客户）
- 实现表单弹窗引导

### 14.4 阶段 4：前端交互

**目标**：实现前端弹窗、表单等交互组件

**任务**：
- 开发 4 种弹窗组件（列表弹窗、表单弹窗、选择弹窗、指标卡片）
- 实现 Action 渲染组件
- 实现 Agent 思考过程展示
- 与后端联调

### 14.5 阶段 5：优化与测试

**目标**：优化性能，完善测试

**任务**：
- 优化 prompt，提高意图识别准确率
- 性能优化（减少 LLM 调用次数）
- 完善单元测试和集成测试
- 端到端测试

### 14.6 阶段 6：上线与监控

**目标**：上线生产环境，建立监控体系

**任务**：
- 部署到生产环境
- 建立监控体系（日志、指标、告警）
- 收集用户反馈
- 持续优化

---

## 15. 附录

### 15.1 术语表

| 术语 | 解释 |
|------|------|
| **ReAct** | Reasoning + Acting，一种 Agent 架构，LLM 交替进行推理和行动 |
| **LangGraph** | 用于构建有状态、多步骤 Agent 的框架 |
| **State** | LangGraph 中的状态对象，保存 Agent 的完整状态 |
| **Checkpoint** | State 的持久化版本，保存在数据库中 |
| **Thread ID** | 对话标识，同一个对话使用相同的 thread_id |
| **Tool Calling** | LLM 调用工具的机制 |
| **Pydantic** | Python 数据验证库，用于参数验证 |
| **task_context** | 短期记忆，保存当前任务的状态 |
| **user_facts** | 长期记忆，保存用户的事实性知识 |
| **Action** | Agent 返回的结构化交互指令，前端根据 type 渲染弹窗/表单等 |

### 15.2 前端 API 与工具映射表

| 前端 API | 工具名 | 说明 |
|----------|--------|------|
| `clientApi.create` | `create_client` | 创建客户 |
| `clientApi.getList` | `list_clients` | 查询客户列表 |
| `clientApi.getDetail` | `get_client_detail` | 查询客户详情 |
| `geoKeywordApi.createProject` | `create_project` | 创建项目 |
| `geoKeywordApi.getProjects` | `list_projects` | 查询项目列表 |
| `geoKeywordApi.getProject` | `get_project_detail` | 查询项目详情 |
| `smartArticleApi.generateQuestions` | `generate_questions` | 生成用户问题 |
| `smartArticleApi.getQuestions` | `list_questions` | 查询问题列表 |
| `smartArticleApi.generate` | `generate_articles` | 智能文章生成（唯一入口） |
| `smartArticleApi.getArticles` | `list_articles` | 查询文章列表 |
| `accountApi.startAuth` | `bind_platform` | 绑定平台账户 |
| `accountApi.getList` | `list_bindings` | 查询已绑定账户 |
| `publishApi.create` | `publish_article` | 发布文章 |
| `publishApi.getRecords` | `list_publish_records` | 查询发布记录 |
| `geoEvaluationApi.createBaseline` | `create_baseline` | 创建基线 |
| `geoEvaluationApi.runRecheck` | `run_recheck` | 执行复测 |
| `geoEvaluationApi.getDiagnosis` | `get_diagnosis` | 获取诊断指标 |
| `clientApi.uploadFiles` | `upload_documents` | 上传客户资料 |

### 15.3 参考资料

- [LangGraph 官方文档](https://langchain-ai.github.io/langgraph/)
- [LangChain 官方文档](https://python.langchain.com/)
- [Pydantic 官方文档](https://docs.pydantic.dev/)
- [FastAPI 官方文档](https://fastapi.tiangolo.com/)

### 15.4 更新日志

| 版本 | 日期 | 更新内容 | 作者 |
|------|------|----------|------|
| v1.0 | 2026-08-06 | 初始版本，完成架构设计 | 开发团队 |
| v2.0 | 2026-08-06 | 基于用户反馈重构：18个工具、4种弹窗、收录监控逻辑修正、工具直接调用Service层 | 开发团队 |

---

## 文档维护说明

本文档是**活文档**，会随着项目进展持续更新。

**更新原则**：
1. 每次重大设计变更都要更新本文档
2. 新增工具时，更新工具清单
3. 发现问题或优化点时，及时记录
4. 保持文档与代码的一致性

**更新流程**：
1. 修改文档
2. 更新版本号和日期
3. 在更新日志中记录变更
4. 提交代码审查

---

**文档结束**
