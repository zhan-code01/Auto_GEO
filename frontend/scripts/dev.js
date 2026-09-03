/**
 * 开发启动脚本
 * 我用这个来同时启动 Vite 和 Electron！
 *
 * 修复说明：
 * - 自动编译 electron 主进程代码后再启动
 * - 这样就不需要手动运行 npm run build 了
 */

const { spawn, execSync } = require('child_process')
const path = require('path')

// 获取项目根目录
const rootDir = path.join(__dirname, '..')

// 设置环境变量
process.env.ELECTRON_RENDERER_URL = 'http://localhost:5173'

// 修复 Windows 控制台中文乱码：切换到 UTF-8 编码
try {
  execSync('chcp 65001 > nul', { stdio: 'ignore' })
} catch {
  // chcp 命令不存在时忽略
}

// 设置 Python 输出编码为 UTF-8
process.env.PYTHONIOENCODING = 'utf-8'
process.env.PYTHONUTF8 = '1'

let viteProcess = null
let electronProcess = null

// 清理函数
function cleanup() {
  console.log('\n🛑 正在清理进程...')
  if (viteProcess) {
    viteProcess.kill('SIGTERM')
    viteProcess = null
  }
  if (electronProcess) {
    electronProcess.kill('SIGTERM')
    electronProcess = null
  }
  setTimeout(() => process.exit(0), 500)
}

// 退出时清理
process.on('SIGINT', cleanup)
process.on('SIGTERM', cleanup)
process.on('exit', cleanup)

// 编译 electron 主进程代码
function buildElectron() {
  console.log('🔨 正在编译 Electron 主进程代码...')
  try {
    execSync('npm run --silent build:electron', {
      cwd: rootDir,
      stdio: 'inherit'
    })
    console.log('✅ Electron 主进程编译完成\n')
  } catch (err) {
    console.error('❌ Electron 主进程编译失败:', err.message)
    process.exit(1)
  }
}

// 先编译 electron 主进程
buildElectron()

// 启动 Vite 开发服务器
console.log('🚀 正在启动 Vite 开发服务器...')

// 使用 npm run 来启动，跨平台最可靠
// 注意：把命令与参数合并为单个字符串传给 spawn，
// 避免 shell:true + 数组参数 触发 Node 的 DEP0190 弃用警告（安全风险提示）。
viteProcess = spawn('npm run --silent vite:dev', {
  shell: true,
  stdio: 'inherit',
  cwd: rootDir,
  env: process.env
})

viteProcess.on('error', (err) => {
  console.error('❌ Vite 启动失败:', err.message)
  process.exit(1)
})

// Vite 启动后再启动 Electron
setTimeout(() => {
  console.log('⚡ 正在启动 Electron...')

  electronProcess = spawn('npm run --silent electron:dev', {
    shell: true,
    stdio: 'inherit',
    cwd: rootDir,
    env: { ...process.env, ELECTRON_RENDERER_URL: 'http://localhost:5173' }
  })

  electronProcess.on('error', (err) => {
    console.error('❌ Electron 启动失败:', err.message)
    if (viteProcess) viteProcess.kill()
    process.exit(1)
  })

  electronProcess.on('close', (code) => {
    console.log(`\nElectron 退出，代码: ${code}`)
    cleanup()
  })
}, 3000)

viteProcess.on('close', (code) => {
  console.log(`\nVite 退出，代码: ${code}`)
  cleanup()
})
