import { execFileSync, spawn } from 'child_process'
import { app } from 'electron'
import * as fs from 'fs'
import * as os from 'os'
import * as path from 'path'
import { getSessionPath, hasSession } from './local-auth'

export type BackendPublishRunnerResult = {
  success: boolean
  url?: string
  platform_url?: string
  error?: string
  error_msg?: string
  manual_required?: boolean
  manual_reason?: string
  manual_timeout?: boolean
  error_code?: string
  risk_type?: string
  auth_status?: string
  raw?: any
}

export type BackendPublisherAttemptMode = 'auto_attempt' | 'manual_handoff'

export type BackendPublisherEvent = {
  type?: string
  platform?: string
  stage?: string
  error_code?: string
  risk_type?: string
  message?: string
  matched_text?: string
  page_url?: string
  [key: string]: any
}

const DEFAULT_RUNNER_TIMEOUT_MS = 180_000
const EVENT_PREFIX = '__AUTO_GEO_EVENT__ '

function projectRoot(): string {
  const isDev = process.env.NODE_ENV === 'development' || !app.isPackaged
  if (isDev) return path.join(__dirname, '../../../..')
  return process.resourcesPath
}

/**
 * 获取发布器可执行文件路径
 * 开发模式（npm run dev）直接跑 Python 源码，保证改完 publisher 立即生效；
 * 打包态优先用自带的 exe（无需 Python），exe 缺失时回退 Python。
 */
function getRunnerExecutable(): { cmd: string; args: string[]; mode: 'exe' | 'python' } {
  const isWin = os.platform() === 'win32'
  const exeName = isWin ? 'local_client_publish_runner.exe' : 'local_client_publish_runner'
  const exePath = path.join(projectRoot(), 'backend', 'scripts', 'dist', exeName)
  const pyPath = path.join(projectRoot(), 'backend', 'scripts', 'local_client_publish_runner.py')

  // 开发模式：强制走 Python 源码，避免每次改动都要重打 exe 才能验证。
  const isDev = process.env.NODE_ENV === 'development' || !app.isPackaged
  if (isDev) {
    return {
      cmd: isWin ? 'python' : 'python3',
      args: [pyPath],
      mode: 'python',
    }
  }

  // 打包态：优先用自带的 exe（无需 Python 环境），exe 缺失时再回退到 Python。
  if (fs.existsSync(exePath)) {
    return { cmd: exePath, args: [], mode: 'exe' }
  }
  return {
    cmd: isWin ? 'python' : 'python3',
    args: [pyPath],
    mode: 'python',
  }
}

function killProcessTree(pid: number | undefined): void {
  if (!pid) return
  try {
    if (os.platform() === 'win32') {
      execFileSync('taskkill', ['/F', '/T', '/PID', String(pid)], { windowsHide: true })
      return
    }
    process.kill(pid, 'SIGTERM')
  } catch {
    // ignore kill failures
  }
}

function parseLastJsonLine(stdout: string): BackendPublishRunnerResult {
  const lines = stdout
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
  for (let index = lines.length - 1; index >= 0; index--) {
    const line = lines[index]
    if (!line.startsWith('{')) continue
    try {
      return JSON.parse(line)
    } catch {
      // keep scanning
    }
  }
  throw new Error('后端发布器未返回有效 JSON 结果')
}

