/**
 * 本地客户端设备服务（渲染进程侧，文档 §6.2.1 / §6.2.2）
 *
 * JWT 存在渲染进程 localStorage，因此 HTTP（注册/心跳）由渲染进程发起；
 * 主进程只提供设备身份（device_id / 版本 / os）。登录成功后注册设备并启动心跳循环，
 * 登出或会话失效时停止。非 Electron 环境（纯 H5/网页）自动降级为 no-op。
 *
 * 心跳异常处理策略：
 *   - 409（设备归属冲突）→ 自动重置 UUID 并重试注册
 *   - 403（无权访问）   → 自动重置 UUID 并重试注册
 *   - 404（设备未注册）  → 重新注册
 *   - 网络错误          → 静默跳过（下次心跳自动恢复）
 *   - 其他错误          → 记录日志，不中断循环
 */

import { post } from '@/services/api'

const HEARTBEAT_INTERVAL_MS = 30_000

let heartbeatTimer: number | null = null
let registeredDeviceId: string | null = null

interface MainDeviceInfo {
  device_id: string
  device_name: string
  os: string
  app_version: string
}

async function getDeviceInfoFromMain(): Promise<MainDeviceInfo | null> {
  const electronAPI = (window as any).electronAPI
  if (!electronAPI?.device?.getInfo) return null
  try {
    return await electronAPI.device.getInfo()
  } catch (e) {
    console.warn('[device] 读取设备信息失败:', e)
    return null
  }
}

/** 向服务器注册/刷新当前设备，返回设备记录或 null。 */
export async function registerCurrentDevice(capabilities?: Record<string, unknown>) {
  const info = await getDeviceInfoFromMain()
  if (!info) return null

  const doRegister = async (deviceInfo: MainDeviceInfo): Promise<any> => {
    const resp = await post('/client/devices/register', {
      device_id: deviceInfo.device_id,
      device_name: deviceInfo.device_name,
      os: deviceInfo.os,
      app_version: deviceInfo.app_version,
      capabilities: capabilities ?? { local_publish: true },
    })
    const device = (resp as any)?.data?.device ?? null
    return device
  }

  try {
    const device = await doRegister(info)
    registeredDeviceId = device?.device_id ?? info.device_id
    return device
  } catch (e: any) {
    const status = e?.response?.status
    const msg = String(e?.response?.data?.detail || e?.message || '')

    // 409 冲突 / 403 无权访问 → UUID 被旧账号占用 → 重置并重试
    if (status === 409 || status === 403 || msg.includes('已被其他账号占用') || msg.includes('无权访问')) {
      console.warn(`[device] 设备归属异常 (${status})，自动重置设备标识并重试...`)
      await (window as any).electronAPI?.device?.resetIdentity?.()
      const newInfo = await getDeviceInfoFromMain()
      if (newInfo) {
        try {
          const device = await doRegister(newInfo)
          registeredDeviceId = device?.device_id ?? newInfo.device_id
          return device
        } catch (retryErr: any) {
          console.warn('[device] 重置后注册仍失败:', retryErr?.response?.data?.detail || retryErr?.message || String(retryErr))
          return null
        }
      }
      return null
    }

    console.warn('[device] 注册失败:', msg || String(e))
    return null
  }
}

/** 发送一次心跳。失败时按策略自动恢复，不中断循环。 */
export async function sendHeartbeat(): Promise<void> {
  const info = await getDeviceInfoFromMain()
  if (!info) return
  try {
    await post('/client/devices/heartbeat', { device_id: info.device_id })
  } catch (e: any) {
    const status = e?.response?.status
    const msg = String(e?.response?.data?.detail || e?.message || '')

    // 403 无权访问或 404 未注册 → 设备状态异常，尝试重新注册
    if (status === 403 || status === 404 || msg.includes('无权访问') || msg.includes('未注册')) {
      console.warn(`[device] 心跳被拒 (${status})，尝试重新注册设备...`)
      const device = await registerCurrentDevice()
      if (!device) {
        console.warn('[device] 设备重新注册失败，本次心跳放弃（下次重试）')
      }
      return
    }

    // 409 冲突 → 重置 UUID
    if (status === 409 || msg.includes('已被其他账号占用')) {
      console.warn('[device] 心跳 409，自动重置设备标识...')
      await (window as any).electronAPI?.device?.resetIdentity?.()
      const device = await registerCurrentDevice()
      if (!device) {
        console.warn('[device] 重置后重新注册失败，本次心跳放弃')
      }
      return
    }

    // 网络错误 → 静默跳过
    if (!status || status === 0 || status >= 500) {
      return
    }

    console.warn('[device] 心跳失败:', msg || String(e))
  }
}

/** 启动心跳循环（登录后调用）。 */
export function startHeartbeatLoop(): void {
  stopHeartbeatLoop()
  void sendHeartbeat()
  heartbeatTimer = window.setInterval(() => void sendHeartbeat(), HEARTBEAT_INTERVAL_MS)
}

/** 停止心跳循环（登出/会话失效时调用）。 */
export function stopHeartbeatLoop(): void {
  if (heartbeatTimer !== null) {
    clearInterval(heartbeatTimer)
    heartbeatTimer = null
  }
  registeredDeviceId = null
}

export function getRegisteredDeviceId(): string | null {
  return registeredDeviceId
}
