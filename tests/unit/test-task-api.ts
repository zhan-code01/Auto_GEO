/**
 * AutoGeo 任务 API 客户端集成测试
 *
 * 通过模拟 global fetch 来测试 TaskApiClient 的各个方法，
 * 包括轮询、领取、上报、心跳、冲突处理、重试逻辑。
 *
 * 运行方式:
 *   npx tsx tests/unit/test-task-api.ts
 *   npx ts-node tests/unit/test-task-api.ts
 *
 * 编译为 CommonJS 模块（tsconfig "module": "CommonJS"）。
 *
 * 注意：此测试不依赖 Electron 运行时，纯 Node.js 即可运行。
 */

// ============================================================
//  简易测试运行器
// ============================================================

let passed = 0
let failed = 0
const pendingAssertions: Array<{ name: string; fn: () => Promise<void> }> = []

function assert(condition: boolean, message: string): void {
  if (condition) {
    passed++
    console.log(`  ✅ ${message}`)
  } else {
    failed++
    console.error(`  ❌ FAIL: ${message}`)
  }
}

async function describe(name: string, fn: () => void | Promise<void>): Promise<void> {
  console.log(`\n${name}`)
  await fn()
}

/** 注册异步断言，在所有同步测试完成后执行 */
function asyncTest(name: string, fn: () => Promise<void>): void {
  pendingAssertions.push({ name, fn })
}

// ============================================================
//  Mock fetch 工具
// ============================================================

let fetchMock: ((url: string | URL | Request, init?: RequestInit) => Promise<Response>) | null =
  null

function installFetchMock(): void {
  const originalFetch = globalThis.fetch
  globalThis.fetch = async (url: string | URL | Request, init?: any): Promise<Response> => {
    if (fetchMock) {
      return fetchMock(url, init as RequestInit)
    }
    return originalFetch(url as string, init)
  }
}

function uninstallFetchMock(): void {
  fetchMock = null
}

/** 创建模拟的 Response 对象（最小实现） */
function mockResponse(
  status: number,
  body: any,
  headers: Record<string, string> = {},
): Response {
  return {
    status,
    ok: status >= 200 && status < 300,
    statusText: status === 200 ? 'OK' : 'Error',
    headers: new Headers(headers),
    json: async () => body,
    text: async () => JSON.stringify(body),
    arrayBuffer: async () => new ArrayBuffer(0),
    blob: async () => new Blob(),
    formData: async () => new FormData(),
    clone: () => mockResponse(status, body, headers),
    body: null,
    bodyUsed: false,
    redirected: false,
    type: 'basic' as ResponseType,
    url: '',
  } as Response
}

// ============================================================
//  测试主体
// ============================================================

async function run(): Promise<void> {
  console.log('🧪 AutoGeo TaskApiClient Integration Tests')
  console.log('==========================================')

  installFetchMock()

  // ---- 同步测试（纯数据结构） ----
  testClientConstruction()

  // ---- 异步测试（依赖 mock fetch） ----
  await testPollTasks()
  await testClaimTask()
  await testClaimTaskConflict()
  await testReportResult()
  await testHeartbeat()
  await testMarkManualRequired()
  await testRetryOnNetworkError()
  await testRetryMaxExceeded()

  uninstallFetchMock()

  // ---- 结果汇总 ----
  console.log('\n==========================================')
  console.log(`  结果: ${passed} 通过 / ${failed} 失败`)
  if (failed === 0) {
    console.log('✅ 所有 TaskApiClient 测试通过')
  } else {
    console.error(`❌ ${failed} 个测试失败`)
    process.exit(1)
  }
}

// ============================================================
//  测试: 客户端构造
// ============================================================

function testClientConstruction(): void {
  describe('TaskApiClient 构造', async () => {
    const { TaskApiClient } = require('../../frontend/electron/main/task-api-client')

    // 正常构造
    const client = new TaskApiClient('http://localhost:8000', 'jwt-token-123', 'device-abc')
    assert(client !== undefined, '创建客户端实例成功')

    // 去掉尾部斜杠
    const client2 = new TaskApiClient('http://localhost:8000/', 'token', 'dev')
    // 通过内部 URL 拼接验证（调用 pollTasks 会用到 baseUrl，这里用反射检查）
    assert(
      (client2 as any).baseUrl === 'http://localhost:8000',
      '尾部斜杠被正确移除',
    )
  })
}

// ============================================================
//  测试: pollTasks - 正确解析响应
// ============================================================

