<template>
  <div class="settings-page">
    <h2>设置</h2>
    <div class="settings-sections">
      <div class="setting-section">
        <h3>服务连接状态</h3>
        <div class="setting-item">
          <div class="setting-info">
            <span>健康检查</span>
            <span class="setting-desc">测试后端与各服务的连接状态</span>
          </div>
          <el-button type="primary" @click="refreshHealth" :loading="healthLoading">
            {{ healthLoading ? '检测中...' : '刷新状态' }}
          </el-button>
        </div>

        <template v-if="healthError">
          <div class="setting-item">
            <div class="setting-info">
              <span>后端服务</span>
              <span class="setting-desc">健康检测失败</span>
            </div>
            <div class="setting-value">
              <span class="status-badge error">检测失败</span>
            </div>
          </div>
          <div class="setting-item">
            <div class="setting-info">
              <span>失败原因</span>
              <span class="setting-desc error-reason">{{ healthError }}</span>
            </div>
          </div>
        </template>

        <template v-else-if="healthStatus">
          <div class="setting-item">
            <div class="setting-info">
              <span>整体状态</span>
              <span class="setting-desc">后端服务运行状态</span>
            </div>
            <div class="setting-value">
              <span class="status-badge" :class="{ active: healthStatus.status === 'ok', error: healthStatus.status === 'degraded' || healthStatus.status === 'error' }">
                {{ healthStatus.status === 'ok' ? '正常' : healthStatus.status === 'degraded' ? '部分异常' : '异常' }}
              </span>
            </div>
          </div>

          <div class="setting-item">
            <div class="setting-info">
              <span>数据库</span>
              <span class="setting-desc">PostgreSQL 连接状态</span>
            </div>
            <div class="setting-value">
              <span class="status-badge" :class="getServiceStatusClass(healthStatus.services.database.status)">
                {{ getServiceStatusText(healthStatus.services.database.status) }}
              </span>
            </div>
          </div>

          <div class="setting-item">
            <div class="setting-info">
              <span>RAGFlow</span>
              <span class="setting-desc">知识库检索服务</span>
            </div>
            <div class="setting-value">
              <span class="status-badge" :class="getServiceStatusClass(healthStatus.services.ragflow.status)">
                {{ getServiceStatusText(healthStatus.services.ragflow.status) }}
              </span>
            </div>
          </div>
        </template>

        <template v-else>
          <div class="setting-item">
            <div class="setting-info">
              <span>后端服务</span>
              <span class="setting-desc">点击刷新获取服务状态</span>
            </div>
            <div class="setting-value">
              <span class="status-badge">{{ healthLoading ? '检测中...' : '未检测' }}</span>
            </div>
          </div>
        </template>
      </div>

      <div class="setting-section">
        <h3>定时任务</h3>
        <div class="setting-item">
          <div class="setting-info">
            <span>定时任务服务状态</span>
            <span class="setting-desc">控制自动化任务的运行状态</span>
          </div>
          <div class="setting-value">
            <span class="status-badge" :class="{ active: schedulerRunning }">
              {{ schedulerRunning ? '运行中' : '已停止' }}
            </span>
          </div>
        </div>
        <div class="setting-item">
          <div class="setting-info">
            <span>快速配置</span>
            <span class="setting-desc">跳转到定时任务配置页面</span>
          </div>
          <el-button type="primary" link @click="goToScheduler">
            前往配置
            <svg viewBox="0 0 16 16" fill="currentColor" width="12">
              <path d="M4 8a.5.5 0 01.5-.5h5.793L4.146 3.354a.5.5 0 11.708-.708l7 7a.5.5 0 010 .708l-7 7a.5.5 0 01-.708-.708L10.293 8.5H4.5A.5.5 0 014 8z"/>
            </svg>
          </el-button>
        </div>
      </div>

      <div class="setting-section">
        <h3>知识库管理</h3>
        <div class="setting-item">
          <div class="setting-info">
            <span>企业知识库</span>
            <span class="setting-desc">管理不同企业的知识库内容</span>
          </div>
          <el-button type="primary" link @click="goToKnowledge">
            前往管理
            <svg viewBox="0 0 16 16" fill="currentColor" width="12">
              <path d="M4 8a.5.5 0 01.5-.5h5.793L4.146 3.354a.5.5 0 11.708-.708l7 7a.5.5 0 010 .708l-7 7a.5.5 0 01-.708-.708L10.293 8.5H4.5A.5.5 0 014 8z"/>
            </svg>
          </el-button>
        </div>
      </div>

      <div class="setting-section">
        <h3>应用设置</h3>
        <div class="setting-item">
          <div class="setting-info">
            <span>暗色主题</span>
            <span class="setting-desc">切换应用的外观主题</span>
          </div>
          <el-switch v-model="darkTheme" />
        </div>
        <div class="setting-item">
          <div class="setting-info">
            <span>启动时最小化到托盘</span>
            <span class="setting-desc">应用启动后最小化到系统托盘</span>
          </div>
          <el-switch v-model="minimizeToTray" />
        </div>
        <div class="setting-item">
          <div class="setting-info">
            <span>发布完成通知</span>
            <span class="setting-desc">文章发布完成后发送通知</span>
          </div>
          <el-switch v-model="publishNotification" />
        </div>
      </div>

      <div class="setting-section">
        <h3>本地浏览器桥接服务</h3>
        <div class="setting-item">
          <div class="setting-info">
            <span>服务状态</span>
            <span class="setting-desc">本地浏览器桥接服务运行状态</span>
          </div>
          <div class="setting-value">
            <span class="status-badge" :class="bridgeStatusClass">
              {{ bridgeStatusText }}
            </span>
          </div>
        </div>
        <div class="setting-item" v-if="bridgeConfig">
          <div class="setting-info">
            <span>CDP端口</span>
            <span class="setting-desc">Chrome DevTools Protocol 端口</span>
          </div>
          <div class="setting-value">
            <span class="port-badge">{{ bridgeConfig.cdpPort }}</span>
          </div>
        </div>
        <div class="setting-item">
          <div class="setting-info">
            <span>重启服务</span>
            <span class="setting-desc">重启浏览器桥接服务</span>
          </div>
          <el-button type="primary" link @click="restartBridge" :loading="bridgeRestarting">
            重新启动
            <svg viewBox="0 0 16 16" fill="currentColor" width="12">
              <path d="M4 8a.5.5 0 01.5-.5h5.793L4.146 3.354a.5.5 0 11.708-.708l7 7a.5.5 0 010 .708l-7 7a.5.5 0 01-.708-.708L10.293 8.5H4.5A.5.5 0 014 8z"/>
            </svg>
          </el-button>
        </div>
        <div class="setting-item">
          <div class="setting-info">
            <span>服务说明</span>
            <span class="setting-desc">用于本地授权和文章发布，启动时自动运行</span>
          </div>
        </div>
      </div>

      <div class="setting-section">
        <h3>关于</h3>
        <div class="about-info">
          <div class="about-header">
            <div class="about-logo">
              <span class="about-logo-icon">G</span>
            </div>
            <div class="about-title">
              <strong>AutoGeo</strong>
              <span class="about-version">v2.0.0</span>
            </div>
          </div>
          <p>AI搜索引擎优化自动化平台</p>
          <p class="about-desc">用心打造的自动化工具，让GEO更简单</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { systemApi, type HealthStatus } from '@/services/api'

