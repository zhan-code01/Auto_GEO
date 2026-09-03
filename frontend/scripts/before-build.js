/**
 * Electron 构建前脚本
 * 准备构建环境和资源
 */

const fs = require('fs')
const path = require('path')

console.log('🚀 Starting Electron build preparation...')

// 1. 检查必要的环境变量
const requiredEnvVars = []
const missingEnvVars = requiredEnvVars.filter(envVar => !process.env[envVar])

if (missingEnvVars.length > 0) {
  console.warn('⚠️  Warning: Missing environment variables:', missingEnvVars)
}

// 2. 创建构建目录
const buildDir = path.join(__dirname, '..', 'build')
if (!fs.existsSync(buildDir)) {
  fs.mkdirSync(buildDir, { recursive: true })
  console.log('✅ Created build directory')
}

// 3. 检查图标文件
const iconFiles = {
  windows: path.join(buildDir, 'icon.ico'),
  mac: path.join(buildDir, 'icon.icns'),
  linux: path.join(buildDir, 'icons'),
}

for (const [platform, iconPath] of Object.entries(iconFiles)) {
  if (fs.existsSync(iconPath)) {
    console.log(`✅ Found ${platform} icon`)
  } else {
    console.warn(`⚠️  Warning: ${platform} icon not found at ${iconPath}`)
  }
}

// 4. 检查后端目录
const backendDir = path.join(__dirname, '..', '..', 'backend')
if (fs.existsSync(backendDir)) {
  console.log('✅ Backend directory found')
} else {
  console.warn('⚠️  Warning: Backend directory not found')
}

// 5. 写入构建信息
const buildInfo = {
  version: require('../package.json').version,
  buildDate: new Date().toISOString(),
  platform: process.platform,
  arch: process.arch,
  nodeVersion: process.version,
}

fs.writeFileSync(
  path.join(buildDir, 'build-info.json'),
  JSON.stringify(buildInfo, null, 2)
)

console.log('✅ Build preparation completed!')
console.log('Build info:', buildInfo)
