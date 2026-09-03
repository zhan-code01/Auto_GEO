import { app } from 'electron'
import { spawn, type ChildProcessWithoutNullStreams } from 'child_process'
import { join } from 'path'
import * as os from 'os'
import * as fs from 'fs'
import { getSessionPath, decodeJwtUserId } from './local-auth'

/** 获取日志文件路径，用于排查 worker 启动问题 */
function getLogPath(): string {
  const logDir = join(app.getPath('userData'), 'logs')
  if (!fs.existsSync(logDir)) {
    try { fs.mkdirSync(logDir, { recursive: true }) } catch { /* ignore */ }
  }
  return join(logDir, 'geo-evaluation-worker.log')
}

/** 写入日志文件（同时输出到 console） */
function writeLog(message: string): void {
  const timestamp = new Date().toISOString()
  const line = `[${timestamp}] ${message}`
  console.log(line)
  try {
    fs.appendFileSync(getLogPath(), line + '\n', 'utf-8')
  } catch { /* ignore */ }
}

function writeLogError(message: string): void {
  const timestamp = new Date().toISOString()
  const line = `[${timestamp}] ${message}`
  console.error(line)
  try {
    fs.appendFileSync(getLogPath(), line + '\n', 'utf-8')
  } catch { /* ignore */ }
}

/** 项目根目录：打包后为 resourcesPath，开发模式为源码根 */
function projectRoot(): string {
  return app.isPackaged ? process.resourcesPath : join(__dirname, '../../../..')
}

/**
 * 获取 geo evaluation worker 可执行文件路径
 * 优先使用打包的 exe（无需 Python），回退到 Python 模块（开发模式）
 */
function getWorkerExecutable(): { cmd: string; args: string[]; mode: 'exe' | 'python' } {
  const isWin = os.platform() === 'win32'
  const exeName = isWin ? 'geo_evaluation_worker_runner.exe' : 'geo_evaluation_worker_runner'
  const exePath = join(projectRoot(), 'backend', 'scripts', 'dist', exeName)

  if (fs.existsSync(exePath)) {
    return { cmd: exePath, args: [], mode: 'exe' }
  }

  // 回退到 Python 模块（开发模式）
  return {
    cmd: isWin ? 'python' : 'python3',
    args: ['-m', 'backend.workers.geo_evaluation_worker'],
    mode: 'python',
  }
}

export type GeoEvaluationEngineStatus =
  | 'stopped'
  | 'polling'
  | 'executing'
  | 'manual_required'
  | 'interrupted'

type EvaluationPlatform = 'doubao' | 'qianwen' | 'deepseek'
const SUPPORTED_PLATFORMS = new Set<EvaluationPlatform>(['doubao', 'qianwen', 'deepseek'])

interface ActiveWorker {
  platform: EvaluationPlatform
  process: ChildProcessWithoutNullStreams
  promise: Promise<void>
}

export class GeoEvaluationEngine {
  private running = false
  private pollTimer: NodeJS.Timeout | null = null
  private polling = false
  private readonly activeRuns = new Map<number, ActiveWorker>()

  onStatus?: (status: GeoEvaluationEngineStatus, data?: any) => void
  onProgress?: (data: any) => void

  constructor(
    readonly baseUrl: string,
    readonly token: string,
    private deviceId: string,
  ) {
    this.baseUrl = baseUrl.replace(/\/+$/, '')
  }

  start(pollIntervalMs = 15_000): void {
    if (this.running) {
      void this.pollOnce()
      return
    }
    this.running = true
    this.onStatus?.('polling', { activeRuns: [] })
    void this.pollOnce()
    this.pollTimer = setInterval(() => void this.pollOnce(), Math.max(15_000, pollIntervalMs))
  }

  stop(): void {
    this.running = false
    if (this.pollTimer) clearInterval(this.pollTimer)
    this.pollTimer = null
    for (const worker of this.activeRuns.values()) {
      worker.process.kill()
    }
    this.onStatus?.('stopped', { activeRuns: this.activeRunSummary() })
  }

  getStatus() {
    return {
      running: this.running,
      activeRuns: this.activeRunSummary(),
      status: this.running ? (this.activeRuns.size ? 'executing' : 'polling') : 'stopped',
    }
  }

  recheckManual(runId: number): boolean {
    const worker = this.activeRuns.get(runId)
    if (!worker?.process.stdin.writable) return false
    worker.process.stdin.write(`${JSON.stringify({ command: 'recheck_manual' })}\n`)
    return true
  }

