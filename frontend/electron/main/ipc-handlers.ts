/**
 * IPC 通信处理器
 * 我用这个来处理渲染进程和主进程之间的通信！
 */

import { ipcMain, shell, dialog } from 'electron'
import { getMainWindow, createAuthWindow, showNotification } from './window-manager'
import * as backendManager from './backend-manager'
import * as browserBridgeManager from './browser-bridge-manager'
import { getDeviceInfo, getServerUrl } from './device-manager'
import { hasUsableSession, startLocalAuth, verifySessionState, uploadAllLocalSessions } from './local-auth'
import { PublishEngine, type EngineStatus, type ManualRequiredData, type TaskProgressData } from './publish-engine'
import { GeoEvaluationEngine } from './geo-evaluation-engine'

// 允许的调用通道（白名单模式）
const INVOKE_CHANNELS = [
  'app:get-info',
  'app:get-version',
  'window:minimize',
  'window:maximize',
  'window:close',
  'shell:open-external',
  'dialog:open-file',
  'dialog:save-file',
  'auth:start',
  'backend:get-status',
  'backend:restart',
  'backend:get-config',
  'bridge:get-status',
  'bridge:restart',
  'bridge:get-config',
  'local-auth:start',
  'local-auth:get-session-status',
  'local-auth:verify-session',
  'publish-engine:start',
  'publish-engine:stop',
  'publish-engine:get-status',
  'geo-evaluation-engine:start',
  'geo-evaluation-engine:get-status',
  'geo-evaluation-engine:recheck-manual',
]

// 允许的发送通道
const SEND_CHANNELS = [
  'app:ready',
  'auth:check-status',
]

const CLIENT_PUBLISH_PLATFORMS = [
  'zhihu',
  'bilibili',
  'douyin',
  'kuaishou',
  'baijiahao',
  'toutiao',
  'jianshu',
  'juejin',
  'csdn',
  'tieba',
]

let publishEngine: PublishEngine | null = null
let geoEvaluationEngine: GeoEvaluationEngine | null = null
let publishEngineStatus: EngineStatus = 'stopped'
let deviceHeartbeatTimer: NodeJS.Timeout | null = null

function normalizeServerBaseUrl(serverBaseUrl?: string): string {
  return (serverBaseUrl || getServerUrl() || process.env.AUTO_GEO_SERVER_URL || 'http://127.0.0.1:8001').replace(/\/+$/, '')
}

function publishCapabilities() {
  return {
    publish: {
      platforms: CLIENT_PUBLISH_PLATFORMS,
      manual_intervention: true,
      local_browser: true,
    },
    geo_evaluation: {
      platforms: ['doubao', 'qianwen', 'deepseek'],
      manual_intervention: true,
      local_browser: true,
    },
  }
}

function hasUsableLocalSession(platform: string): boolean {
  return hasUsableSession(platform)
}