async function testPollTasks(): Promise<void> {
  describe('TaskApiClient.pollTasks', async () => {
    const { TaskApiClient } = require('../../frontend/electron/main/task-api-client')

    // 正常返回：包装格式
    fetchMock = async () => {
      return mockResponse(200, {
        code: 0,
        message: 'ok',
        data: {
          items: [
            { id: 1, name: 'Task 1', status: 'pending' },
            { id: 2, name: 'Task 2', status: 'pending' },
          ],
        },
      })
    }

    const client = new TaskApiClient('http://localhost:8000', 'token', 'dev123')
    const tasks = await client.pollTasks()

    assert(tasks.length === 2, '返回 2 个任务')
    assert(tasks[0].id === 1, '第一个任务 id=1')
    assert(tasks[0].name === 'Task 1', '第一个任务 name=Task 1')
    assert(tasks[1].id === 2, '第二个任务 id=2')

    // 空列表
    fetchMock = async () => {
      return mockResponse(200, { code: 0, message: 'ok', data: { items: [] } })
    }
    const emptyTasks = await client.pollTasks()
    assert(emptyTasks.length === 0, '无任务时返回空数组 []')

    // data.items 缺失
    fetchMock = async () => {
      return mockResponse(200, { code: 0, message: 'ok', data: {} })
    }
    const noItems = await client.pollTasks()
    assert(noItems.length === 0, 'data.items 缺失 → 返回空数组')

    // 无包装格式
    fetchMock = async () => {
      return mockResponse(200, { items: [{ id: 99 }] })
    }
    const unwrapped = await client.pollTasks()
    assert(unwrapped.length === 1, '无包装返回 → 正确解析')
    assert(unwrapped[0].id === 99, '无包装格式 id 正确')

    // 按平台过滤
    let lastUrl = ''
    fetchMock = async (url: string | URL | Request) => {
      lastUrl = typeof url === 'string' ? url : url.toString()
      return mockResponse(200, { code: 0, message: 'ok', data: { items: [] } })
    }
    await (client as any).pollTasks('zhihu')
    assert(
      lastUrl.includes('platform=zhihu'),
      'pollTasks 传入 platform 参数时 URL 含 platform 查询参数',
    )
  })
}

// ============================================================
//  测试: claimTask - 成功领取
// ============================================================

async function testClaimTask(): Promise<void> {
  describe('TaskApiClient.claimTask 成功领取', async () => {
    const { TaskApiClient } = require('../../frontend/electron/main/task-api-client')

    let requestBody: any = null
    fetchMock = async (_url: string | URL | Request, init?: RequestInit) => {
      requestBody = JSON.parse(init?.body as string || '{}')
      return mockResponse(200, {
        code: 0,
        message: 'ok',
        data: {
          task: { id: 5, name: 'Test Task' },
          record_ids: [101, 102, 103],
          claim_expires_at: '2026-06-22T18:00:00Z',
        },
      })
    }

    const client = new TaskApiClient('http://localhost:8000', 'token', 'dev-xyz')
    const result = await client.claimTask(5)

    assert(result !== null, '成功领取 → 非 null')
    assert(result!.recordIds.length === 3, '3 条发布记录')
    assert(result!.recordIds[0] === 101, 'recordIds[0] = 101')
    assert(result!.claimExpiresAt === '2026-06-22T18:00:00Z', '过期时间正确')
    assert(requestBody.device_id === 'dev-xyz', '请求体含 device_id')
  })
}

// ============================================================
//  测试: claimTask - 409 冲突
// ============================================================

async function testClaimTaskConflict(): Promise<void> {
  describe('TaskApiClient.claimTask 409 冲突', async () => {
    const { TaskApiClient } = require('../../frontend/electron/main/task-api-client')

    fetchMock = async () => {
      return mockResponse(409, {
        code: 409,
        message: '任务已被其他设备领取',
      })
    }

    const client = new TaskApiClient('http://localhost:8000', 'token', 'dev-123')
    const result = await client.claimTask(5)

    assert(result === null, '409 冲突 → 返回 null')
  })
}

// ============================================================
//  测试: reportResult - 成功/失败
// ============================================================

async function testReportResult(): Promise<void> {
  describe('TaskApiClient.reportResult', async () => {
    const { TaskApiClient } = require('../../frontend/electron/main/task-api-client')

    // ---- 成功上报 ----
    let bodySuccess: any = null
    fetchMock = async (_url: string | URL | Request, init?: RequestInit) => {
      bodySuccess = JSON.parse(init?.body as string || '{}')
      return mockResponse(200, {
        code: 0,
        message: 'ok',
        data: { task: {}, settled: false },
      })
    }

    const client = new TaskApiClient('http://localhost:8000', 'token', 'dev-1')
    const result = await client.reportResult(1, 100, 'success', 'https://zhuanlan.zhihu.com/p/123')

    assert(result.settled === false, '单条上报 → settled=false（未完成全部）')
    assert(bodySuccess.status === 'success', '请求体 status=success')
    assert(bodySuccess.platform_url === 'https://zhuanlan.zhihu.com/p/123', '含 platform_url')
    assert(!bodySuccess.error_msg, '无 error_msg')

    // ---- 失败上报 ----
    let bodyFailed: any = null
    fetchMock = async (_url: string | URL | Request, init?: RequestInit) => {
      bodyFailed = JSON.parse(init?.body as string || '{}')
      return mockResponse(200, {
        code: 0,
        message: 'ok',
        data: { task: {}, settled: true },
      })
    }
    const failResult = await client.reportResult(
      1, 101, 'failed', undefined, '发布超时',
    )
    assert(failResult.settled === true, '失败上报仍可触发 settled=true')
    assert(bodyFailed.status === 'failed', '请求体 status=failed')
    assert(bodyFailed.error_msg === '发布超时', '含 error_msg')
    assert(!bodyFailed.platform_url, '失败上报无 platform_url')

    // ---- 全部完成 ----
    fetchMock = async () => {
      return mockResponse(200, {
        code: 0,
        message: 'ok',
        data: { task: {}, settled: true },
      })
    }
    const doneResult = await client.reportResult(1, 102, 'success', 'http://example.com/post')
    assert(doneResult.settled === true, '最后一条 → settled=true')

    // ---- data.settled 缺失时的兜底 ----
    fetchMock = async () => {
      return mockResponse(200, { code: 0, message: 'ok', data: { task: {} } })
    }
    const noSettled = await client.reportResult(1, 103, 'success')
    assert(noSettled.settled === false, 'data.settled 缺失 → 默认为 false')
  })
}

