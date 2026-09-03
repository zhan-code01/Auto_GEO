/**
 * AutoGeo 发布引擎 - 核心调度器
 *
 * 职责：
 *  1. 定时轮询服务端待发布任务
 *  2. 领取（Claim）任务，防止多设备重复执行
 *  3. 驱动 Playwright 浏览器逐条执行发布操作
 *  4. 维护心跳（Heartbeat），保持任务不过期释放
 *  5. 检测并上报需要人工介入的场景
 *  6. 逐条上报发布结果回服务端
 *  7. 通过回调通知渲染进程（UI 更新）
 *
 * 编译为 CommonJS 模块（tsconfig "module": "CommonJS"）。
 */

import { chromium, type Browser, type BrowserContext, type Page } from 'playwright'
import { TaskApiClient } from './task-api-client'
import { loadSession, saveSession, uploadLocalSession } from './local-auth'
import { detectManualIntervention, looksLikeManualIntervention } from './browser/manual-intervention'
import { runBackendPublisher, type BackendPublisherEvent } from './backend-publisher-runner'

const AUTO_ATTEMPT_TIMEOUT_MS = Number(process.env.AUTO_GEO_AUTO_ATTEMPT_TIMEOUT_MS || 180_000)
const MANUAL_HANDOFF_TIMEOUT_MS = Number(process.env.AUTO_GEO_MANUAL_HANDOFF_TIMEOUT_MS || 1_800_000)

function autoAttemptHeadless(): boolean {
  const raw = process.env.AUTO_GEO_AUTO_ATTEMPT_HEADLESS
  if (raw == null || raw === '') return false
  return !['0', 'false', 'no', 'off'].includes(String(raw).toLowerCase())
}

function shouldOpenManualHandoff(result: any): boolean {
  const code = String(result?.error_code || result?.raw?.error_code || '').toUpperCase()
  return result?.manual_required === true && !['AUTH_REQUIRED', 'SESSION_EXPIRED', 'LOGIN_REQUIRED'].includes(code)
}

// ============================================================
//  平台发布器注册表
// ============================================================

/**
 * 平台标识 → 发布器实例的映射。
 *
 * 每个平台的发布器必须继承 BasePublisher 并实现以下接口：
 *   - platform: string
 *   - publish(page, article, account): Promise<PublishResult>
 */
const PUBLISHERS: Record<string, any> = {}

/**
 * 注册所有可用的平台发布器。
 *
 * 新增平台时只需在这里添加一行 try/catch 即可，
 * 发布器本身按需加载，不会阻塞启动流程。
 */