async function callClientDeviceApi(
  baseUrl: string,
  token: string,
  path: string,
  body: Record<string, any>,
): Promise<any> {
  const response = await fetch(`${baseUrl}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    let message = `HTTP ${response.status}`
    try {
      const data = await response.json()
      message = data?.detail || data?.message || message
    } catch {
      // ignore non-json error bodies
    }
    throw new Error(message)
  }
  return response.json()
}

async function registerClientDevice(baseUrl: string, token: string): Promise<void> {
  const device = getDeviceInfo()
  await callClientDeviceApi(baseUrl, token, '/api/client/devices/register', {
    ...device,
    capabilities: publishCapabilities(),
  })
}

function startDeviceHeartbeat(baseUrl: string, token: string): void {
  if (deviceHeartbeatTimer) clearInterval(deviceHeartbeatTimer)

  const beat = () => {
    const device = getDeviceInfo()
    callClientDeviceApi(baseUrl, token, '/api/client/devices/heartbeat', {
      device_id: device.device_id,
      capabilities: publishCapabilities(),
    }).catch((err: any) => {
      console.error('[ClientDevice] heartbeat failed:', err.message)
    })
  }

  beat()
  deviceHeartbeatTimer = setInterval(beat, 30 * 1000)
}

function stopDeviceHeartbeat(): void {
  if (deviceHeartbeatTimer) {
    clearInterval(deviceHeartbeatTimer)
    deviceHeartbeatTimer = null
  }
}

function wirePublishEngine(engine: PublishEngine): void {
  engine.onEngineStatus = (status: EngineStatus) => {
    publishEngineStatus = status
    sendToRenderer('publish-engine:status', { status })
  }
  engine.onTaskProgress = (data: TaskProgressData) => {
    sendToRenderer('publish-engine:task-progress', data)
    sendToRenderer('publish:progress', data)
  }
  engine.onManualRequired = (data: ManualRequiredData) => {
    sendToRenderer('publish-engine:manual-required', data)
    sendToRenderer('publish:progress', { ...data, status: 'manual_required' })
  }
}

function wireGeoEvaluationEngine(engine: GeoEvaluationEngine): void {
  engine.onStatus = (status, data) => {
    sendToRenderer('geo-evaluation-engine:status', { status, ...data })
  }
  engine.onProgress = (data) => {
    sendToRenderer('geo-evaluation-engine:progress', data)
  }
}

/**
 * 验证发送者（安全检查）
 * 我用这个来防止攻击！
 */
function validateSender(frame: any): boolean {
  if (!frame) return false
  try {
    const url = new URL(frame.url)
    const allowedProtocols = ['http:', 'https:', 'file:']
    return allowedProtocols.includes(url.protocol)
  } catch {
    return false
  }
}

/**
 * 注册所有 IPC 处理器
 */
export function registerHandlers(): void {
  // ==================== 应用相关 ====================

  ipcMain.handle('app:get-info', (event) => {
    if (!validateSender(event.senderFrame)) return null
    const { app } = require('electron')
    return {
      name: app.getName(),
      version: app.getVersion(),
      platform: process.platform,
      arch: process.arch,
    }
  })

  ipcMain.handle('app:get-version', (event) => {
    if (!validateSender(event.senderFrame)) return null
    return require('electron').app.getVersion()
  })

  // ==================== 窗口控制 ====================

  ipcMain.handle('window:minimize', (event) => {
    if (!validateSender(event.senderFrame)) return
    const win = getMainWindow()
    win?.minimize()
  })

  ipcMain.handle('window:maximize', (event) => {
    if (!validateSender(event.senderFrame)) return
    const win = getMainWindow()
    if (win?.isMaximized()) {
      win.unmaximize()
    } else {
      win?.maximize()
    }
  })

  ipcMain.handle('window:close', (event) => {
    if (!validateSender(event.senderFrame)) return
    const win = getMainWindow()
    win?.close()
  })

  // ==================== Shell 操作 ====================

  ipcMain.handle('shell:open-external', (event, url: string) => {
    if (!validateSender(event.senderFrame)) return
    shell.openExternal(url)
  })

  // ==================== 文件对话框 ====================

  ipcMain.handle('dialog:open-file', async (event, options: any) => {
    if (!validateSender(event.senderFrame)) return { canceled: true }
    const result = await dialog.showOpenDialog(options)
    return result
  })

  ipcMain.handle('dialog:save-file', async (event, options: any) => {
    if (!validateSender(event.senderFrame)) return { canceled: true }
    const result = await dialog.showSaveDialog(options)
    return result
  })

  // ==================== 授权相关 ====================

  ipcMain.handle('auth:start', (event, platformId: string, authUrl: string) => {
    if (!validateSender(event.senderFrame)) return
    const authWindow = createAuthWindow(platformId, authUrl)

    // 监听授权窗口关闭
    authWindow.on('closed', () => {
      // 通知渲染进程授权窗口已关闭
      const mainWin = getMainWindow()
      mainWin?.webContents.send('auth:window-closed', { platformId })
    })
  })

  ipcMain.handle('local-auth:start', async (
    event,
    platform: string,
    token: string,
    serverBaseUrl?: string,
    accountName?: string,
    accountId?: number,
  ) => {
    if (!validateSender(event.senderFrame)) return { success: false, error: 'invalid sender' }
    const baseUrl = (serverBaseUrl || getServerUrl() || 'http://127.0.0.1:8001').replace(/\/+$/, '')
    const deviceId = getDeviceInfo().device_id
    if (token) {
      await registerClientDevice(baseUrl, token)
    }
    const result = await startLocalAuth(platform, baseUrl, token, deviceId, accountName, accountId)
    getMainWindow()?.webContents.send('local-auth:result', result)
    return result
  })

  ipcMain.handle('local-auth:get-session-status', (event, platforms?: string[]) => {
    if (!validateSender(event.senderFrame)) return { success: false, error: 'invalid sender' }
    const targetPlatforms = Array.isArray(platforms) && platforms.length > 0
      ? platforms
      : CLIENT_PUBLISH_PLATFORMS
    const sessions = Object.fromEntries(
      targetPlatforms.map((platform) => [platform, hasUsableLocalSession(platform)]),
    )
    return { success: true, sessions }
  })

  // 「一键检测所有」真相引擎：用本地会话在真实无头浏览器里验证登录态
  ipcMain.handle('local-auth:verify-session', async (event, platform: string, accountId?: number) => {
    if (!validateSender(event.senderFrame)) return { success: false, error: 'invalid sender' }
    try {
      const result = await verifySessionState(platform, accountId)
      return { success: true, ...result }
    } catch (err: any) {
      return { success: false, auth_status: 'unknown', error: err?.message || '未知错误' }
    }
  })

  // ==================== 鏈湴瀹㈡埛绔彂甯冨紩鎿� ====================

  ipcMain.handle('publish-engine:start', async (
    event,
    token: string,
    serverBaseUrl?: string,
    pollIntervalMs?: number,
  ) => {
    if (!validateSender(event.senderFrame)) return { success: false, error: 'invalid sender' }
    if (!token) return { success: false, error: 'missing token' }

    const baseUrl = normalizeServerBaseUrl(serverBaseUrl)
    const deviceId = getDeviceInfo().device_id

    try {
      await registerClientDevice(baseUrl, token)
      startDeviceHeartbeat(baseUrl, token)

      const safePollIntervalMs = Math.max(pollIntervalMs || 30000, 30000)

      // 换账号/换服务器时重建引擎，避免复用旧账号 token 轮询其任务（同机多账号隔离）
      if (!publishEngine || publishEngine.token !== token || publishEngine.baseUrl !== baseUrl) {
        publishEngine?.stop()
        publishEngine = null
        publishEngine = new PublishEngine(baseUrl, token, deviceId)
        wirePublishEngine(publishEngine)
      }
      publishEngine.start(safePollIntervalMs)
      // 会话漫游：把本机已有内容平台会话批量上传到服务器（历史绑定无需重新扫码，
      // 同账号其它电脑即可直接发布）。失败静默忽略，不影响引擎启动。
      uploadAllLocalSessions(baseUrl, token).catch(() => {})
      return { success: true, status: publishEngineStatus, device_id: deviceId, server_base_url: baseUrl }
    } catch (err: any) {
      console.error('[PublishEngine] start failed:', err)
      return { success: false, error: err.message || String(err) }
    }
  })

  ipcMain.handle('geo-evaluation-engine:start', async (
    event,
    token: string,
    serverBaseUrl?: string,
  ) => {
    if (!validateSender(event.senderFrame)) return { success: false, error: 'invalid sender' }
    if (!token) return { success: false, error: 'missing token' }

    const baseUrl = normalizeServerBaseUrl(serverBaseUrl)
    const deviceId = getDeviceInfo().device_id
    try {
      await registerClientDevice(baseUrl, token)
      startDeviceHeartbeat(baseUrl, token)
      // 换账号/换服务器时重建引擎，避免复用旧账号 token（同机多账号隔离）
      if (!geoEvaluationEngine || geoEvaluationEngine.token !== token || geoEvaluationEngine.baseUrl !== baseUrl) {
        geoEvaluationEngine?.stop()
        geoEvaluationEngine = null
        geoEvaluationEngine = new GeoEvaluationEngine(baseUrl, token, deviceId)
        wireGeoEvaluationEngine(geoEvaluationEngine)
      }
      geoEvaluationEngine.start(15000)
      return {
        success: true,
        device_id: deviceId,
        server_base_url: baseUrl,
        ...geoEvaluationEngine.getStatus(),
      }
    } catch (err: any) {
      console.error('[GeoEvaluationEngine] start failed:', err)
      return { success: false, error: err.message || String(err) }
    }
  })

  ipcMain.handle('geo-evaluation-engine:get-status', (event) => {
    if (!validateSender(event.senderFrame)) return { status: 'unknown' }
    return geoEvaluationEngine?.getStatus?.() || {
      running: false,
      status: 'stopped',
      activeRuns: [],
    }
  })

  ipcMain.handle('geo-evaluation-engine:recheck-manual', (event, runId: number) => {
    if (!validateSender(event.senderFrame)) return { success: false, error: 'invalid sender' }
    const success = geoEvaluationEngine?.recheckManual(runId) || false
    return { success, error: success ? undefined : '当前任务没有可用的人工验证进程' }
  })

  ipcMain.handle('publish-engine:stop', (event) => {
    if (!validateSender(event.senderFrame)) return { success: false, error: 'invalid sender' }
    publishEngine?.stop()
    publishEngine = null
    geoEvaluationEngine?.stop()
    geoEvaluationEngine = null
    publishEngineStatus = 'stopped'
    stopDeviceHeartbeat()
    return { success: true, status: publishEngineStatus }
  })

  ipcMain.handle('publish-engine:get-status', (event) => {
    if (!validateSender(event.senderFrame)) return { status: 'unknown' }
    return publishEngine?.getStatus?.() || {
      running: false,
      status: publishEngineStatus,
      activeTaskId: null,
      geoEvaluation: geoEvaluationEngine?.getStatus?.() || null,
      device: getDeviceInfo(),
    }
  })

  // ==================== 消息通知 ====================

  ipcMain.on('show-notification', (event, title: string, body: string) => {
    showNotification(title, body)
  })

  // ==================== 后端管理相关 ====================

  /**
   * 获取后端状态
   */
  ipcMain.handle('backend:get-status', (event) => {
    if (!validateSender(event.senderFrame)) return { status: 'unknown' }
    return {
      status: backendManager.backendManager.getStatus(),
      pid: backendManager.backendManager['process']?.pid || null
    }
  })

  /**
   * 重启后端
   */
  ipcMain.handle('backend:restart', async (event) => {
    if (!validateSender(event.senderFrame)) return { success: false }
    const result = await backendManager.backendManager.restart()
    return { success: result }
  })

  /**
   * 获取后端配置
   */
  ipcMain.handle('backend:get-config', (event) => {
    if (!validateSender(event.senderFrame)) return null
    return backendManager.backendManager.getConfig()
  })

  // ==================== 浏览器桥接服务相关 ====================

  /**
   * 获取桥接服务状态
   */
  ipcMain.handle('bridge:get-status', (event) => {
    if (!validateSender(event.senderFrame)) return { status: 'unknown' }
    return {
      status: browserBridgeManager.browserBridgeManager.getStatus(),
      pid: browserBridgeManager.browserBridgeManager['process']?.pid || null
    }
  })

  /**
   * 重启桥接服务
   */
  ipcMain.handle('bridge:restart', async (event) => {
    if (!validateSender(event.senderFrame)) return { success: false }
    const result = await browserBridgeManager.browserBridgeManager.restart()
    return { success: result }
  })

  /**
   * 获取桥接服务配置
   */
  ipcMain.handle('bridge:get-config', (event) => {
    if (!validateSender(event.senderFrame)) return null
    return browserBridgeManager.browserBridgeManager.getConfig()
  })

  // 提示：未注册的通道会被拒绝，安全第一！
  ipcMain.handle('unknown-channel', () => {
    throw new Error('Unknown IPC channel')
  })
}

/**
 * 发送消息到渲染进程
 */
export function sendToRenderer(channel: string, ...args: any[]): void {
  const win = getMainWindow()
  win?.webContents.send(channel, ...args)
}

export function stopManagedEngines(): void {
  publishEngine?.stop()
  publishEngine = null
  geoEvaluationEngine?.stop()
  geoEvaluationEngine = null
  stopDeviceHeartbeat()
}