const router = useRouter()
const darkTheme = ref(true)
const minimizeToTray = ref(false)
const publishNotification = ref(true)
const schedulerRunning = ref(true)

// 健康检查状态
const healthStatus = ref<HealthStatus | null>(null)
const healthLoading = ref(false)
// 健康检查失败原因（用于页面内红字提示，而不是只剩「未检测」）
const healthError = ref<string | null>(null)

// 健康检测参数：单次超时与重试策略
const HEALTH_TIMEOUT = 10000 // 单次请求超时（毫秒）
const HEALTH_MAX_RETRIES = 2 // 失败后最多重试次数
const HEALTH_RETRY_DELAY = 1500 // 重试间隔（毫秒）

// 浏览器桥接服务状态
const bridgeStatus = ref<'stopped' | 'starting' | 'running' | 'error'>('stopped')
const bridgeConfig = ref<any>(null)
const bridgeRestarting = ref(false)
let statusCheckInterval: number | null = null

// 服务状态文本映射
const getServiceStatusText = (status: string) => {
  const map: Record<string, string> = {
    connected: '已连接',
    error: '连接失败',
    not_configured: '未配置',
    unknown: '未知'
  }
  return map[status] || status
}

// 服务状态样式类
const getServiceStatusClass = (status: string) => {
  return {
    active: status === 'connected',
    error: status === 'error',
    warning: status === 'not_configured'
  }
}

// 获取健康状态（带超时 + 失败自动重试 + 错误兜底）
const fetchHealthStatus = async () => {
  healthError.value = null
  healthLoading.value = true
  let attempt = 0
  while (true) {
    try {
      // 单独控制超时；silent:true 避免全局错误 toast，错误在页面内展示
      const status = await systemApi.getHealth({ timeout: HEALTH_TIMEOUT, silent: true })
      healthStatus.value = status
      healthLoading.value = false
      return
    } catch (error: any) {
      console.error('[Settings] 获取健康状态失败:', error)
      if (attempt < HEALTH_MAX_RETRIES) {
        attempt++
        await new Promise((resolve) => setTimeout(resolve, HEALTH_RETRY_DELAY))
        continue
      }
      // 重试耗尽，提取可读的错误原因
      const raw =
        error?.response?.data?.detail ||
        error?.response?.data?.message ||
        error?.message ||
        '未知错误'
      healthStatus.value = null
      healthError.value = typeof raw === 'string' ? raw : '检测失败'
      healthLoading.value = false
      return
    }
  }
}

// 刷新健康状态
const refreshHealth = () => {
  fetchHealthStatus()
}

// 状态文本映射
const bridgeStatusText = computed(() => {
  const statusMap = {
    stopped: '已停止',
    starting: '启动中',
    running: '运行中',
    error: '错误'
  }
  return statusMap[bridgeStatus.value] || '未知'
})

