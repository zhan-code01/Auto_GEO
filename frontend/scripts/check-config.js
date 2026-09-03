#!/usr/bin/env node
/**
 * CI/CD 配置检查脚本
 * 检查 GitHub Secrets 和环境变量配置状态
 */

const fs = require('fs')
const path = require('path')

const requiredSecrets = [
  { name: 'ENCRYPTION_KEY', description: 'AES 加密密钥', required: true },
  { name: 'DEEPSEEK_API_KEY', description: 'DeepSeek AI 密钥', required: true },
]

const recommendedSecrets = [
  { name: 'SERVER_HOST', description: '服务器地址', required: false },
  { name: 'SERVER_USER', description: 'SSH 用户名', required: false },
  { name: 'SERVER_SSH_KEY', description: 'SSH 私钥', required: false },
  { name: 'API_URL', description: '后端 API 地址', required: false },
]

const optionalSecrets = [
  { name: 'WIN_CSC_LINK', description: 'Windows 代码签名证书', required: false },
  { name: 'CSC_LINK', description: 'macOS 代码签名证书', required: false },
  { name: 'APPLE_ID', description: '苹果开发者账号', required: false },
  { name: 'SLACK_WEBHOOK', description: 'Slack 通知 Webhook', required: false },
]

// 颜色
const colors = {
  reset: '\x1b[0m',
  red: '\x1b[31m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  blue: '\x1b[34m',
  cyan: '\x1b[36m',
}

function checkEnvFile() {
  const envExamplePath = path.join(__dirname, '../..', '.env.production.example')
  const envPath = path.join(__dirname, '../..', '.env')

  if (!fs.existsSync(envExamplePath)) {
    return null
  }

  const example = fs.readFileSync(envExamplePath, 'utf-8')
  const configured = fs.existsSync(envPath) ? fs.readFileSync(envPath, 'utf-8') : ''

  // 检查每个变量是否配置
  const variables = example.split('\n')
    .filter(line => line.includes('='))
    .map(line => line.split('=')[0])
    .filter(name => name && !name.startsWith('#'))

  return variables.filter(v => !configured.includes(`${v}=`) || configured.includes(`${v}=your-`))
}

function main() {
  console.log(`\n${colors.cyan}╔════════════════════════════════════════════════════════════╗${colors.reset}`)
  console.log(`${colors.cyan}║           AutoGeo CI/CD 配置检查工具                        ║${colors.reset}`)
  console.log(`${colors.cyan}╚════════════════════════════════════════════════════════════╝${colors.reset}\n`)

  // 检查必须配置的 Secrets
  console.log(`${colors.red}🔴 必须配置的 GitHub Secrets:${colors.reset}`)
  console.log(`   请在以下页面配置: https://github.com/Architecture-Matrix/auto_geo_dev/settings/secrets/actions\n`)

  requiredSecrets.forEach(secret => {
    console.log(`   ${colors.cyan}${secret.name}${colors.reset}`)
    console.log(`   描述: ${secret.description}`)
    console.log(`   配置方法: Settings → Secrets and variables → Actions → New repository secret\n`)
  })

  // 推荐配置
  console.log(`${colors.yellow}🟡 推荐配置的 GitHub Secrets:${colors.reset}\n`)

  recommendedSecrets.forEach(secret => {
    console.log(`   ${colors.cyan}${secret.name}${colors.reset}`)
    console.log(`   描述: ${secret.description}`)
    console.log(`   用于: 自动部署功能\n`)
  })

  // 可选配置
  console.log(`${colors.green}🟢 可选配置的 GitHub Secrets:${colors.reset}\n`)

  optionalSecrets.forEach(secret => {
    console.log(`   ${colors.cyan}${secret.name}${colors.reset}`)
    console.log(`   描述: ${secret.description}\n`)
  })

  // 本地环境文件检查
  const missing = checkEnvFile()
  if (missing && missing.length > 0) {
    console.log(`${colors.yellow}⚠️  本地 .env 文件缺少以下配置:${colors.reset}`)
    missing.forEach(v => console.log(`   - ${v}`))
    console.log(`\n   请复制 .env.production.example 到 .env 并填写实际值:\n`)
    console.log(`   ${colors.cyan}cp .env.production.example .env${colors.reset}\n`)
  }

  // 快速配置命令
  console.log(`${colors.cyan}═══════════════════════════════════════════════════════════${colors.reset}`)
  console.log(`${colors.cyan}快速配置命令:${colors.reset}\n`)

  console.log(`1. 生成加密密钥:`)
  console.log(`   ${colors.green}python -c "import secrets; print(secrets.token_urlsafe(32))"${colors.reset}\n`)

  console.log(`2. 生成 SSH 密钥 (用于自动部署):`)
  console.log(`   ${colors.green}ssh-keygen -t ed25519 -f ~/.ssh/auto_geo_deploy -N ""${colors.reset}\n`)

  console.log(`3. 打开 GitHub Secrets 配置页面:`)
  console.log(`   ${colors.green}https://github.com/Architecture-Matrix/auto_geo_dev/settings/secrets/actions${colors.reset}\n`)

  console.log(`${colors.cyan}═══════════════════════════════════════════════════════════${colors.reset}\n`)
}

main()
