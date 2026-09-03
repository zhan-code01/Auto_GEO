/**
 * 系统托盘管理器
 * 我用这个来管理系统托盘图标！
 */

import { Tray, Menu, nativeImage, app } from 'electron'
import { join } from 'path'
import { getMainWindow } from './window-manager'

let tray: Tray | null = null

/**
 * 创建系统托盘
 * 我设计了一个简洁的托盘菜单！
 */
export function createTray(mainWindow: any): void {
  // 开发环境使用默认图标，生产环境使用自定义图标
  const iconPath = join(__dirname, '../../resources/icons/tray-icon.png')

  // 创建托盘图标
  try {
    const icon = nativeImage.createFromPath(iconPath)
    tray = new Tray(icon)
  } catch {
    // 如果图标加载失败，使用默认图标
    tray = new Tray(nativeImage.createEmpty())
  }

  // 设置托盘提示
  tray.setToolTip('AutoGeo 智能发布助手')

  // 创建托盘菜单
  const contextMenu = Menu.buildFromTemplate([
    {
      label: '显示主窗口',
      click: () => {
        mainWindow?.show()
        mainWindow?.focus()
      },
    },
    {
      label: '隐藏主窗口',
      click: () => {
        mainWindow?.hide()
      },
    },
    { type: 'separator' },
    {
      label: '关于',
      click: () => {
        // TODO: 打开关于对话框
        mainWindow?.webContents.send('navigate-to', '/settings/about')
      },
    },
    { type: 'separator' },
    {
      label: '退出',
      click: () => {
        app.quit()
      },
    },
  ])

  tray.setContextMenu(contextMenu)

  // 双击托盘图标显示/隐藏窗口
  tray.on('double-click', () => {
    if (mainWindow?.isVisible()) {
      mainWindow.hide()
    } else {
      mainWindow?.show()
      mainWindow.focus()
    }
  })
}

/**
 * 销毁托盘
 */
export function destroyTray(): void {
  if (tray) {
    tray.destroy()
    tray = null
  }
}

/**
 * 更新托盘图标（闪烁效果等）
 */
export function updateTrayIcon(isActive: boolean): void {
  if (!tray) return

  // 提示：可以用不同图标表示不同状态
  // 例如：有发布任务进行中时显示蓝色图标
  // 这里简单实现，实际可以准备多个图标
}

export { tray }