// ============================================================
//  测试: heartbeat 心跳
// ============================================================

async function testHeartbeat(): Promise<void> {
  describe('TaskApiClient.heartbeat', async () => {
    const { TaskApiClient } = require('../../frontend/electron/main/task-api-client')

    let lastUrl = ''
    let lastBody: any = null
    fetchMock = async (url: string | URL | Request, init?: RequestInit) => {
      lastUrl = typeof url === 'string' ? url : url.toString()
      lastBody = JSON.parse(init?.body as string || '{}')
      return mockResponse(200, { code: 0, message: 'ok' })
    }

    const client = new TaskApiClient('http://localhost:8000', 'token', 'dev-heart')
    await client.heartbeat(42)

    assert(
      lastUrl.includes('/publish/tasks/42/heartbeat'),
      'URL 包含 /publish/tasks/42/heartbeat',
    )
    assert(lastBody.device_id === 'dev-heart', '请求体含 device_id')
  })
}

// ============================================================
//  测试: markManualRequired
// ============================================================

async function testMarkManualRequired(): Promise<void> {
  describe('TaskApiClient.markManualRequired', async () => {
    const { TaskApiClient } = require('../../frontend/electron/main/task-api-client')

    let lastUrl = ''
    let lastBody: any = null
    fetchMock = async (url: string | URL | Request, init?: RequestInit) => {
      lastUrl = typeof url === 'string' ? url : url.toString()
      lastBody = JSON.parse(init?.body as string || '{}')
      return mockResponse(200, { code: 0, message: 'ok' })
    }

    const client = new TaskApiClient('http://localhost:8000', 'token', 'dev-manual')
    await client.markManualRequired(7, '需要滑块验证码')

    assert(
      lastUrl.includes('/publish/tasks/7/manual-required'),
      'URL 含 manual-required 端点',
    )
    assert(lastBody.message === '需要滑块验证码', '消息正确传递')
    assert(lastBody.device_id === 'dev-manual', 'device_id 正确')
  })
}

// ============================================================
//  测试: 网络错误重试
// ============================================================

async function testRetryOnNetworkError(): Promise<void> {
  describe('TaskApiClient 网络错误自动重试', async () => {
    const { TaskApiClient } = require('../../frontend/electron/main/task-api-client')

    let callCount = 0
    fetchMock = async () => {
      callCount++
      if (callCount < 3) {
        // 前两次模拟网络错误（TypeError）
        throw new TypeError('fetch failed')
      }
      // 第三次成功
      return mockResponse(200, {
        code: 0,
        message: 'ok',
        data: { items: [{ id: 'retried' }] },
      })
    }

    const client = new TaskApiClient('http://localhost:8000', 'token', 'dev-retry')
    const tasks = await client.pollTasks()

    assert(callCount === 3, '网络错误重试 3 次后成功')
    assert(tasks.length === 1, '重试成功后拿到数据')
    assert(tasks[0].id === 'retried', '重试后数据正确')
  })
}

// ============================================================
//  测试: 超过最大重试次数
// ============================================================

async function testRetryMaxExceeded(): Promise<void> {
  describe('TaskApiClient 超过最大重试次数', async () => {
    const { TaskApiClient } = require('../../frontend/electron/main/task-api-client')

    let callCount = 0
    fetchMock = async () => {
      callCount++
      throw new TypeError('fetch failed')
    }

    const client = new TaskApiClient('http://localhost:8000', 'token', 'dev-max')
    let errorCaught = false
    try {
      await client.pollTasks()
    } catch (err: any) {
      errorCaught = true
      assert(
        err.message.includes('已达最大重试次数'),
        `错误消息含"已达最大重试次数": ${err.message}`,
      )
    }

    assert(errorCaught === true, '超过重试次数后抛出异常')
    assert(callCount === 3, '恰好重试了 3 次（默认 maxRetries=3）')
  })
}

// ============================================================
//  执行
// ============================================================

run().catch((err) => {
  console.error('测试运行异常:', err)
  process.exit(1)
})
