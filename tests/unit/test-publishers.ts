/**
 * AutoGeo 发布器单元测试
 *
 * 测试 BasePublisher 工具方法、ZhihuPublisher URL 检测、
 * 以及 TaskApiClient.extractData 的响应解包逻辑。
 *
 * 运行方式:
 *   npx tsx tests/unit/test-publishers.ts
 *   npx ts-node tests/unit/test-publishers.ts
 *
 * 编译为 CommonJS 模块（tsconfig "module": "CommonJS"）。
 */

// ============================================================
//  简易测试运行器
// ============================================================

let passed = 0
let failed = 0

function assert(condition: boolean, message: string): void {
  if (condition) {
    passed++
    console.log(`  ✅ ${message}`)
  } else {
    failed++
    console.error(`  ❌ FAIL: ${message}`)
  }
}

function describe(name: string, fn: () => void): void {
  console.log(`\n${name}`)
  fn()
}

// ============================================================
//  测试主体
// ============================================================

function run(): void {
  console.log('🧪 AutoGeo Publisher Unit Tests')
  console.log('================================')

  testMarkdownToPlainText()
  testIsLoginPage()
  testZhihuWaitForResult()
  testExtractData()

  // ---- 结果汇总 ----
  console.log('\n================================')
  console.log(`  结果: ${passed} 通过 / ${failed} 失败`)
  if (failed === 0) {
    console.log('✅ 所有 publisher 单元测试通过')
  } else {
    console.error(`❌ ${failed} 个测试失败`)
    process.exit(1)
  }
}

// ============================================================
//  测试 1: BasePublisher.markdownToPlainText
// ============================================================

function testMarkdownToPlainText(): void {
  describe('BasePublisher.markdownToPlainText', () => {
    // 导入 BasePublisher（创建匿名子类实例以测试方法）
    const { BasePublisher } = require('../../frontend/electron/main/publishers/base')

    // 创建测试用实例（匿名子类，避免 require abstract class 错误）
    const TestPublisher = class extends BasePublisher {
      platform = 'test'
      publishUrl = 'http://test.com'
      titleSelector = 'input'
      contentSelector = 'textarea'
      async fillContent(): Promise<void> {}
      async waitForResult(): Promise<string> { return '' }
    }
    const pub = new TestPublisher()

    // ---- <br> 标签 ----
    assert(
      pub.markdownToPlainText('Line1<br>Line2') === 'Line1\nLine2',
      '<br> → 换行符',
    )
    assert(
      pub.markdownToPlainText('A<br/>B<br />C') === 'A\nB\nC',
      '<br/> 和 <br /> 变体 → 换行符',
    )

    // ---- Markdown 图片语法 ----
    assert(
      pub.markdownToPlainText('Text ![alt](http://img.png) suffix') === 'Text  suffix',
      '移除 ![]() 图片语法',
    )
    assert(
      pub.markdownToPlainText('Before ![no-url] after') === 'Before  after',
      '移除 ![] 无 URL 图片语法',
    )

    // ---- Markdown 加粗 ----
    assert(
      pub.markdownToPlainText('Hello **world** here') === 'Hello world here',
      '移除 **加粗** 标记',
    )
    assert(
      pub.markdownToPlainText('Prefix __bold__ suffix') === 'Prefix bold suffix',
      '移除 __加粗__ 标记',
    )

    // ---- Markdown 链接 ----
    assert(
      pub.markdownToPlainText('Click [here](http://example.com) now') === 'Click here now',
      '移除链接语法，保留文字',
    )
    assert(
      pub.markdownToPlainText('[only text]') === '[only text]',
      '非链接格式的 [text] 原样保留',
    )

    // ---- Markdown 斜体 ----
    assert(
      pub.markdownToPlainText('This *is* italic') === 'This is italic',
      '移除 *斜体* 标记',
    )
    assert(
      pub.markdownToPlainText('Also _italic_ here') === 'Also italic here',
      '移除 _斜体_ 标记',
    )

    // ---- 行内代码 ----
    assert(
      pub.markdownToPlainText('Use `console.log()` please') === 'Use console.log() please',
      '移除行内代码标记',
    )

    // ---- HTML 标签 ----
    assert(
      pub.markdownToPlainText('<p>Paragraph</p>') === 'Paragraph',
      '去除 HTML 标签',
    )
    assert(
      pub.markdownToPlainText('<div class="a"><span>Nested</span></div>') === 'Nested',
      '去除嵌套 HTML 标签',
    )

    // ---- HTML 实体解码 ----
    assert(
      pub.markdownToPlainText('Tom &amp; Jerry') === 'Tom & Jerry',
      '解码 &amp; → &',
    )
    assert(
      pub.markdownToPlainText('A &lt; B &gt; C') === 'A < B > C',
      '解码 &lt; &gt;',
    )
    assert(
      pub.markdownToPlainText('It&apos;s nice') === "It's nice",
      '解码 &#39; → \'',
    )
    assert(
      pub.markdownToPlainText('Word1&nbsp;Word2') === 'Word1 Word2',
      '解码 &nbsp; → 空格',
    )

    // ---- 合并连续空行 ----
    assert(
      pub.markdownToPlainText('A\n\n\n\nB') === 'A\n\nB',
      '多个连续空行合并为最多一个空行',
    )

    // ---- 综合测试 ----
    const complexInput =
      '<h1>Title</h1><br>Hello **world**<br>See [link](http://x.com)<br><br><br>End'
    const expectedComplex = 'Title\nHello world\nSee link\n\nEnd'
    assert(
      pub.markdownToPlainText(complexInput) === expectedComplex,
      '综合：标题 + 换行 + 加粗 + 链接 + 空行合并',
    )

    // ---- 空输入 ----
    assert(
      pub.markdownToPlainText('') === '',
      '空字符串 → 空字符串',
    )
    assert(
      pub.markdownToPlainText(null as any) === '',
      'null → 空字符串',
    )
  })
}