function registerPublishers(): void {
  // ---- 知乎 ----
  try {
    const { ZhihuPublisher } = require('./publishers/zhihu')
    if (ZhihuPublisher) {
      PUBLISHERS['zhihu'] = new ZhihuPublisher()
      console.log('[发布引擎] ✅ 已注册发布器: zhihu')
    }
  } catch (err: any) {
    console.warn('[发布引擎] ⚠️ 知乎发布器加载失败:', err.message)
  }

  // ---- 小红书 ----
  try {
    const { XiaohongshuPublisher } = require('./publishers/xiaohongshu')
    if (XiaohongshuPublisher) {
      PUBLISHERS['xiaohongshu'] = new XiaohongshuPublisher()
      console.log('[发布引擎] ✅ 已注册发布器: xiaohongshu')
    }
  } catch (err: any) {
    console.warn('[发布引擎] ⚠️ 小红书发布器加载失败:', err.message)
  }

  // ---- 简书 ----
  try {
    const { JianshuPublisher } = require('./publishers/jianshu')
    if (JianshuPublisher) {
      PUBLISHERS['jianshu'] = new JianshuPublisher()
      console.log('[发布引擎] ✅ 已注册发布器: jianshu')
    }
  } catch (err: any) {
    console.warn('[发布引擎] ⚠️ 简书发布器加载失败:', err.message)
  }

  // ---- 掘金 ----
  // 说明：掘金只实现了后端 Python 发布器（backend/services/playwright/publishers/juejinpro.py），
  // 没有 TS 版。实际发布走 runBackendPublisher() spawn Python，不调用这里的 .publish()。
  // 但 getPublisherForPlatform() 会把本注册表当“平台是否受理”的准入闸门——缺这一项会在
  // 真正发布前就抛“不支持的平台: juejin”，连 Python 都进不去。故放一个占位对象通过闸门即可。
  PUBLISHERS['juejin'] = {
    platform: 'juejin',
    publish: async () => {
      throw new Error('掘金发布应由后端 Python 发布器执行（runBackendPublisher），不应调用 TS 占位实现')
    },
  }
  console.log('[发布引擎] ✅ 已注册发布器: juejin (后端 Python 执行，TS 占位过闸)')

  // ---- 博客园 ----
  try {
    const { CnblogsPublisher } = require('./publishers/cnblogs')
    if (CnblogsPublisher) {
      PUBLISHERS['cnblogs'] = new CnblogsPublisher()
      console.log('[发布引擎] ✅ 已注册发布器: cnblogs')
    }
  } catch (err: any) {
    console.warn('[发布引擎] ⚠️ 博客园发布器加载失败:', err.message)
  }

  // ---- 豆瓣 ----
  try {
    const { DoubanPublisher } = require('./publishers/douban')
    if (DoubanPublisher) {
      PUBLISHERS['douban'] = new DoubanPublisher()
      console.log('[发布引擎] ✅ 已注册发布器: douban')
    }
  } catch (err: any) {
    console.warn('[发布引擎] ⚠️ 豆瓣发布器加载失败:', err.message)
  }

  // ---- 网易号 ----
  try {
    const { WangyiPublisher } = require('./publishers/wangyi')
    if (WangyiPublisher) {
      PUBLISHERS['wangyi'] = new WangyiPublisher()
      console.log('[发布引擎] ✅ 已注册发布器: wangyi')
    }
  } catch (err: any) {
    console.warn('[发布引擎] ⚠️ 网易号发布器加载失败:', err.message)
  }

  // ---- 百家号 ----
  try {
    const { BaijiahaoPublisher } = require('./publishers/baijiahao')
    if (BaijiahaoPublisher) {
      PUBLISHERS['baijiahao'] = new BaijiahaoPublisher()
      console.log('[发布引擎] ✅ 已注册发布器: baijiahao')
    }
  } catch (err: any) {
    console.warn('[发布引擎] ⚠️ 百家号发布器加载失败:', err.message)
  }

  // ---- 头条号 ----
  try {
    const { ToutiaoPublisher } = require('./publishers/toutiao')
    if (ToutiaoPublisher) {
      PUBLISHERS['toutiao'] = new ToutiaoPublisher()
      console.log('[发布引擎] ✅ 已注册发布器: toutiao')
    }
  } catch (err: any) {
    console.warn('[发布引擎] ⚠️ 头条号发布器加载失败:', err.message)
  }

  // ---- CSDN ----
  try {
    const { CsdnPublisher } = require('./publishers/csdn')
    if (CsdnPublisher) {
      PUBLISHERS['csdn'] = new CsdnPublisher()
      console.log('[发布引擎] ✅ 已注册发布器: csdn')
    }
  } catch (err: any) {
    console.warn('[发布引擎] ⚠️ CSDN 发布器加载失败:', err.message)
  }

  // ---- 搜狐号 ----
  try {
    const { SohuPublisher } = require('./publishers/sohu')
    if (SohuPublisher) {
      PUBLISHERS['sohu'] = new SohuPublisher()
      console.log('[发布引擎] ✅ 已注册发布器: sohu')
    }
  } catch (err: any) {
    console.warn('[发布引擎] ⚠️ 搜狐号发布器加载失败:', err.message)
  }

  // ---- B站专栏 ----
  try {
    const { BilibiliPublisher } = require('./publishers/bilibili')
    if (BilibiliPublisher) {
      PUBLISHERS['bilibili'] = new BilibiliPublisher()
      console.log('[发布引擎] ✅ 已注册发布器: bilibili')
    }
  } catch (err: any) {
    console.warn('[发布引擎] ⚠️ B站专栏发布器加载失败:', err.message)
  }

  // ---- 微信公众号 ----
  try {
    const { WeixinPublisher } = require('./publishers/weixin')
    if (WeixinPublisher) {
      PUBLISHERS['weixin'] = new WeixinPublisher()
      console.log('[发布引擎] ✅ 已注册发布器: weixin')
    }
  } catch (err: any) {
    console.warn('[发布引擎] ⚠️ 公众号发布器加载失败:', err.message)
  }

  // ---- 企鹅号 ----
  try {
    const { PenguinPublisher } = require('./publishers/penguin')
    if (PenguinPublisher) {
      PUBLISHERS['penguin'] = new PenguinPublisher()
      console.log('[发布引擎] ✅ 已注册发布器: penguin')
    }
  } catch (err: any) {
    console.warn('[发布引擎] ⚠️ 企鹅号发布器加载失败:', err.message)
  }

  // ---- 抖音 ----
  try {
    const { DouyinPublisher } = require('./publishers/douyin')
    if (DouyinPublisher) {
      PUBLISHERS['douyin'] = new DouyinPublisher()
      console.log('[发布引擎] ✅ 已注册发布器: douyin')
    }
  } catch (err: any) {
    console.warn('[发布引擎] ⚠️ 抖音发布器加载失败:', err.message)
  }

  // ---- 快手 ----
  try {
    const { KuaishouPublisher } = require('./publishers/kuaishou')
    if (KuaishouPublisher) {
      PUBLISHERS['kuaishou'] = new KuaishouPublisher()
      console.log('[发布引擎] ✅ 已注册发布器: kuaishou')
    }
  } catch (err: any) {
    console.warn('[发布引擎] ⚠️ 快手发布器加载失败:', err.message)
  }

  // ---- 微博头条文章 ----
  // 实际发布由本机 Python Playwright 执行；占位对象仅用于平台准入检查。
  PUBLISHERS['weibo'] = {
    platform: 'weibo',
    publish: async () => {
      throw new Error('微博发布应由后端 Python 发布器执行（runBackendPublisher），不应调用 TS 占位实现')
    },
  }
  console.log('[发布引擎] ✅ 已注册发布器: weibo (后端 Python 执行，TS 占位过闸)')

  // ---- 百度贴吧 ----
  // 说明：贴吧只实现了后端 Python 发布器（backend/services/playwright/publishers/tieba.py），
  // 没有 TS 版。实际发布走 runBackendPublisher() spawn Python，不调用这里的 .publish()。
  // 但 getPublisherForPlatform() 会把本注册表当“平台是否受理”的准入闸门——缺这一项会在
  // 真正发布前就抛“不支持的平台: tieba”，连 Python 都进不去。故放一个占位对象通过闸门即可。
  PUBLISHERS['tieba'] = {
    platform: 'tieba',
    // 兜底：万一被误调用（正常流程不会），也走后端 Python，行为与其它平台一致
    publish: async () => {
      throw new Error('贴吧发布应由后端 Python 发布器执行（runBackendPublisher），不应调用 TS 占位实现')
    },
  }
  console.log('[发布引擎] ✅ 已注册发布器: tieba (后端 Python 执行，TS 占位过闸)')

}

