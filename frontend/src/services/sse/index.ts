/**
 * SSE 客户端服务 - Agent V2 流式响应
 *
 * 对应 PRD 第十三章 13.6 节前端实现。
 * 使用 fetch + ReadableStream（不用 EventSource），支持 JWT 请求头。
 *
 * 事件类型（PRD 13.3 节，ReAct 模式）：
 * - thinking: Agent 思考过程（展示给用户，类似 ChatGPT 的 thinking 状态）
 * - tool_calls: Agent 决策调用的工具列表（即将调用工具）
 * - tool_start: 工具开始执行
 * - tool_end: 工具执行完成
 * - actions: 前端按钮（列表弹窗/表单弹窗/选择弹窗/指标卡片等）
 * - text_delta: LLM 回复生成中（流式分片，打字机效果）
 * - async_task_started: 异步任务已启动
 * - clarification: 需要用户补充信息
 * - error: 执行异常
 * - progress: 心跳/阶段进度
 * - done: 本轮响应结束
 */

// 判断是否在 Electron 打包环境中
const isElectronApp =
  typeof window !== 'undefined' &&
  (window.navigator.userAgent.includes('Electron') || window.__ELECTRON_ENV__ === 'production')

const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL

const isLocalhostUrl = /^https?:\/\/(?:localhost|127\.0\.0\.1)(?::\d+)?\/api\/?$/i.test(
  configuredBaseUrl || ''
)

// SSE 端点基础地址（与 axios 实例保持一致的 URL 协商逻辑）
const SSE_BASE = isLocalhostUrl && isElectronApp ? configuredBaseUrl : isLocalhostUrl ? '/api' : configuredBaseUrl || '/api'

// Action 按钮（对应 PRD §11.1）
export interface AgentAction {
  type: string // Action 类型（show_client_list / select_platform / show_diagnosis 等）
  label: string // 按钮文案
  payload: Record<string, unknown> // 按钮数据
  interaction: 'frontend_direct' | 'via_agent' // 交互方式：前端直连 / 走智能体
}

// 工具调用（Agent 决策调用）
export interface ToolCall {
  name: string // 工具名
  args: Record<string, unknown> // 工具参数
}

// 异步任务引用
export interface AsyncTaskRef {
  task_type: string
  task_id: number | string
  query_tool: string // 前端可用此工具名轮询结果
  platform?: string // bind_platform 工具会带上平台名（如 zhihu）
}

// 工具执行结果
export interface ToolResult {
  name: string
  result: Record<string, unknown>
  id?: string
}

// 事件处理器类型（对齐 V2 ReAct 模式事件）
export interface SSEHandlers {
  /** Agent 思考过程（对应 PRD §11.7，展示给用户） */
  onThinking?: (data: { thinking: string }) => void
  /** Agent 决策调用的工具列表（即将调用工具） */
  onToolCalls?: (data: { tool_calls: ToolCall[] }) => void
  /** 工具开始执行 */
  onToolStart?: (data: { tool_name: string; params: Record<string, unknown> }) => void
  /** 工具执行完成 */
  onToolEnd?: (data: { tool_name: string; result: Record<string, unknown>; actions: AgentAction[] }) => void
  /** 前端按钮（列表弹窗/表单弹窗/选择弹窗/指标卡片等） */
  onActions?: (data: { actions: AgentAction[] }) => void
  /** LLM 回复文本增量（流式分片，打字机效果） */
  onTextDelta?: (delta: string) => void
  /** 异步任务已启动 */
  onAsyncTask?: (data: AsyncTaskRef) => void
  /** 需要用户补充信息 */
  onClarification?: (data: { reply: string; actions: AgentAction[] }) => void
  /** 错误事件 */
  onError?: (data: { code: string; message: string }) => void
  /** 心跳/阶段进度 */
  onProgress?: (data: { stage: string; elapsed_sec: number }) => void
  /** 本轮响应结束 */
  onDone?: (data: {
    status: 'completed' | 'need_clarification' | 'running' | 'failed'
    session_id: string
    actions: AgentAction[]
    async_task_refs: AsyncTaskRef[]
    tool_results: ToolResult[]
  }) => void
}

// SSE 请求体
export interface SSEMessageRequest {
  message: string
  session_id?: string
  attachments?: Array<{ type: string; path: string; filename: string }>
  /** V1 兼容：action 回调（select_client/confirm/show_*_form 后回传用户选择） */
  action?: {
    type: string
    label: string
    payload?: Record<string, unknown>
  }
  /** 静默发送：不触发前端提示音/气泡动画等 */
  silent?: boolean
}

/**
 * SSE 客户端单例
 */
class SSEClient {
  private controller: AbortController | null = null