// 状态样式类
const bridgeStatusClass = computed(() => {
  return {
    active: bridgeStatus.value === 'running',
    error: bridgeStatus.value === 'error',
    starting: bridgeStatus.value === 'starting'
  }
})

// 获取桥接服务状态
const fetchBridgeStatus = async () => {
  try {
    if (!window.electronAPI) {
      console.log('[Settings] 非 Electron 环境，跳过桥接服务状态获取')
      return
    }
    const status = await window.electronAPI.getBridgeStatus()
    bridgeStatus.value = status.status
  } catch (error) {
    console.error('[Settings] 获取桥接服务状态失败:', error)
  }
}

// 获取桥接服务配置
const fetchBridgeConfig = async () => {
  try {
    if (!window.electronAPI) return
    const config = await window.electronAPI.getBridgeConfig()
    bridgeConfig.value = config
  } catch (error) {
    console.error('[Settings] 获取桥接服务配置失败:', error)
  }
}

// 重启桥接服务
const restartBridge = async () => {
  bridgeRestarting.value = true
  try {
    const result = await window.electronAPI?.restartBridge()
    if (result?.success) {
      ElMessage.success('浏览器桥接服务正在重启...')
      // 等待服务启动
      setTimeout(() => {
        fetchBridgeStatus()
      }, 2000)
    } else {
      ElMessage.error('重启失败，请检查日志')
    }
  } catch (error) {
    console.error('[Settings] 重启桥接服务失败:', error)
    ElMessage.error('重启失败')
  } finally {
    bridgeRestarting.value = false
  }
}

const goToScheduler = () => {
  router.push({ name: 'Scheduler' })
}

const goToKnowledge = () => {
  router.push({ name: 'Knowledge' })
}

// 组件挂载时获取状态
onMounted(async () => {
  await fetchBridgeStatus()
  await fetchBridgeConfig()
  await fetchHealthStatus()

  // 定期检查状态（每5秒）
  if (window.electronAPI) {
    statusCheckInterval = window.setInterval(() => {
      fetchBridgeStatus()
    }, 5000)
  }
})

onUnmounted(() => {
  if (statusCheckInterval) {
    clearInterval(statusCheckInterval)
  }
})
</script>

<style scoped lang="scss">
.settings-page {
  display: flex;
  flex-direction: column;
  gap: 24px;

  h2 {
    margin: 0;
  }
}

.settings-sections {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.setting-section {
  background: var(--bg-secondary);
  border-radius: 12px;
  padding: 24px;

  h3 {
    margin: 0 0 20px 0;
    font-size: 16px;
    font-weight: 600;
    color: var(--text-primary);
    padding-bottom: 12px;
    border-bottom: 1px solid var(--border);
  }

  .setting-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 0;
    border-bottom: 1px solid var(--border);

    &:last-child {
      border-bottom: none;
      padding-top: 0;
    }

      .setting-info {
        display: flex;
        flex-direction: column;
        gap: 4px;

        > span:first-child {
          font-size: 14px;
          color: var(--text-primary);
          font-weight: 500;
        }

        .setting-desc {
          font-size: 12px;
          color: var(--text-secondary);

          &.error-reason {
            color: #ef4444;
            word-break: break-all;
            white-space: pre-wrap;
          }
        }
      }

    .setting-value {
      .status-badge {
        padding: 6px 12px;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 500;
        background: var(--bg-tertiary);
        color: var(--text-secondary);

        &.active {
          background: rgba(34, 197, 94, 0.1);
          color: #22c55e;
        }

        &.error {
          background: rgba(239, 68, 68, 0.1);
          color: #ef4444;
        }

        &.warning {
          background: rgba(251, 191, 36, 0.1);
          color: #fbbf24;
        }

        &.starting {
          background: rgba(251, 191, 36, 0.1);
          color: #fbbf24;
        }
      }

      .port-badge {
        padding: 6px 12px;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 500;
        background: var(--bg-tertiary);
        color: var(--text-primary);
        font-family: 'Consolas', 'Monaco', monospace;
      }
    }
  }

  .about-info {
    text-align: center;
    padding: 20px 0;

    .about-header {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 16px;
      margin-bottom: 16px;

      .about-logo {
        width: 64px;
        height: 64px;
        border-radius: 16px;
        background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%);
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 28px;
      }

      .about-title {
        text-align: left;

        strong {
          display: block;
          font-size: 20px;
          color: var(--text-primary);
        }

        .about-version {
          font-size: 13px;
          color: #6366f1;
          background: rgba(99, 102, 241, 0.1);
          padding: 4px 10px;
          border-radius: 12px;
        }
      }
    }

    p {
      margin: 6px 0;
      color: var(--text-secondary);
      font-size: 14px;

      &.about-desc {
        font-size: 13px;
        color: var(--text-secondary);
        opacity: 0.8;
      }
    }
  }
}

.el-button svg {
  margin-left: 4px;
  vertical-align: middle;
}
</style>
