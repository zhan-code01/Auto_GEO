/**
 * 本地客户端设备身份与配置管理（文档 §6.2.1 / §6.2.2）
 *
 * 职责：
 * 1. 生成并持久化 device_id（首次启动生成 UUID，写入 userData/device.json）。
 * 2. 持久化可切换的服务器地址（userData/config.json），供打包后的客户端连接不同环境。
 * 3. 通过 IPC 向渲染进程暴露设备信息与配置读写。
 *
 * 只持有「设备身份」与「服务器地址」；JWT 仍在渲染进程 localStorage（既有方案），
 * 平台登录态将在 Phase 2 由本地浏览器 Profile 保存，不经过这里。
 */

import { app, ipcMain } from 'electron'
import { join } from 'path'
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'fs'
import { randomUUID } from 'crypto'
import * as os from 'os'

const DEVICE_FILE = 'device.json'
const CONFIG_FILE = 'config.json'

interface DeviceIdentity {
  device_id: string
  created_at: string
}

interface ClientConfig {
  server_url?: string
}

function userDataDir(): string {
  return app.getPath('userData')
}

function readJson<T>(file: string, fallback: T): T {
  const p = join(userDataDir(), file)
  if (!existsSync(p)) return fallback
  try {
    return JSON.parse(readFileSync(p, 'utf8')) as T
  } catch {
    return fallback
  }
}

function writeJson(file: string, data: unknown): void {
  const dir = userDataDir()
  if (!existsSync(dir)) mkdirSync(dir, { recursive: true })
  writeFileSync(join(dir, file), JSON.stringify(data, null, 2), 'utf8')
}

/** 获取或创建设备身份（幂等：同一台机器始终用同一个 device_id）。 */
function getDeviceIdentity(): DeviceIdentity {
  const existing = readJson<DeviceIdentity | null>(DEVICE_FILE, null)
  if (existing && existing.device_id) return existing
  const identity: DeviceIdentity = {
    device_id: randomUUID(),
    created_at: new Date().toISOString(),
  }
  writeJson(DEVICE_FILE, identity)
  return identity
}

/** 设备可读名称（主机名）。 */
function deviceName(): string {
  try {
    return os.hostname() || 'AutoGeo-Client'
  } catch {
    return 'AutoGeo-Client'
  }
}

function platformName(): 'windows' | 'mac' | 'linux' {
  switch (process.platform) {
    case 'darwin':
      return 'mac'
    case 'linux':
      return 'linux'
    default:
      return 'windows'
  }
}

/**
 * 设备信息（供渲染进程注册/心跳时上报）。
 * 注意：app_version 来自打包后的 app.getVersion()；开发态返回 package.json 的版本。
 */
export function getDeviceInfo() {
  const identity = getDeviceIdentity()
  return {
    device_id: identity.device_id,
    device_name: deviceName(),
    os: platformName(),
    app_version: app.getVersion(),
  }
}

/** 读取已保存的服务器地址（空表示用默认/开发代理）。 */
export function getServerUrl(): string {
  const cfg = readJson<ClientConfig>(CONFIG_FILE, {})
  return cfg.server_url || ''
}

/** 保存服务器地址。传入空串清除自定义地址（回落到默认）。 */
export function setServerUrl(url: string): string {
  const cfg = readJson<ClientConfig>(CONFIG_FILE, {})
  cfg.server_url = (url || '').trim()
  writeJson(CONFIG_FILE, cfg)
  return cfg.server_url
}

/** 注册设备/配置相关 IPC 处理器。 */
export function registerDeviceIpcHandlers(): void {
  ipcMain.handle('device:get-info', () => getDeviceInfo())
  ipcMain.handle('device:reset-identity', () => resetDeviceIdentity())
  ipcMain.handle('config:get-server-url', () => getServerUrl())
  ipcMain.handle('config:set-server-url', (_event, url: string) => setServerUrl(url))
}

/** 删除 device.json 并重新生成 device_id（409 冲突时调用）。 */
export function resetDeviceIdentity(): DeviceIdentity {
  const p = join(userDataDir(), DEVICE_FILE)
  try {
    if (existsSync(p)) {
      // 备份旧文件而非直接删除（安全起见）
      writeFileSync(p + '.bak', readFileSync(p, 'utf8'), 'utf8')
    }
  } catch { /* 忽略备份失败 */ }
  const identity: DeviceIdentity = {
    device_id: randomUUID(),
    created_at: new Date().toISOString(),
  }
  writeJson(DEVICE_FILE, identity)
  return identity
}