  private async pollOnce(): Promise<void> {
    if (!this.running || this.polling || this.activeRuns.size >= 3) return
    this.polling = true
    try {
      const data = await this.request<any>(
        `/api/client/geo-evaluation/runs/poll?device_id=${encodeURIComponent(this.deviceId)}&limit=5`,
      )
      writeLog(`[GeoEvaluation] poll response: ${JSON.stringify(data)}`)
      const activePlatforms = new Set(Array.from(this.activeRuns.values()).map(item => item.platform))
      for (const run of data?.items || []) {
        if (!this.running || this.activeRuns.size >= 3) break
        const platforms = Array.isArray(run.platforms) ? run.platforms : []
        const runStatus = run.status || 'unknown'
        writeLog(`[GeoEvaluation] run=${run.id} platforms=${JSON.stringify(platforms)} status=${runStatus} claimedDevice=${run.claimed_device_id || ''}`)
        if (platforms.length !== 1 || !SUPPORTED_PLATFORMS.has(platforms[0])) {
          writeLog(`[GeoEvaluation] run=${run.id} skipped: invalid platforms`)
          continue
        }
        const platform = platforms[0] as EvaluationPlatform
        if (activePlatforms.has(platform)) {
          writeLog(`[GeoEvaluation] run=${run.id} skipped: platform ${platform} already active`)
          continue
        }

        // running 状态且已被当前设备 claim → 跳过 claim 直接启动 worker（worker 可能崩溃了）
        if (runStatus === 'running' && run.claimed_device_id === this.deviceId) {
          writeLog(`[GeoEvaluation] run=${run.id} already claimed by this device, restarting worker`)
          activePlatforms.add(platform)
          this.startWorker(run.id, platform)
          continue
        }

        // pending 状态 → 正常 claim 流程
        const claimed = await this.request<any>(`/api/client/geo-evaluation/runs/${run.id}/claim`, {
          method: 'POST',
          body: JSON.stringify({ device_id: this.deviceId }),
        }).catch(error => {
          writeLogError(`[GeoEvaluation] claim skipped run=${run.id}: ${error.message}`)
          return null
        })
        writeLog(`[GeoEvaluation] claim result run=${run.id}: ${JSON.stringify(claimed)}`)
        if (!claimed?.run) {
          writeLogError(`[GeoEvaluation] run=${run.id} claim returned no run, skipping`)
          continue
        }
        activePlatforms.add(platform)
        writeLog(`[GeoEvaluation] calling startWorker run=${run.id} platform=${platform}`)
        this.startWorker(run.id, platform)
      }
    } catch (error) {
      writeLogError(`[GeoEvaluation] poll failed: ${error}`)
    } finally {
      this.polling = false
    }
  }

