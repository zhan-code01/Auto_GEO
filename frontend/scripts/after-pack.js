/**
 * Electron 打包后脚本
 * 处理打包后的文件
 */

const fs = require('fs')
const path = require('path')

console.log('📦 Processing packaged Electron app...')

/**
 * 检查打包后的后端文件
 */
function checkBackendFiles(appOutDir) {
  const backendDir = path.join(appOutDir, 'resources', 'backend')

  if (!fs.existsSync(backendDir)) {
    console.warn('⚠️  Warning: Backend directory not found in packaged app')
    return
  }

  // 检查关键文件
  const requiredFiles = [
    'main.py',
    'requirements.txt',
    'database/models.py',
  ]

  for (const file of requiredFiles) {
    const filePath = path.join(backendDir, file)
    if (fs.existsSync(filePath)) {
      console.log(`✅ Found: ${file}`)
    } else {
      console.warn(`⚠️  Missing: ${file}`)
    }
  }

  console.log('🧹 Cleaning up unnecessary files...')
}

/**
 * 创建启动脚本
 */
function createLaunchScripts(appOutDir, platform) {
  const scriptsDir = path.join(appOutDir, 'scripts')

  if (!fs.existsSync(scriptsDir)) {
    fs.mkdirSync(scriptsDir, { recursive: true })
  }

  if (platform === 'win32') {
    // Windows 启动脚本
    const batScript = `@echo off
cd /d "%~dp0"
start "" "AutoGeo.exe"
`
    fs.writeFileSync(path.join(scriptsDir, 'launch.bat'), batScript)
  } else if (platform === 'darwin') {
    // macOS 启动脚本
    const shScript = `#!/bin/bash
cd "$(dirname "$0")"
open AutoGeo.app
`
    fs.writeFileSync(path.join(scriptsDir, 'launch.sh'), shScript)
    fs.chmodSync(path.join(scriptsDir, 'launch.sh'), '755')
  } else {
    // Linux 启动脚本
    const shScript = `#!/bin/bash
cd "$(dirname "$0")"
./AutoGeo
`
    fs.writeFileSync(path.join(scriptsDir, 'launch.sh'), shScript)
    fs.chmodSync(path.join(scriptsDir, 'launch.sh'), '755')
  }
}

/**
 * 主函数
 */
exports.default = async function(context) {
  const { appOutDir, electronPlatformName } = context

  console.log(`Platform: ${electronPlatformName}`)
  console.log(`Output directory: ${appOutDir}`)

  // 检查后端文件
  checkBackendFiles(appOutDir)

  // 创建启动脚本
  createLaunchScripts(appOutDir, electronPlatformName)

  console.log('✅ Post-pack processing completed!')
}