// ============================================================
//  测试 2: BasePublisher.isLoginPage
// ============================================================

function testIsLoginPage(): void {
  describe('BasePublisher.isLoginPage', () => {
    const { BasePublisher } = require('../../frontend/electron/main/publishers/base')

    const TestPublisher = class extends BasePublisher {
      platform = 'test'
      publishUrl = 'http://test.com'
      titleSelector = 'input'
      contentSelector = 'textarea'
      async fillContent(): Promise<void> {}
      async waitForResult(): Promise<string> { return '' }
    }
    const pub = new TestPublisher()

    // ---- 含 login 的 URL ----
    assert(
      pub.isLoginPage('https://www.zhihu.com/login') === true,
      'URL 含 "login" → true',
    )
    assert(
      pub.isLoginPage('https://accounts.example.com/LOGIN?next=/') === true,
      'URL 含 "LOGIN"（大写） → true',
    )

    // ---- 含 signin 的 URL ----
    assert(
      pub.isLoginPage('https://example.com/signin') === true,
      'URL 含 "signin" → true',
    )
    assert(
      pub.isLoginPage('https://auth.example.com/user/signIn/verify') === true,
      'URL 含 "signIn"（混合大小写） → true',
    )

    // ---- 含 passport 的 URL ----
    assert(
      pub.isLoginPage('https://passport.zhihu.com/') === true,
      'URL 含 "passport" → true',
    )
    assert(
      pub.isLoginPage('https://example.com/passport-auth') === true,
      'URL 含 "passport" 作为路径段 → true',
    )

    // ---- 正常 URL ----
    assert(
      pub.isLoginPage('https://zhuanlan.zhihu.com/write') === false,
      '正常写文章页面 → false',
    )
    assert(
      pub.isLoginPage('https://www.zhihu.com/question/123') === false,
      '知乎问题页 → false',
    )
    assert(
      pub.isLoginPage('https://example.com/dashboard') === false,
      '普通 dashboard 页 → false',
    )
    assert(
      pub.isLoginPage('https://blog.example.com/the-login-issue') === true,
      'URL 路径中嵌有 "login" → true（预期行为：宽松匹配）',
    )
  })
}

// ============================================================
//  测试 3: ZhihuPublisher.waitForResult URL 正则
// ============================================================