  private startWorker(runId: number, platform: EvaluationPlatform): void {
    const root = projectRoot()
    const worker = getWorkerExecutable()
    const configuredMode = (process.env.GEO_EVALUATION_DEFAULT_BROWSER_MODE || '').toLowerCase()
    // 打包后默认 headed，让用户能看到浏览器操作；开发模式也默认 headed
    const mode = configuredMode === 'headless' || configuredMode === 'headed'
      ? configuredMode
      : 'headed'
    
    writeLog(`[GeoEvaluation] Starting worker: mode=${worker.mode}, cmd=${worker.cmd}`)
    writeLog(`[GeoEvaluation] Project root: ${root}`)
    writeLog(`[GeoEvaluation] Worker args: ${JSON.stringify(worker.args)}`)
    writeLog(`[GeoEvaluation] Run=${runId}, platform=${platform}, browserMode=${mode}`)
    writeLog(`[GeoEvaluation] exe exists: ${fs.existsSync(worker.cmd)}`)
    
    // AI 平台本地会话按用户隔离（同机多账号互不覆盖），隔离键 = JWT 里的 user_id
    const sessionUid = decodeJwtUserId(this.token) ?? undefined
    const sessionPath = getSessionPath(platform, sessionUid)
    
    // 收集 stderr 用于错误上报
    let stderrCollected = ''
    // worker 是否已经产生了输出
    let workerProducedOutput = false
    
    const child = spawn(
      worker.cmd,
      [
        ...worker.args,
        '--run-id',
        String(runId),
        '--platform',
        platform,
        '--device-id',
        this.deviceId,
        '--server',
        this.baseUrl,
        '--mode',
        mode,
        '--session-path',
        sessionPath,
      ],
      {
        cwd: root,
        shell: false,
        windowsHide: true,
        env: {
          ...process.env,
          PYTHONPATH: root,
          PYTHONUTF8: '1',
          PYTHONIOENCODING: 'utf-8',
          AUTOGEO_WORKER_TOKEN: this.token,
        },
        stdio: ['pipe', 'pipe', 'pipe'],
      },
    )
    
    // 启动超时检测：20 秒内没有任何 stdout 输出则认为 worker 卡住
    const startupTimeout = setTimeout(() => {
      if (!workerProducedOutput && child.exitCode === null) {
        writeLogError(`[GeoEvaluation] Worker startup timeout run=${runId}, killing process`)
        stderrCollected += '\n[Startup timeout: worker produced no output in 20s]'
        child.kill('SIGKILL')
      }
    }, 20000)
    
    child.on('error', (err) => {
      clearTimeout(startupTimeout)
      writeLogError(`[GeoEvaluation] Worker spawn error: ${err.message}`)
      writeLogError(`[GeoEvaluation] Failed to start: ${worker.cmd}`)
      writeLogError(`[GeoEvaluation] exe exists: ${fs.existsSync(worker.cmd)}`)
      // 上报错误到后端，让服务器日志也能看到
      this.reportWorkerError(runId, `Worker spawn failed: ${err.message}`).catch(() => {})
    })

    let stdoutBuffer = ''
    child.stdout.on('data', chunk => {
      workerProducedOutput = true
      stdoutBuffer += chunk.toString('utf8')
      const lines = stdoutBuffer.split(/\r?\n/)
      stdoutBuffer = lines.pop() || ''
      for (const line of lines) this.handleWorkerLine(runId, platform, line)
    })
    let stderrBuffer = ''
    child.stderr.on('data', chunk => {
      stderrBuffer += chunk.toString('utf8')
      stderrCollected += chunk.toString('utf8')
      const lines = stderrBuffer.split(/\r?\n/)
      stderrBuffer = lines.pop() || ''
      for (const rawLine of lines) {
        const message = rawLine.trim()
        if (message) writeLogError(`[GeoEvaluationWorker][${platform}] ${message}`)
      }
    })

    const promise = new Promise<void>((resolve, reject) => {
      child.once('error', reject)
      child.once('close', code => {
        clearTimeout(startupTimeout)
        if (stdoutBuffer.trim()) this.handleWorkerLine(runId, platform, stdoutBuffer)
        if (stderrBuffer.trim()) writeLogError(`[GeoEvaluationWorker][${platform}] ${stderrBuffer.trim()}`)
        if (code === 0) {
          writeLog(`[GeoEvaluation] Worker completed run=${runId} platform=${platform}`)
          resolve()
        } else {
          reject(new Error(`Worker exited with code ${code}`))
        }
      })
    })
      .catch(async error => {
        writeLogError(`[GeoEvaluation] Worker failed run=${runId}: ${error.message}`)
        writeLogError(`[GeoEvaluation] stderr output: ${stderrCollected.slice(-2000)}`)
        // 上报错误到后端，让服务器日志也能看到
        const errorMsg = `${error.message}. stderr: ${stderrCollected.slice(-1000)}`
        await this.reportWorkerError(runId, errorMsg).catch(() => {})
      })
      .finally(() => {
        this.activeRuns.delete(runId)
        if (this.running) {
          this.onStatus?.('polling', { activeRuns: this.activeRunSummary() })
          void this.pollOnce()
        }
      })

    this.activeRuns.set(runId, { platform, process: child, promise })
    writeLog(`[GeoEvaluation] Worker started run=${runId} platform=${platform} pid=${child.pid}`)
    this.onStatus?.('executing', { runId, platform, mode, activeRuns: this.activeRunSummary() })
  }

  /** 上报 worker 错误到后端，让服务器日志也能看到 */
  private async reportWorkerError(runId: number, message: string): Promise<void> {
    try {
      await this.request(`/api/client/geo-evaluation/runs/${runId}/interrupt`, {
        method: 'POST',
        body: JSON.stringify({
          device_id: this.deviceId,
          message: `[client_worker_error] ${message}`.slice(0, 500),
          reason: 'client_error',
        }),
      })
      writeLog(`[GeoEvaluation] Error reported to backend for run=${runId}`)
    } catch (err: any) {
      writeLogError(`[GeoEvaluation] Failed to report error to backend: ${err.message}`)
    }
  }

  private handleWorkerLine(runId: number, platform: EvaluationPlatform, raw: string): void {
    const line = raw.trim()
    if (!line) return
    try {
      const event = JSON.parse(line)
      writeLog(`[GeoEvaluationWorker][${platform}] ${JSON.stringify(event)}`)
      if (event.event === 'manual_required') {
        this.onStatus?.('manual_required', { runId, platform, ...event })
      } else if (event.event === 'worker_failed' || event.event === 'task_interrupted') {
        this.onStatus?.('interrupted', { runId, platform, ...event })
      } else if (event.event === 'question_started' || event.event === 'answer_uploaded') {
        this.onProgress?.({ runId, platform, ...event })
      } else {
        this.onStatus?.('executing', { runId, platform, ...event })
      }
    } catch {
      writeLog(`[GeoEvaluationWorker][${platform}] ${line}`)
    }
  }

  private activeRunSummary() {
    return Array.from(this.activeRuns.entries()).map(([runId, worker]) => ({
      runId,
      platform: worker.platform,
      pid: worker.process.pid,
    }))
  }

  private async request<T = any>(path: string, options: RequestInit = {}): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${this.token}`,
        ...(options.headers as Record<string, string> | undefined),
      },
    })
    if (!response.ok) {
      let message = `HTTP ${response.status}`
      try {
        const data = await response.json()
        message = data?.detail || data?.message || message
      } catch {
        // Non-JSON response.
      }
      throw new Error(message)
    }
    const data: any = await response.json()
    return (data?.data ?? data) as T
  }
}