  /**
   * 发送消息并接收 SSE 流
   *
   * 用 fetch + ReadableStream 实现，不用 EventSource（EventSource 不支持自定义请求头）。
   * 支持断线重连（手动，用 AbortController + 指数退避）。
   */
  async sendMessage(body: SSEMessageRequest, handlers: SSEHandlers): Promise<void> {
    // 取消上一个未完成的请求
    this.cancel()

    this.controller = new AbortController()
    const token = localStorage.getItem('autogeo_token')

    const url = `${SSE_BASE}/agent-v2/message`
    let response: Response

    try {
      response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'text/event-stream',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(body),
        signal: this.controller.signal,
      })
    } catch (err: any) {
      if (err.name === 'AbortError') {
        return
      }
      handlers.onError?.({ code: 'network_error', message: `连接失败: ${err.message}` })
      return
    }

    if (!response.ok) {
      const text = await response.text().catch(() => '')
      handlers.onError?.({
        code: `http_${response.status}`,
        message: text || `HTTP ${response.status}`,
      })
      return
    }

    if (!response.body) {
      handlers.onError?.({ code: 'no_body', message: '响应无 body' })
      return
    }

    // 用 ReadableStream 手动解析 text/event-stream
    const reader = response.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''

    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // 按 \n\n 分割事件（SSE 事件以空行分隔）
        const events = buffer.split('\n\n')
        buffer = events.pop() || ''

        for (const eventStr of events) {
          this.dispatchEvent(eventStr, handlers)
        }
      }
      // 处理最后残留的 buffer
      if (buffer.trim()) {
        this.dispatchEvent(buffer, handlers)
      }
    } catch (err: any) {
      if (err.name === 'AbortError') {
        return
      }
      handlers.onError?.({ code: 'stream_error', message: `流读取失败: ${err.message}` })
    } finally {
      this.controller = null
    }
  }

  /**
   * 解析并分发单个 SSE 事件
   */
  private dispatchEvent(eventStr: string, handlers: SSEHandlers): void {
    const lines = eventStr.split('\n')
    let eventType = ''
    let dataStr = ''

    for (const line of lines) {
      if (line.startsWith('event: ')) {
        eventType = line.slice(7).trim()
      } else if (line.startsWith('data: ')) {
        dataStr += line.slice(6)
      }
    }

    if (!eventType || !dataStr) return

    let parsed: any
    try {
      parsed = JSON.parse(dataStr)
    } catch (e) {
      console.error('[SSE] 解析 data 失败:', e, dataStr)
      return
    }

    switch (eventType) {
      case 'thinking':
        handlers.onThinking?.(parsed)
        break
      case 'tool_calls':
        handlers.onToolCalls?.(parsed)
        break
      case 'tool_start':
        handlers.onToolStart?.(parsed)
        break
      case 'tool_end':
        handlers.onToolEnd?.(parsed)
        break
      case 'actions':
        handlers.onActions?.(parsed)
        break
      case 'text_delta':
        handlers.onTextDelta?.(parsed.delta || '')
        break
      case 'async_task_started':
        handlers.onAsyncTask?.(parsed)
        break
      case 'clarification':
        handlers.onClarification?.(parsed)
        break
      case 'error':
        handlers.onError?.(parsed)
        break
      case 'progress':
        handlers.onProgress?.(parsed)
        break
      case 'done':
        handlers.onDone?.(parsed)
        break
      default:
        console.warn('[SSE] 未知事件类型:', eventType, parsed)
    }
  }

  /**
   * 取消当前请求
   */
  cancel(): void {
    if (this.controller) {
      this.controller.abort()
      this.controller = null
    }
  }
}

// 全局单例
export const sseClient = new SSEClient()

// ============================================================
//  REST API 辅助函数（会话管理、偏好、事实）
// ============================================================

import axios from 'axios'

const restInstance = axios.create({
  baseURL: SSE_BASE,
  timeout: 30000,
})

restInstance.interceptors.request.use((config) => {
  const token = localStorage.getItem('autogeo_token')
  if (token && config.headers) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

/** 列出会话 */
export async function listSessions(limit = 50, offset = 0) {
  const res = await restInstance.get('/agent-v2/sessions', { params: { limit, offset } })
  return res.data
}

/** 获取会话详情（含消息历史） */
export async function getSession(sessionId: string, includeSlots = false) {
  const res = await restInstance.get(`/agent-v2/sessions/${sessionId}`, {
    params: { include_slots: includeSlots },
  })
  return res.data
}

/** 重命名会话 */
export async function renameSession(sessionId: string, title: string) {
  const res = await restInstance.put(`/agent-v2/sessions/${sessionId}`, { title })
  return res.data
}

/** 归档会话 */
export async function archiveSession(sessionId: string) {
  const res = await restInstance.post(`/agent-v2/sessions/${sessionId}/archive`)
  return res.data
}

/** 删除会话 */
export async function deleteSession(sessionId: string) {
  const res = await restInstance.delete(`/agent-v2/sessions/${sessionId}`)
  return res.data
}

/** 获取会话消息历史 */
export async function listMessages(sessionId: string, limit = 50) {
  const res = await restInstance.get(`/agent-v2/sessions/${sessionId}/messages`, {
    params: { limit },
  })
  return res.data
}

/** 获取用户偏好 */
export async function getPreferences() {
  const res = await restInstance.get('/agent-v2/preferences')
  return res.data
}

/** 更新用户偏好 */
export async function updatePreferences(payload: Record<string, unknown>) {
  const res = await restInstance.put('/agent-v2/preferences', payload)
  return res.data
}

/** 获取用户事实 */
export async function getFacts(userId?: number) {
  const res = await restInstance.get('/agent-v2/facts', { params: { user_id: userId } })
  return res.data
}

/** 注册 WebSocket user_id 映射 */
export async function registerWsUser(clientId: string, userId: number) {
  const res = await restInstance.post('/agent-v2/ws/register', { client_id: clientId, user_id: userId })
  return res.data
}

/** 获取新用户引导状态（确定性状态机，前端据此渲染进度条与下一步卡片） */
export async function getOnboarding() {
  const res = await restInstance.get('/agent-v2/onboarding')
  return res.data
}

/** 跳过引导（持久化 onboarding_dismissed） */
export async function dismissOnboarding() {
  const res = await restInstance.post('/agent-v2/onboarding/dismiss', {})
  return res.data
}