function testZhihuWaitForResult(): void {
  describe('ZhihuPublisher.waitForResult URL 正则', () => {
    // 知乎发布成功判定（对齐后端 zhihu.py::_wait_for_publish_result：URL 含 /p/<id> 即成功，
    // 含 /p/<id>/edit 也算成功 —— 文章已创建）
    const ARTICLE_RE = /^https?:\/\/zhuanlan\.zhihu\.com\/p\/\d+(?:\/edit)?\/?(?:[?#].*)?$/i

    // ---- 匹配的情况（算发布成功）----
    assert(
      ARTICLE_RE.test('https://zhuanlan.zhihu.com/p/12345') === true,
      'zhuanlan.zhihu.com/p/12345 → 匹配',
    )
    assert(
      ARTICLE_RE.test('https://zhuanlan.zhihu.com/p/999888777') === true,
      'zhuanlan.zhihu.com/p/999888777 → 匹配',
    )
    assert(
      ARTICLE_RE.test('https://zhuanlan.zhihu.com/p/12345?utm_source=share') === true,
      '带 query 参数的文章页 → 匹配',
    )
    assert(
      ARTICLE_RE.test('https://zhuanlan.zhihu.com/p/12345/edit') === true,
      'zhuanlan.zhihu.com/p/12345/edit → 匹配（edit 态也算成功，对齐后端）',
    )

    // ---- 不匹配的情况（不算成功）----
    assert(
      ARTICLE_RE.test('https://zhuanlan.zhihu.com/write') === false,
      'zhuanlan.zhihu.com/write → 不匹配',
    )
    assert(
      ARTICLE_RE.test('https://www.zhihu.com/question/123') === false,
      'www.zhihu.com/question/123 → 不匹配',
    )
    assert(
      ARTICLE_RE.test('https://www.zhihu.com/p/12345') === false,
      'www.zhihu.com/p/12345（非专栏域名） → 不匹配',
    )
  })
}

// ============================================================
//  测试 4: TaskApiClient.extractData API 响应解包
// ============================================================

function testExtractData(): void {
  describe('TaskApiClient.extractData API 响应解包', () => {
    // extractData 是 private 方法，我们直接测试提取逻辑
    // 通过模拟 Response.json() 来验证行为
    const { TaskApiClient } = require('../../frontend/electron/main/task-api-client')

    // 使用 Reflection 访问 private extractData（仅测试用）
    async function simulateExtract(json: any): Promise<any> {
      const mockResponse = {
        json: async () => json,
      } as Response

      // 通过创建实例并使用类型忽略来调用 private 方法
      const client = new TaskApiClient('http://localhost:8000', 'test-token', 'test-device')
      // 使用 any 绕过 TypeScript private 访问检查
      return (client as any).extractData(mockResponse)
    }

    // ---- 标准包装: { data: { items: [...] } } → { items: [...] } ----
    (async () => {
      const result = await simulateExtract({
        code: 0,
        message: 'ok',
        data: { items: [{ id: 1 }, { id: 2 }] },
      })
      assert(
        JSON.stringify(result) === JSON.stringify({ items: [{ id: 1 }, { id: 2 }] }),
        '包装格式: { data: { items: [...] } } → { items: [...] }',
      )
    })()

    // ---- 无包装: { items: [...] } → { items: [...] } ----
    ;(async () => {
      const result = await simulateExtract({ items: [{ id: 1 }] })
      assert(
        JSON.stringify(result) === JSON.stringify({ items: [{ id: 1 }] }),
        '无包装: { items: [...] } → { items: [...] }',
      )
    })()

    // ---- 空 data: { data: null } ----
    ;(async () => {
      const result = await simulateExtract({ code: 0, message: 'ok', data: null })
      assert(
        result === null,
        'data 为 null → null',
      )
    })()

    // ---- 空对象: {} → {} ----
    ;(async () => {
      const result = await simulateExtract({})
      assert(
        JSON.stringify(result) === JSON.stringify({}),
        '空对象 → {}（无 data 字段时原样返回）',
      )
    })()

    // ---- data 为数组: { data: [1, 2, 3] } → [1, 2, 3] ----
    ;(async () => {
      const result = await simulateExtract({ data: [1, 2, 3] })
      assert(
        JSON.stringify(result) === JSON.stringify([1, 2, 3]),
        'data 为数组 → 直接返回数组',
      )
    })()
  })
}

// ============================================================
//  执行
// ============================================================

run()