/**
 * 根据平台标识获取对应的发布器实例。
 *
 * @throws 如果平台未注册，抛出错误（调用方应确保平台合法）
 */
function getPublisherForPlatform(platform: string): any {
  const pub = PUBLISHERS[platform]
  if (!pub) {
    throw new Error(`不支持的平台: ${platform}`)
  }
  return pub
}

// ============================================================
//  前端状态回调类型
// ============================================================

/** 发布进度数据 */
export interface TaskProgressData {
  taskId: number
  recordId: number | null
  status: 'publishing' | 'success' | 'failed' | 'completed' | 'progress'
  progress: { done: number; total: number }
}

/** 人工介入数据 */
export interface ManualRequiredData {
  taskId: number
  recordId: number
  platform: string
  message: string
}

/** 引擎运行状态 */
export type EngineStatus = 'idle' | 'polling' | 'executing' | 'manual_required' | 'stopped'

// ============================================================
//  会话有效性检查
// ============================================================

function hasUsableSession(session: any): boolean {
  if (!session || typeof session !== 'object') return false
  const cookies = Array.isArray(session.cookies) ? session.cookies : []
  if (cookies.length === 0) return false
  const nowSeconds = Date.now() / 1000
  return cookies.some((cookie: any) => {
    const expires = Number(cookie?.expires)
    // expires = -1 表示会话级 cookie（关闭浏览器失效）
    // expires = 0 表示已过期
    // expires > 0 且 > nowSeconds 表示有效
    return expires === -1 || expires > nowSeconds
  })
}

// ============================================================
//  发布引擎
// ============================================================

export class PublishEngine {
  // ---- 依赖 ----
  /** 服务器地址（公开只读，供换账号时判断是否需要重建引擎） */
  readonly baseUrl: string
  /** 当前账号 JWT（公开只读，供换账号时判断是否需要重建引擎） */
  readonly token: string
  private apiClient: TaskApiClient

  // ---- 运行状态 ----
  private running: boolean = false
  private loopTimer: ReturnType<typeof setInterval> | null = null
  private activeTaskId: number | null = null
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null
  private currentBrowser: Browser | null = null
  private manualContexts: BrowserContext[] = []

  /** 上一次 tick 是否处于空闲态（无任务）；用于避免空闲时反复打印轮询日志 */
  private lastTickIdle: boolean | null = null
  private skippedActiveTickLogged: boolean = false

  // ---- UI 回调（由 ipc-handlers 设置，用于通知渲染进程） ----

  /** 发布进度更新（每条记录开始/完成时回调） */
  onTaskProgress?: (data: TaskProgressData) => void

  /** 需要人工介入（登录、验证码、编辑器异常等） */
  onManualRequired?: (data: ManualRequiredData) => void

  /** 引擎整体状态变更 */
  onEngineStatus?: (status: EngineStatus) => void

