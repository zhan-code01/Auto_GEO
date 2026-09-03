/**
 * useSSE - Agent V2 SSE 流式响应 composable
 *
 * 对应 PRD 第十三章 13.6 节前端实现 + §11.7 Agent 思考过程展示。
 * 参考 useWebSocket.ts 结构，提供 sendMessage 和事件订阅器。
 *
 * 用法：
 *   const { sendMessage, sending, thinking, replyText, actions, cancel } = useSSE()
 *   await sendMessage('帮我生成5篇文章', { sessionId })
 */

import { ref, onUnmounted, readonly } from 'vue'
import {
  sseClient,
  type SSEHandlers,
  type SSEMessageRequest,
  type AgentAction,
  type ToolCall,
  type AsyncTaskRef,
} from '@/services/sse'

export function useSSE() {
  // ===== 响应式状态 =====
  const sending = ref(false)
  const thinking = ref<string>('')        // Agent 思考过程（对应 PRD §11.7）
  const pendingToolCalls = ref<ToolCall[]>([])  // Agent 决策调用的工具列表
  const replyText = ref<string>('')        // 累积的回复文本（text_delta 拼接）
  const actions = ref<AgentAction[]>([])   // 前端按钮（列表/表单/选择/指标卡片）
  const toolName = ref<string>('')         // 当前执行的工具名
  const toolResult = ref<Record<string, unknown>>({})
  const asyncTasks = ref<AsyncTaskRef[]>([])  // 异步任务引用
  const error = ref<{ code: string; message: string } | null>(null)
  const status = ref<string>('')           // done 事件的状态
  const sessionId = ref<string>('')
  const progress = ref<{ stage: string; elapsed_sec: number } | null>(null)
  const needClarification = ref(false)     // 是否需要用户补充信息

  // 事件回调（外部可覆盖）
  const callbacks: Partial<SSEHandlers> = {}

  /**
   * 发送消息
   *
   * @param message 用户消息
   * @param options 可选：sessionId、attachments、action（V1 兼容回调）
   */
  async function sendMessage(
    message: string,
    options: {
      sessionId?: string
      attachments?: SSEMessageRequest['attachments']
      action?: SSEMessageRequest['action']
    } = {}
  ): Promise<void> {
    // 重置状态
    sending.value = true
    thinking.value = ''
    pendingToolCalls.value = []
    replyText.value = ''
    actions.value = []
    toolName.value = ''
    toolResult.value = {}
    asyncTasks.value = []
    error.value = null
    status.value = ''
    progress.value = null
    needClarification.value = false

    const body: SSEMessageRequest = {
      message,
      session_id: options.sessionId,
      attachments: options.attachments,
      action: options.action,
    }

    const handlers: SSEHandlers = {
      onThinking: (data) => {
        thinking.value = data.thinking
        callbacks.onThinking?.(data)
      },
      onToolCalls: (data) => {
        pendingToolCalls.value = data.tool_calls
        callbacks.onToolCalls?.(data)
      },
      onToolStart: (data) => {
        toolName.value = data.tool_name
        callbacks.onToolStart?.(data)
      },
      onToolEnd: (data) => {
        toolName.value = data.tool_name
        toolResult.value = data.result
        if (data.actions?.length) {
          actions.value = [...actions.value, ...data.actions]
        }
        callbacks.onToolEnd?.(data)
      },
      onActions: (data) => {
        if (data.actions?.length) {
          actions.value = [...actions.value, ...data.actions]
        }
        callbacks.onActions?.(data)
      },
      onTextDelta: (delta) => {
        replyText.value += delta
        callbacks.onTextDelta?.(delta)
      },
      onAsyncTask: (data) => {
        asyncTasks.value.push(data)
        callbacks.onAsyncTask?.(data)
      },
      onClarification: (data) => {
        needClarification.value = true
        replyText.value = data.reply
        if (data.actions?.length) {
          actions.value = [...actions.value, ...data.actions]
        }
        callbacks.onClarification?.(data)
      },
      onError: (data) => {
        error.value = data
        callbacks.onError?.(data)
      },
      onProgress: (data) => {
        progress.value = data
        callbacks.onProgress?.(data)
      },
      onDone: (data) => {
        status.value = data.status
        sessionId.value = data.session_id
        sending.value = false
        // done 事件可能携带最终 actions（如 done 前没有 actions 事件）
        if (data.actions?.length && actions.value.length === 0) {
          actions.value = data.actions
        }
        if (data.async_task_refs?.length) {
          asyncTasks.value = [...asyncTasks.value, ...data.async_task_refs]
        }
        callbacks.onDone?.(data)
      },
    }

    await sseClient.sendMessage(body, handlers)

    // 兜底：如果 done 事件没收到（网络异常），也释放 sending
    if (sending.value) {
      sending.value = false
    }
  }

  /**
   * 取消当前请求
   */
  function cancel(): void {
    sseClient.cancel()
    sending.value = false
  }

  /**
   * 注册事件回调（覆盖默认行为）
   *
   * 用法：
   *   const { on } = useSSE()
   *   on('onDone', (data) => { console.log('完成', data) })
   */
  function on<K extends keyof SSEHandlers>(event: K, handler: SSEHandlers[K]): void {
    callbacks[event] = handler
  }

  // 组件卸载时取消未完成的请求
  onUnmounted(() => {
    cancel()
  })

  return {
    // 状态（只读）
    sending: readonly(sending),
    thinking: readonly(thinking),
    pendingToolCalls: readonly(pendingToolCalls),
    replyText: readonly(replyText),
    actions: readonly(actions),
    toolName: readonly(toolName),
    toolResult: readonly(toolResult),
    asyncTasks: readonly(asyncTasks),
    error: readonly(error),
    status: readonly(status),
    sessionId: readonly(sessionId),
    progress: readonly(progress),
    needClarification: readonly(needClarification),

    // 方法
    sendMessage,
    cancel,
    on,
  }
}
