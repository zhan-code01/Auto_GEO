/**
 * WebSocket 服务
 * 我用这个来处理实时通信！
 */

import { ref } from 'vue'
import { ElMessage } from 'element-plus'

type MessageHandler = (data: any) => void
type ConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'error'

class WebSocketService {
  private ws: WebSocket | null = null
  private url: string = ''
  private reconnectTimer: number | null = null
  private reconnectAttempts: number = 0
  private maxReconnectAttempts: number = 5
  private reconnectDelay: number = 3000
  private handlers: Map<string, Set<MessageHandler>> = new Map()

  // 连接状态
  public status = ref<ConnectionStatus>('disconnected')

  /**
   * 连接 WebSocket
   */
  connect(url: string, clientId?: string) {
    this.url = url

    if (this.ws?.readyState === WebSocket.OPEN) {
      return
    }

    this.status.value = 'connecting'

    try {
      // 构建 WebSocket URL
      const wsUrl = url.replace('http://', 'ws://').replace('https://', 'wss://')
      const fullUrl = clientId ? `${wsUrl}?client_id=${clientId}` : wsUrl

      this.ws = new WebSocket(fullUrl)

      this.ws.onopen = () => {
        this.status.value = 'connected'
        this.reconnectAttempts = 0
        console.log('WebSocket 连接成功')
      }

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          this.handleMessage(data)
        } catch (e) {
          console.error('解析 WebSocket 消息失败:', e)
        }
      }

      this.ws.onerror = () => {
        this.status.value = 'error'
        console.error('WebSocket 错误')
      }

      this.ws.onclose = () => {
        this.status.value = 'disconnected'
        console.log('WebSocket 连接关闭')

        // 尝试重连
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
          this.scheduleReconnect()
        }
      }
    } catch (e) {
      this.status.value = 'error'
      console.error('WebSocket 连接失败:', e)
    }
  }

  /**
   * 断开连接
   */
  disconnect() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }

    if (this.ws) {
      this.ws.close()
      this.ws = null
    }

    this.status.value = 'disconnected'
  }

  /**
   * 发送消息
   */
  send(data: any) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data))
    } else {
      console.warn('WebSocket 未连接，无法发送消息')
    }
  }

  /**
   * 订阅消息
   */
  on(type: string, handler: MessageHandler) {
    if (!this.handlers.has(type)) {
      this.handlers.set(type, new Set())
    }
    this.handlers.get(type)!.add(handler)

    // 返回取消订阅函数
    return () => this.off(type, handler)
  }

  /**
   * 取消订阅
   */
  off(type: string, handler: MessageHandler) {
    this.handlers.get(type)?.delete(handler)
  }

  /**
   * 处理接收到的消息
   */
  private handleMessage(data: any) {
    const type = data.type || data.messageType

    if (type && this.handlers.has(type)) {
      this.handlers.get(type)!.forEach(handler => handler(data))
    }

    // 触发所有消息的处理器
    if (this.handlers.has('*')) {
      this.handlers.get('*')!.forEach(handler => handler(data))
    }
  }

  /**
   * 安排重连
   */
  private scheduleReconnect() {
    if (this.reconnectTimer) return

    this.reconnectAttempts++
    const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1)

    console.log(`${delay}ms 后尝试第 ${this.reconnectAttempts} 次重连...`)

    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null
      this.connect(this.url)
    }, delay)
  }
}

// 单例实例
const wsService = new WebSocketService()

/**
 * WebSocket Hook
 * 我用这个来在组件中使用 WebSocket！
 */
export function useWebSocket(url?: string) {
  const connect = (wsUrl?: string) => {
    if (wsUrl || url) {
      wsService.connect(wsUrl || url!)
    }
  }

  const disconnect = () => {
    wsService.disconnect()
  }

  const send = (data: any) => {
    wsService.send(data)
  }

  const on = (type: string, handler: MessageHandler) => {
    return wsService.on(type, handler)
  }

  const status = wsService.status

  return {
    status,
    connect,
    disconnect,
    send,
    on,
  }
}

export default wsService
