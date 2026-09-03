/**
 * 窗口管理器
 * 我用这个来管理应用窗口！
 */

import { BrowserWindow, screen } from 'electron'
import { join } from 'path'
import { is } from '@electron-toolkit/utils'
// 我先注释掉图标，等有图标文件再说
// import icon from '../../../resources/icons/icon.png?asset'

// 窗口状态存储
let mainWindow: BrowserWindow | null = null

/**
 * 创建主窗口
 * 我设计了一个漂亮的暗色主题窗口！
 */
export function createMainWindow(): BrowserWindow {
  // 获取屏幕尺寸
  const { width, height } = screen.getPrimaryDisplay().workAreaSize

  // 创建浏览器窗口
  mainWindow = new BrowserWindow({
    width: Math.min(1400, width - 100),
    height: Math.min(900, height - 100),
    x: (width - Math.min(1400, width - 100)) / 2,
    y: (height - Math.min(900, height - 100)) / 2,
    show: false, // 我先用隐藏，等加载完再显示，避免白屏！
    autoHideMenuBar: true, // 自动隐藏菜单栏
    frame: true, // 显示原生窗口框架
    titleBarStyle: 'default', // 标题栏样式
    backgroundColor: '#1E1E1E', // 暗色背景
    // icon: icon, // 我先注释掉图标
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      sandbox: true, // 我开启沙箱模式，更安全！
      contextIsolation: true, // 必须开启！
      nodeIntegration: false, // 必须关闭！
      webSecurity: true, // 启用 Web 安全
    },
  })

  // 加载页面
  if (is.dev && process.env['ELECTRON_RENDERER_URL']) {
    // 开发模式：加载开发服务器
    mainWindow.loadURL(process.env['ELECTRON_RENDERER_URL'])
    mainWindow.webContents.openDevTools() // 打开开发者工具
  } else {
    // 生产模式：加载构建后的文件
    // __dirname 是 out/electron/main，需要向上两级到 out/，然后进入 renderer/
    mainWindow.loadFile(join(__dirname, '../../renderer/index.html'))
    // 临时调试：生产模式也打开 DevTools，排查白屏问题
    mainWindow.webContents.openDevTools()
  }

  // 窗口准备好后显示（避免白屏）
  mainWindow.once('ready-to-show', () => {
    mainWindow?.show()
  })

  // 加载失败处理 — 打印错误信息帮助排查白屏问题
  mainWindow.webContents.on('did-fail-load', (_event, errorCode, errorDescription, validatedURL) => {
    console.error(`[Window] 页面加载失败: code=${errorCode}, desc=${errorDescription}, url=${validatedURL}`)
  })

  // 渲染进程崩溃处理
  mainWindow.webContents.on('render-process-gone', (_event, details) => {
    console.error(`[Window] 渲染进程崩溃: reason=${details.reason}`)
  })

  // 控制台日志转发 — 将渲染进程的 console 输出到主进程终端
  mainWindow.webContents.on('console-message', (_event, level, message, line, sourceId) => {
    const levelStr = ['LOG', 'WARN', 'ERROR'][level] || 'LOG'
    console.log(`[Renderer ${levelStr}] ${message} (${sourceId}:${line})`)
  })

  // 窗口关闭事件
  mainWindow.on('closed', () => {
    mainWindow = null
  })

  // 防止外部链接在应用内打开
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    require('electron').shell.openExternal(url)
    return { action: 'deny' }
  })

  return mainWindow
}

/**
 * 获取主窗口实例
 */
export function getMainWindow(): BrowserWindow | null {
  return mainWindow
}

/**
 * 创建授权窗口（独立窗口用于账号授权）
 * 我用这个来打开浏览器让用户登录！
 */
export function createAuthWindow(platformId: string, authUrl: string): BrowserWindow {
  const authWindow = new BrowserWindow({
    width: 500,
    height: 700,
    show: true,
    autoHideMenuBar: true,
    resizable: true,
    backgroundColor: '#FFFFFF',
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
      // 授权窗口需要更宽松的安全策略
      webSecurity: false,
    },
  })

  // 加载授权页面
  authWindow.loadURL(authUrl)

  return authWindow
}

/**
 * 创建消息通知窗口
 */
export function showNotification(title: string, body: string): void {
  const { Notification } = require('electron')

  if (Notification.isSupported()) {
    new Notification({ title, body }).show() // 我先不显示图标
  }
}