export async function runBackendPublisher(
  platform: string,
  article: any,
  account: any,
  options: {
    headless?: boolean
    timeoutMs?: number
    attemptMode?: BackendPublisherAttemptMode
    onEvent?: (event: BackendPublisherEvent) => void
  } = {},
): Promise<BackendPublishRunnerResult> {
  if (!hasSession(platform, account?.account_id ?? null)) {
    return {
      success: false,
      manual_required: true,
      manual_reason: `平台 ${platform} 尚未在本机完成登录授权，请先在账号管理中登录后再发布`,
      error: 'AUTH_REQUIRED',
      error_msg: 'AUTH_REQUIRED',
    }
  }

  // 1. 获取发布器可执行文件
  const runner = getRunnerExecutable()
  if (runner.mode === 'python') {
    // 开发模式：检查 Python 是否可用
    try {
      execFileSync(runner.cmd, ['--version'], { windowsHide: true, stdio: 'pipe' })
    } catch {
      return {
        success: false,
        error: 'Python 未安装。发布功能需要 Python 3.10+ 环境。',
        error_msg: 'Python 未安装',
      }
    }
  }

  // 2. 准备输入文件
  const inputDir = fs.mkdtempSync(path.join(os.tmpdir(), 'autogeo-publish-'))
  const inputPath = path.join(inputDir, 'payload.json')
  fs.writeFileSync(
    inputPath,
    JSON.stringify(
      {
        platform,
        article,
        account,
        storage_state_path: getSessionPath(platform, account?.account_id ?? null),
        headless: options.headless === true,
        attempt_mode: options.attemptMode || 'auto_attempt',
      },
      null,
      2,
    ),
    'utf-8',
  )

  console.log(`[BackendPublisher] 模式: ${runner.mode}, 命令: ${runner.cmd}`)
  console.log(`[BackendPublisher] 平台: ${platform}, headless: ${options.headless === true}`)

  // 3. 执行发布器
  return await new Promise((resolve, reject) => {
    let settled = false
    const childArgs = [...runner.args, '--input', inputPath]
    const child = spawn(runner.cmd, childArgs, {
      cwd: projectRoot(),
      shell: false,
      windowsHide: true,
      env: {
        ...process.env,
        PYTHONPATH: projectRoot(),
        PYTHONUTF8: '1',
        PYTHONIOENCODING: 'utf-8',
        AUTO_GEO_RUNNER_LOG_LEVEL: process.env.AUTO_GEO_RUNNER_LOG_LEVEL || 'INFO',
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    })

    let stdout = ''
    let stderr = ''
    const timeoutMs = options.timeoutMs ?? DEFAULT_RUNNER_TIMEOUT_MS
    const timer = timeoutMs > 0
      ? setTimeout(() => {
          if (settled) return
          settled = true
          killProcessTree(child.pid)
          try {
            fs.rmSync(inputDir, { recursive: true, force: true })
          } catch {
            // ignore temp cleanup failures
          }
          resolve({
            success: false,
            error: `后端发布器执行超时 (${Math.round(timeoutMs / 1000)}s)`,
            error_msg: `后端发布器执行超时 (${Math.round(timeoutMs / 1000)}s)`,
          })
        }, timeoutMs)
      : undefined

    child.stdout?.on('data', (chunk) => {
      stdout += chunk.toString('utf-8')
    })
    child.stderr?.on('data', (chunk) => {
      const text = chunk.toString('utf-8')
      stderr += text
      for (const line of text.split(/\r?\n/).map((item: string) => item.trim()).filter(Boolean)) {
        if (line.startsWith(EVENT_PREFIX)) {
          try {
            options.onEvent?.(JSON.parse(line.slice(EVENT_PREFIX.length)))
          } catch (err: any) {
            console.warn(`[BackendPublisher:${platform}] 人工事件解析失败: ${err.message}`)
          }
          continue
        }
        console.log(`[BackendPublisher:${platform}] ${line}`)
      }
    })
    child.on('error', (err) => {
      if (settled) return
      settled = true
      if (timer) clearTimeout(timer)
      reject(err)
    })
    child.on('close', (code) => {
      if (settled) return
      settled = true
      if (timer) clearTimeout(timer)
      try {
        fs.rmSync(inputDir, { recursive: true, force: true })
      } catch {
        // ignore temp cleanup failures
      }

      if (code !== 0) {
        const errMsg = `后端发布器执行失败(code=${code}): ${stderr.trim() || stdout.trim()}`
        console.error(`[BackendPublisher:${platform}] ${errMsg}`)
        resolve({
          success: false,
          error: errMsg,
          error_msg: stderr.trim() || stdout.trim(),
        })
        return
      }

      try {
        const result = parseLastJsonLine(stdout)
        if (!result.success && stderr.trim() && !result.error_msg) {
          result.error_msg = stderr.trim()
          result.error = stderr.trim()
        }
        resolve(result)
      } catch (err) {
        reject(err)
      }
    })
  })
}