  private async launchBrowser(headless: boolean): Promise<Browser> {
    const { findChromeExe } = require('./local-auth')
    const exePath = findChromeExe()
    const launchOpts: any = {
      headless,
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-blink-features=AutomationControlled',
      ],
    }
    if (exePath) launchOpts.executablePath = exePath
    const browser = await chromium.launch(launchOpts)
    console.log(`[发布引擎] 🌐 浏览器已启动 headless=${headless}`)
    return browser
  }

  private async getOrCreateTaskBrowser(): Promise<Browser> {
    if (this.currentBrowser && this.currentBrowser.isConnected()) {
      return this.currentBrowser
    }
    this.currentBrowser = await this.launchBrowser(false)
    return this.currentBrowser
  }

  // ==========================================================
  //  构造与初始化
  // ==========================================================

  constructor(baseUrl: string, token: string, deviceId: string) {
    this.baseUrl = baseUrl
    this.token = token
    this.apiClient = new TaskApiClient(baseUrl, token, deviceId)
    registerPublishers()
    console.log('[发布引擎] 🏗️ 发布引擎已就绪')
  }

  // ==========================================================
  //  启动 / 停止
  // ==========================================================

  /**
   * 启动发布时间循环。
   *
   * 启动后立即执行一次轮询，之后按 pollIntervalMs 间隔重复。
   *
   * @param pollIntervalMs 轮询间隔（毫秒），默认 30 秒
   */
  start(pollIntervalMs: number = 30000): void {
    if (this.running) {
      console.log('[发布引擎] ⚠️ 引擎已在运行中，忽略重复启动')
      return
    }

    const safePollIntervalMs = Math.max(pollIntervalMs || 30000, 30000)
    console.log(`[发布引擎] 🚀 启动发布轮询 (间隔 ${safePollIntervalMs}ms)`)
    this.running = true
    this.lastTickIdle = null // 重置空闲态标记，让首轮重新感知并打印一次摘要
    this.onEngineStatus?.('polling')

    // 立即执行一次，避免等完第一个间隔才启动
    this.tick().catch((err) => {
      console.error('[发布引擎] 首次轮询异常:', err)
    })

    // 定时循环
    this.loopTimer = setInterval(() => {
      // 防止上一轮 tick 尚未返回时又启动新的一轮
      this.tick().catch((err) => {
        console.error('[发布引擎] 轮询异常:', err)
      })
    }, safePollIntervalMs)
  }

  getStatus(): {
    running: boolean
    status: EngineStatus
    activeTaskId: number | null
    hasHeartbeat: boolean
  } {
    let status: EngineStatus = 'stopped'
    if (this.running) {
      status = this.activeTaskId !== null ? 'executing' : 'polling'
    }
    return {
      running: this.running,
      status,
      activeTaskId: this.activeTaskId,
      hasHeartbeat: this.heartbeatTimer !== null,
    }
  }

  /**
   * 停止发布时间循环。
   *
   * 清理：
   *  - 停止轮询定时器
   *  - 停止心跳
   *  - 关闭浏览器（非人工介入模式）
   *  - 重置所有状态
   */
  stop(): void {
    console.log('[发布引擎] 🛑 正在停止发布引擎...')
    // Best effort only: on a normal close fail the claimed batch immediately.
    // A crash still falls back to the server-side lease expiry handling.
    if (this.activeTaskId) {
      this.apiClient.terminateTask(this.activeTaskId).catch((err) => {
        console.warn(`[发布引擎] 终止任务 #${this.activeTaskId} 回传失败:`, err.message)
      })
    }
    this.running = false
    this.onEngineStatus?.('stopped')

    // 清除轮询定时器
    if (this.loopTimer) {
      clearInterval(this.loopTimer)
      this.loopTimer = null
    }

    // 停止心跳
    this.stopHeartbeat()

    // 关闭浏览器（如果处于非人工介入模式）
    this.closeBrowser().catch((err) => {
      console.error('[发布引擎] 关闭浏览器时出错:', err)
    })

    this.activeTaskId = null
    this.manualContexts = []

    console.log('[发布引擎] ⏹️ 引擎已停止')
  }

  // ==========================================================
  //  轮询主循环
  // ==========================================================

  /**
   * 单次轮询周期。
   *
   * 流程：
   *  1. 拉取待处理任务列表
   *  2. 逐条尝试领取（遇到已领取的跳过）
   *  3. 获取任务完整数据
   *  4. 驱动浏览器执行发布
   *  5. 单次轮询最多处理一个任务，其余留待下一轮
   *
   * 注意：如果当前正在执行任务（activeTaskId != null），跳过本次轮询。
   */
  private async tick(): Promise<void> {
    // ---- 正在执行任务中 → 跳过 ----
    if (this.activeTaskId !== null) {
      if (!this.skippedActiveTickLogged) {
        console.log('[发布引擎] ⏭️ 正在执行任务中，暂停轮询')
        this.skippedActiveTickLogged = true
      }
      return
    }
    this.skippedActiveTickLogged = false

    // ---- 引擎已停止 → 跳过 ----
    if (!this.running) return

    this.onEngineStatus?.('polling')

    try {
      // 1. 拉取待执行任务
      const tasks = await this.apiClient.pollTasks()
      if (tasks.length === 0) {
        // 空闲态：仅在状态切换时打印一次，避免每个轮询周期都刷屏
        if (this.lastTickIdle !== true) {
          console.log('[发布引擎] 💤 暂无待发布任务，进入空闲态')
          this.lastTickIdle = true
        }
        this.onEngineStatus?.('idle')
        return
      }

      // 检测到任务：从空闲切回忙碌时打印一次
      if (this.lastTickIdle !== false) {
        console.log('[发布引擎] 🔔 检测到待发布任务，开始处理')
        this.lastTickIdle = false
      }

      console.log(`[发布引擎] 📋 获取到 ${tasks.length} 个待处理任务`)

      // 2. 遍历任务，尝试领取并执行
      for (const task of tasks) {
        if (!this.running) break

        const taskId: number = task.id

        // 2a. 尝试领取（409 → 已被抢占，跳过）
        const claimResult = await this.apiClient.claimTask(taskId)
        if (!claimResult) {
          // 日志已在 claimTask 内部输出
          continue
        }

        if (claimResult.settled || claimResult.recordIds.length === 0) {
          console.warn(`[发布引擎] ⚠️ 任务 #${taskId} 没有待执行发布记录，跳过本轮执行`)
          continue
        }

        console.log(
          `[发布引擎] ✅ 已领取任务 #${taskId} ` +
            `(记录数: ${claimResult.recordIds.length}, 到期: ${claimResult.claimExpiresAt})`,
        )

        // 2b. 获取任务完整数据
        let payload
        try {
          payload = await this.apiClient.getPayload(taskId)
        } catch (err: any) {
          console.error(`[发布引擎] ❌ 获取任务 #${taskId} 数据失败:`, err.message)
          // 数据获取失败则不再处理此任务，让 claim 自然过期
          continue
        }

        console.log(
          `[发布引擎] 📦 任务 #${taskId} 数据就绪, 共 ${payload.records.length} 条发布记录`,
        )

        if (payload.records.length === 0) {
          console.warn(`[发布引擎] ⚠️ 任务 #${taskId} payload 为空，跳过执行`)
          continue
        }

        // 2c. 执行任务
        try {
          await this.executeTask(payload.task, payload.records)
        } catch (err: any) {
          console.error(`[发布引擎] ❌ 任务 #${taskId} 执行失败:`, err.message)
        }

        // 一个轮询周期只处理一个任务，其余留待下次
        // （防止连续处理多个长任务导致心跳过期）
        break
      }
    } catch (err: any) {
      console.error('[发布引擎] 轮询出错:', err.message)
    }
  }

  // ==========================================================
  //  执行单个任务
  // ==========================================================

  /**
   * 执行发布任务的核心流程。
   *
   * 步骤：
   *  1. 启动心跳循环（每 4 分钟一次，TTL 为 10 分钟）
   *  2. 启动 Chromium 浏览器（可见模式，用户可观察进度）
   *  3. 逐条处理发布记录：
   *     a. 获取对应平台的发布器
   *     b. 加载平台登录态
   *     c. 创建浏览器上下文（带登录态）
   *     d. 调用发布器执行发布
   *     e. 处理人工介入 / 成功 / 失败三种结果
   *     f. 上报结果回服务端
   *     g. 通知 UI 进度
   *  4. 关闭浏览器（人工介入时保持打开）
   *  5. 停止心跳
   *
   * @param task    任务元数据
   * @param records 发布记录列表（每条对应一个平台的一篇文章）
   */
  private async executeTask(task: any, records: any[]): Promise<void> {
    const taskId: number = task.id
    this.activeTaskId = taskId
    this.manualContexts = []
    this.onEngineStatus?.('executing')

    console.log(`[发布引擎] 🎯 开始执行任务 #${taskId}`)
    console.log(`[发布引擎] 📊 共 ${records.length} 条发布记录`)

    // ======================================================
    //  1. 启动心跳（每 4 分钟一次，TTL 为 10 分钟）
    // ======================================================
    this.startHeartbeat(taskId)

    const total = records.length
    let done = 0

    // ======================================================
    //  3. 逐条处理
    // ======================================================
    for (const record of records) {
      if (!this.running) {
        console.log('[发布引擎] ⏹️ 引擎已停止, 中断任务执行')
        break
      }

      const recordId: number = record.record_id
      const platform: string = record.platform || ''
      const accountName: string = record.account_name || '未知帐号'
      const articleTitle: string = record.article?.title || '(无标题)'

      console.log(
        `[发布引擎] 📝 [${done + 1}/${total}] 记录 #${recordId} → 平台: ${platform}, ` +
          `帐号: ${accountName}, 标题: "${articleTitle.slice(0, 30)}"`,
      )

      this.onTaskProgress?.({
        taskId,
        recordId,
        status: 'publishing',
        progress: { done, total },
      })

      try {
        await this.apiClient.startRecord(taskId, recordId)
      } catch (err: any) {
        console.error(`[发布引擎] ❌ 无法开始记录 #${recordId}:`, err.message)
        await this.reportAndContinue(taskId, recordId, `无法开始发布任务：${err.message}`)
        done++
        continue
      }

      // ---- 3a. 获取发布器 ----
      let publisher: any
      try {
        publisher = getPublisherForPlatform(platform)
      } catch (err: any) {
        console.error(`[发布引擎] ❌ 记录 #${recordId} → ${err.message}`)
        // 上报失败（平台不支持）
        await this.reportAndContinue(taskId, recordId, err.message)
        done++
        this.onTaskProgress?.({
          taskId,
          recordId,
          status: 'failed',
          progress: { done, total },
        })
        continue
      }

      try {
        // ---- 3b. 构造发布器参数 ----
        const article = {
          ...(record.article || {}),
          id: record.article?.id ?? null,
          title: record.article?.title ?? null,
          content: record.article?.content ?? null,
        }
        const account = {
          account_id: record.account_id ?? null,
          account_name: record.account_name || null,
          platform: record.platform || null,
          auth_mode: 'cookie', // 当前全部使用 cookie 方式
          // 贴吧默认目标吧：服务端从 Account.tags 解析好的干净字段，透传给后端发布器
          target_forum: record.target_forum || null,
        }

        const attempt = await this.runHeadlessPublishAttempt(
          taskId,
          recordId,
          platform,
          publisher,
          article,
          account,
        )

        if (attempt.result.manual_required) {
          const message = attempt.result.manual_reason || '需要人工介入'
          console.log(
            `[发布引擎] 🙋 任务 #${taskId} 记录 #${recordId} 发布尝试触发人工介入: ${message}`,
          )
          this.onEngineStatus?.('manual_required')
          this.onManualRequired?.({ taskId, recordId, platform, message })
        }

        let result = attempt.result

        if (result.manual_required) {
          try {
            await this.apiClient.reportResult(
              taskId,
              recordId,
              'manual_required',
              undefined,
              result.manual_reason || '需要人工介入',
            )
          } catch (err: any) {
            console.error('[发布引擎] 通知服务端人工介入失败:', err.message)
          }

          if (!shouldOpenManualHandoff(result)) {
            done++
            this.onTaskProgress?.({
              taskId,
              recordId,
              status: 'progress',
              progress: { done, total },
            })
            continue
          }

          try {
            await this.apiClient.resumeManualRecord(taskId, recordId)
          } catch (err: any) {
            console.error('[发布引擎] 恢复人工接管记录失败:', err.message)
            done++
            this.onTaskProgress?.({
              taskId,
              recordId,
              status: 'progress',
              progress: { done, total },
            })
            continue
          }

          console.log(`[发布引擎] 🧭 启动 headed 人工接管发布: task=${taskId}, record=${recordId}`)
          const handoff = await this.runManualHandoffAttempt(taskId, recordId, platform, article, account)
          result = handoff.result
        }

        // 会话漫游：发布后把（可能被 Python 发布器刷新过的）本机会话回传服务器，
        // 保持其它电脑的漫游副本新鲜。失败不影响发布结果。
        if (account.account_id) {
          uploadLocalSession(this.baseUrl, this.token, platform, account.account_id).catch(() => {})
        }

        if (result.manual_required) {
          const message = result.manual_reason || result.error_msg || result.error || '仍需要人工介入'
          try {
            await this.apiClient.reportResult(taskId, recordId, 'manual_required', undefined, message)
          } catch (err: any) {
            console.error('[发布引擎] 通知服务端人工介入失败:', err.message)
          }
          done++
          this.onTaskProgress?.({
            taskId,
            recordId,
            status: 'progress',
            progress: { done, total },
          })
          continue
        }

        if (result.success) {
          // --- 发布成功 ---
          const report = await this.apiClient.reportResult(
            taskId,
            recordId,
            'success',
            result.url,
            undefined,
            result.auth_status,
          )
          done++

          console.log(
            `[发布引擎] ✅ 记录 #${recordId} 发布成功` +
              (result.url ? ` → ${result.url}` : ''),
          )

          this.onTaskProgress?.({
            taskId,
            recordId,
            status: report.settled ? 'completed' : 'success',
            progress: { done, total },
          })

          if (report.settled) {
            console.log(`[发布引擎] 🎉 任务 #${taskId} 全部完成！`)
          }
        } else {
          // --- 发布失败 ---
          const errorMessage = result.error || result.error_msg || '发布失败'
          await this.apiClient.reportResult(
            taskId,
            recordId,
            'failed',
            undefined,
            errorMessage,
            result.auth_status,
          )
          done++

          console.log(
            `[发布引擎] ❌ 记录 #${recordId} 发布失败: ${errorMessage || '未知错误'}`,
          )

          this.onTaskProgress?.({
            taskId,
            recordId,
            status: 'failed',
            progress: { done, total },
          })
        }
      } catch (err: any) {
        // ---- 记录级别的异常保护 ----
        // 单条记录失败不应该导致整个引擎崩溃
        console.error(
          `[发布引擎] ❌ 记录 #${recordId} 执行异常: ${err.message}`,
        )

        await this.reportAndContinue(taskId, recordId, err.message)
        done++

        this.onTaskProgress?.({
          taskId,
          recordId,
          status: 'failed',
          progress: { done, total },
        })
      }
    }

    // ======================================================
    //  4. 清理
    // ======================================================
    this.stopHeartbeat()

    await this.closeBrowser()

    this.activeTaskId = null
    this.onEngineStatus?.('idle')
    console.log(`[发布引擎] 🏁 任务 #${taskId} 处理完毕`)
  }

  // ==========================================================
  //  心跳维护
  // ==========================================================

  /**
   * 启动心跳循环。
   *
   * 心跳间隔设为 4 分钟，远小于服务端 TTL（通常 10 分钟），
   * 留出充足余量应对网络波动。
   *
   * 启动后立即发一次，之后按间隔定时发送。
   */
  private startHeartbeat(taskId: number): void {
    this.stopHeartbeat() // 先清除旧的心跳（防御性编程）

    console.log(`[发布引擎] 💓 启动心跳 → 任务 #${taskId} (间隔 4 分钟)`)

    // 立即发送一次
    this.apiClient.heartbeat(taskId).catch((err) => {
      console.error(`[发布引擎] 心跳发送失败 (任务 #${taskId}):`, err.message)
    })

    // 每 4 分钟定时发送
    this.heartbeatTimer = setInterval(() => {
      if (!this.running) return

      this.apiClient.heartbeat(taskId).catch((err) => {
        console.error(`[发布引擎] 心跳发送失败 (任务 #${taskId}):`, err.message)
      })
    }, 4 * 60 * 1000) // 4 分钟
  }

  /**
   * 停止心跳循环。
   */
  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer)
      this.heartbeatTimer = null
      console.log('[发布引擎] 💔 心跳已停止')
    }
  }

  // ==========================================================
  //  浏览器管理
  // ==========================================================

  /**
   * 发布器抛错后的兜底检测：检查页面是否已经跳转到已发布文章页，
   * 或者出现了成功提示文字。如果检测到，返回当前 URL 作为成功结果。
   *
   * 这解决了一个常见问题：发布器 waitForResult 超时后抛错，
   * 但文章实际上已经发布成功了（只是页面 URL 变化或提示出现得慢）。
   */
  private async tryRecoverPublishResult(page: Page, platform: string): Promise<string | null> {
    try {
      const url = page.url()
      // 1. 检查 URL 是否已跳转到已发布文章页
      if (platform === 'zhihu') {
        try {
          const parsed = new URL(url)
          // 对齐 zhihu.ts::isZhihuPublishedArticleUrl：/p/<id>/edit 也算成功（文章已创建）
          if (parsed.hostname === 'zhuanlan.zhihu.com' && /^\/p\/\d+(?:\/edit)?\/?$/i.test(parsed.pathname)) {
            return url
          }
        } catch {
          // ignore
        }
      }
      // 2. 检查页面上是否有成功提示文字
      const successKeywords: Record<string, string[]> = {
        zhihu: ['发布成功', '文章已发布', '审核中'],
      }
      const keywords = successKeywords[platform] || []
      for (const kw of keywords) {
        const node = page.getByText(kw, { exact: false }).first()
        if ((await node.count()) > 0 && (await node.isVisible({ timeout: 500 }).catch(() => false))) {
          return url
        }
      }
    } catch {
      // ignore
    }
    return null
  }

  private async runHeadlessPublishAttempt(
    taskId: number,
    recordId: number,
    platform: string,
    publisher: any,
    article: any,
    account: any,
  ): Promise<{ result: any; pageUrl?: string }> {
    // 会话漫游：本机无会话时自动从服务器拉取（A 电脑绑定，B 电脑可直接发布）
    const session = await this.ensureSessionForPublish(platform, account?.account_id ?? null)
    if (!session) {
      return {
        result: {
          success: false,
          manual_required: true,
          manual_reason: `平台 ${platform} 尚未在本机完成登录授权，请先在账号管理中登录后再发布`,
          error_code: 'AUTH_REQUIRED',
        },
      }
    }

    // 检查会话是否有效（Cookie 是否过期）
    if (!hasUsableSession(session)) {
      return {
        result: {
          success: false,
          manual_required: true,
          manual_reason: `平台 ${platform} 的登录会话已过期，请重新在账号管理中登录授权`,
          error_code: 'SESSION_EXPIRED',
        },
      }
    }

    const result = await runBackendPublisher(platform, article, account, {
      attemptMode: 'auto_attempt',
      headless: autoAttemptHeadless(),
      timeoutMs: AUTO_ATTEMPT_TIMEOUT_MS,
      onEvent: (event) => this.handleBackendPublisherEvent(taskId, recordId, platform, event),
    })
    return { result, pageUrl: result.url || result.platform_url }

    const browser = await this.getOrCreateTaskBrowser()
    let context: BrowserContext = undefined as any
    try {
      context = await browser.newContext({
        viewport: { width: 1280, height: 900 },
        locale: 'zh-CN',
        timezoneId: 'Asia/Shanghai',
        storageState: session as any,
      })
      const page = await context.newPage()

      const beforePublishManual = await detectManualIntervention(page, platform, 'before_publish')
      if (beforePublishManual.manualRequired) {
        return {
          result: {
            success: false,
            manual_required: true,
            manual_reason: beforePublishManual.reason,
            error_code: beforePublishManual.errorCode,
          },
          pageUrl: page.url(),
        }
      }

      let result
      try {
        result = await publisher.publish(page, article, account)
      } catch (err: any) {
        const message = err?.message || String(err)
        // 发布器抛错（如超时）时，文章可能其实已经发布成功。
        // 做一次兜底检查：如果 URL 已跳转到文章页或出现成功提示，则判定为成功。
        const recovered = await this.tryRecoverPublishResult(page, platform)
        if (recovered) {
          console.log(`[发布引擎] 🔄 发布器抛错但兜底检测到已发布成功: ${message}`)
          result = { success: true, url: recovered }
          const afterPublishManual2 = await detectManualIntervention(page, platform, 'after_publish')
          if (afterPublishManual2.manualRequired) {
            return {
              result: {
                success: false,
                manual_required: true,
                manual_reason: afterPublishManual2.reason,
                error_code: afterPublishManual2.errorCode,
              },
              pageUrl: page.url(),
            }
          }
          return { result, pageUrl: page.url() }
        }
        if (!looksLikeManualIntervention(message)) throw err
        result = {
          success: false,
          manual_required: true,
          manual_reason: message,
        }
      }

      const afterPublishManual = await detectManualIntervention(page, platform, 'after_publish')
      if (!result?.success && afterPublishManual.manualRequired) {
        return {
          result: {
            success: false,
            manual_required: true,
            manual_reason: afterPublishManual.reason,
            error_code: afterPublishManual.errorCode,
          },
          pageUrl: page.url(),
        }
      }
      return { result, pageUrl: page.url() }
    } finally {
      try {
        await context?.close()
      } catch {
        // ignore
      }
    }
  }

  private async runManualHandoffAttempt(
    taskId: number,
    recordId: number,
    platform: string,
    article: any,
    account: any,
  ): Promise<{ result: any; pageUrl?: string }> {
    // 会话漫游：进入人工接管前确保本机有可用会话（无则从服务器拉取）
    await this.ensureSessionForPublish(platform, account?.account_id ?? null)
    const result = await runBackendPublisher(platform, article, account, {
      attemptMode: 'manual_handoff',
      headless: false,
      // 微博点选验证按产品约定持续等待；其它平台保持原人工接管超时。
      timeoutMs: platform === 'weibo' ? 0 : MANUAL_HANDOFF_TIMEOUT_MS,
      onEvent: (event) => this.handleBackendPublisherEvent(taskId, recordId, platform, event),
    })
    return { result, pageUrl: result.url || result.platform_url }
  }

  /**
   * 会话漫游：确保本机存在可用的平台会话。
   * - 本机会话有效 → 直接使用；
   * - 本机无会话或已过期 → 从服务器拉取最新漫游会话（A 电脑绑定，B 电脑可直接发布）；
   * - 都没有 → 返回 null（调用方走 AUTH_REQUIRED / 人工介入）。
   */
  private async ensureSessionForPublish(
    platform: string,
    accountId: number | null | undefined,
  ): Promise<object | null> {
    let session = loadSession(platform, accountId ?? null)
    if (session && hasUsableSession(session)) {
      return session
    }
    // 本机无会话 / 会话已过期 → 尝试从服务器拉取最新漫游会话
    if (accountId) {
      const downloaded = await this.downloadRoamingSession(platform, accountId)
      if (downloaded) return downloaded
    }
    return session // 可能为 null 或已过期，交由调用方处理
  }

  /** 从服务器拉取指定账号的漫游会话并保存到本机（无则返回 null）。 */
  private async downloadRoamingSession(platform: string, accountId: number): Promise<object | null> {
    try {
      const resp = await fetch(`${this.baseUrl}/api/auth/roam-session/${accountId}`, {
        headers: { Authorization: `Bearer ${this.token}` },
      })
      if (!resp.ok) {
        console.warn(`[发布引擎] 漫游会话拉取失败: HTTP ${resp.status}`)
        return null
      }
      const data = await resp.json()
      const state = data?.storage_state
      if (state && Array.isArray(state.cookies) && state.cookies.length > 0) {
        saveSession(platform, state, accountId)
        console.log(`[发布引擎] 🔄 已从服务器拉取漫游会话: platform=${platform} accountId=${accountId}`)
        return state
      }
      return null
    } catch (err: any) {
      console.warn(`[发布引擎] 漫游会话下载异常: ${err?.message || String(err)}`)
      return null
    }
  }

  private handleBackendPublisherEvent(
    taskId: number,
    recordId: number,
    platform: string,
    event: BackendPublisherEvent,
  ): void {
    if (event.type === 'manual_required') {
      const message =
        event.message ||
        event.matched_text ||
        event.risk_type ||
        event.error_code ||
        '需要人工介入'
      console.log(`[发布引擎] 🙋 ${platform} 需要人工处理: ${message}`)
      this.onEngineStatus?.('manual_required')
      this.onManualRequired?.({ taskId, recordId, platform, message })
    } else if (event.type === 'manual_resolved') {
      console.log(`[发布引擎] ✅ ${platform} 人工验证已解除，继续发布`)
      this.onEngineStatus?.('executing')
    } else if (event.type === 'manual_timeout') {
      console.warn(`[发布引擎] ⏱️ ${platform} 人工验证等待超时`)
    }
  }

  private async resolveManualIntervention(
    taskId: number,
    recordId: number,
    platform: string,
    url: string,
    message: string,
  ): Promise<boolean> {
    const browser = await this.getOrCreateTaskBrowser()
    let context: BrowserContext = undefined as any
    try {
      const session = loadSession(platform)
      context = await browser.newContext({
        viewport: { width: 1280, height: 900 },
        locale: 'zh-CN',
        timezoneId: 'Asia/Shanghai',
        ...(session ? { storageState: session as any } : {}),
      })
      const page = await context.newPage()
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 }).catch(async () => {
        if (url !== 'about:blank') {
          await page.goto(url, { waitUntil: 'load', timeout: 30000 })
        }
      })
      await page.bringToFront().catch(() => {})
      console.warn(`[发布引擎] 🙋 请在打开的浏览器中处理人工验证：${message}`)

      while (this.running) {
        const detection = await detectManualIntervention(page, platform, 'manual_resolution')
        if (!detection.manualRequired) {
          const state = await context!.storageState()
          saveSession(platform, state)
          console.log(`[发布引擎] ✅ 人工验证已处理，已保存 ${platform} 会话，将回到可见浏览器发布尝试继续`)
          return true
        }
        await page.waitForTimeout(5000)
      }
      return false
    } finally {
      try {
        await context?.close()
      } catch {
        // ignore
      }
    }
  }

  private async pageNeedsManualIntervention(page: Page): Promise<boolean> {
    try {
      const url = page.url().toLowerCase()
      if (['login', 'signin', 'passport', 'captcha', 'verify', 'security'].some((token) => url.includes(token))) {
        return true
      }
      return await page.evaluate<boolean>(() => {
        const keywords = [
          '请登录',
          '登录后',
          '扫码登录',
          '验证码',
          '人机验证',
          '滑块',
          '安全验证',
          '身份验证',
          '短信验证',
          '操作频繁',
          '请求频繁',
          '账号异常',
          '风险提示',
          '检测到风险',
        ]
        const text = (document.body?.innerText || '').slice(0, 20000)
        return keywords.some((keyword) => text.includes(keyword))
      })
    } catch {
      return true
    }
  }

  /**
   * 关闭当前浏览器实例。
   */
  private async closeBrowser(): Promise<void> {
    if (this.currentBrowser) {
      try {
        await this.currentBrowser.close()
        console.log('[发布引擎] 🌐 浏览器已关闭')
      } catch (err: any) {
        console.error('[发布引擎] 关闭浏览器异常:', err.message)
      }
      this.currentBrowser = null
    }
    this.manualContexts = []
  }

  // ==========================================================
  //  辅助方法
  // ==========================================================

  /**
   * 上报失败并继续（不影响后续记录）。
   *
   * 如果上报本身也失败了，仅记录日志，不中断循环。
   */
  private async reportAndContinue(
    taskId: number,
    recordId: number,
    errorMsg: string,
  ): Promise<void> {
    try {
      await this.apiClient.reportResult(taskId, recordId, 'failed', undefined, errorMsg)
    } catch (reportErr: any) {
      console.error(
        `[发布引擎] 上报失败结果时出错 (任务 #${taskId} 记录 #${recordId}):`,
        reportErr.message,
      )
    }
  }
}
