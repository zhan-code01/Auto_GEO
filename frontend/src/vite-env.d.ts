/**
 * Vite 类型声明
 */

/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const component: DefineComponent<any, any, any>
  export default component
}

declare module '@wangeditor/editor-for-vue' {
  import type { DefineComponent } from 'vue'
  export const Editor: DefineComponent<any, any, any>
  export const Toolbar: DefineComponent<any, any, any>
}

// 动态 import Vue 组件的路径别名
declare module '@/views/site-builder/AIWebPage.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<any, any, any>
  export default component
}

/**
 * Electron API 类型声明
 */
interface ElectronAPI {
  getAppInfo(): Promise<{
    name: string
    version: string
    platform: string
    arch: string
  }>
  getVersion(): Promise<string>
  minimizeWindow(): void
  maximizeWindow(): void
  closeWindow(): void
  openExternal(url: string): Promise<void>
  openFile(options: any): Promise<any>
  saveFile(options: any): Promise<any>
  startAuth(platformId: string, authUrl: string): void
  showNotification(title: string, body: string): void
  onAuthWindowClosed(callback: (data: any) => void): () => void
  onPublishProgress(callback: (data: any) => void): () => void

  // 后端管理
  getBackendStatus(): Promise<{
    status: 'stopped' | 'starting' | 'running' | 'error'
    pid: number | null
  }>
  restartBackend(): Promise<{ success: boolean }>
  getBackendConfig(): Promise<any>

  // 浏览器桥接服务管理
  getBridgeStatus(): Promise<{
    status: 'stopped' | 'starting' | 'running' | 'error'
    pid: number | null
  }>
  restartBridge(): Promise<{ success: boolean }>
  getBridgeConfig(): Promise<any>

  platforms: Record<string, { id: string; name: string; color: string }>

  // 本地发布 - 账号授权
  localAuth?: {
    getBoundAccounts(): Promise<Array<{
      platform: string
      name: string
      active: boolean
      accountId: number
    }>>
    startAuth(
      platform: string,
      token?: string,
      serverBaseUrl?: string,
      accountName?: string,
      accountId?: number
    ): Promise<{ success: boolean; error?: string; nickname?: string }>
    getSessionStatus?(platforms?: string[]): Promise<{
      success: boolean
      error?: string
      sessions?: Record<string, boolean>
    }>
    verifySession?(platform: string, accountId?: number): Promise<{
      success: boolean
      auth_status: 'ok' | 'logged_out' | 'unknown'
      nickname?: string
      error?: string
    }>
  }

  // 本地发布 - 发布引擎
  publishEngine?: {
    start(
      token: string,
      serverBaseUrl?: string,
      pollIntervalMs?: number
    ): Promise<{ success: boolean; error?: string; status?: string; device_id?: string; server_base_url?: string }>
    stop(): Promise<{ success: boolean; status?: string; error?: string }>
    getStatus?(): Promise<{
      running: boolean
      status?: string
      activeTask?: string
      activeTaskId?: number | null
      geoEvaluation?: any
      hasHeartbeat?: boolean
      device?: any
      progress?: {
        completed?: number
        total?: number
        records?: Array<{
          title: string
          platform: string
          status: string
          message: string
        }>
      }
    }>
  }

  geoEvaluationEngine?: {
    start(token: string, serverBaseUrl?: string): Promise<{
      success: boolean
      error?: string
      status?: string
      activeRuns?: Array<{ runId: number; platform: string }>
    }>
    getStatus(): Promise<{
      running: boolean
      status: string
      activeRuns: Array<{ runId: number; platform: string }>
    }>
    recheckManual(runId: number): Promise<{ success: boolean; error?: string }>
  }

  // 设备身份（创建任务时绑定本机设备、409 冲突时重置设备标识）
  device?: {
    getInfo(): Promise<{
      device_id: string
      device_name: string
      os: string
      app_version: string
    }>
    resetIdentity(): Promise<{ device_id: string; created_at: string }>
  }

  // 本地发布 - 事件监听
  onAuthResult?(callback: (data: {
    platform: string
    success: boolean
    nickname?: string
    error?: string
  }) => void): (() => void) | undefined

  onTaskProgress?(callback: (data: {
    taskName?: string
    completed?: number
    total?: number
    records?: Array<{
      title: string
      platform: string
      status: 'pending' | 'publishing' | 'success' | 'failed'
      message: string
    }>
  }) => void): (() => void) | undefined

  onManualRequired?(callback: (data: { message?: string }) => void): (() => void) | undefined

  onPublishEngineStatus?(callback: (data: { status: string }) => void): (() => void) | undefined

  onGeoEvaluationEngineStatus?(callback: (data: {
    status: string
    runId?: number
    platform?: string
    message?: string
    browserMode?: string
  }) => void): (() => void) | undefined

  onGeoEvaluationEngineProgress?(callback: (data: {
    runId: number
    platform: string
    promptId: number
    done: number
    total: number
    browserMode?: string
  }) => void): (() => void) | undefined
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI
    __ELECTRON_ENV__?: string
  }
}

export {}
