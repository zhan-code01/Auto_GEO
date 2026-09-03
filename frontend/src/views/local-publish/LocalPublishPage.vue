<template>
  <div class="local-publish-page">
    <!-- Tab 切换 -->
    <el-tabs v-model="activeTab" type="card" class="publish-tabs">
      <!-- ==================== Tab 1: 平台账号绑定 ==================== -->
      <el-tab-pane label="平台账号绑定" name="binding">
        <el-card shadow="never" class="binding-card">
          <template #header>
            <div class="card-header">
              <span>平台账号管理</span>
              <el-button
                type="primary"
                size="small"
                :loading="refreshing"
                @click="refreshAccounts"
              >
                刷新状态
              </el-button>
            </div>
          </template>

          <el-table
            :data="platformList"
            stripe
            style="width: 100%"
            v-loading="refreshing"
          >
            <el-table-column label="平台" width="180">
              <template #default="{ row }">
                <div class="platform-cell">
                  <el-icon :size="20" :color="row.color">
                    <component :is="row.icon" />
                  </el-icon>
                  <span class="platform-name">{{ row.label }}</span>
                </div>
              </template>
            </el-table-column>

            <el-table-column label="绑定状态" width="120">
              <template #default="{ row }">
                <el-tag
                  :type="row.bound ? 'success' : 'info'"
                  size="small"
                >
                  {{ row.bound ? '已绑定' : '未绑定' }}
                </el-tag>
              </template>
            </el-table-column>

            <el-table-column label="账号名称" min-width="160">
              <template #default="{ row }">
                <span v-if="row.bound && row.accountName" class="account-name">
                  {{ row.accountName }}
                </span>
                <span v-else class="no-account">-</span>
              </template>
            </el-table-column>

            <el-table-column label="操作" width="180" align="center">
              <template #default="{ row }">
                <!-- 正在授权中 -->
                <el-button
                  v-if="authingPlatform === row.key"
                  type="primary"
                  size="small"
                  loading
                  disabled
                >
                  授权中...
                </el-button>
                <!-- 已绑定 → 重新授权 -->
                <el-button
                  v-else-if="row.bound"
                  type="warning"
                  size="small"
                  :disabled="authingPlatform !== null"
                  @click="startAuth(row.key)"
                >
                  重新授权
                </el-button>
                <!-- 未绑定 → 绑定 -->
                <el-button
                  v-else
                  type="primary"
                  size="small"
                  :disabled="authingPlatform !== null"
                  @click="startAuth(row.key)"
                >
                  绑定
                </el-button>
              </template>
            </el-table-column>
          </el-table>

          <!-- 授权提示 -->
          <el-alert
            v-if="authingPlatform"
            :title="`正在为「${getPlatformLabel(authingPlatform)}」进行授权，请在打开的浏览器窗口中完成扫码登录...`"
            type="info"
            :closable="false"
            show-icon
            style="margin-top: 12px"
          />
        </el-card>
      </el-tab-pane>

      <!-- ==================== Tab 2: 执行中任务 ==================== -->
      <el-tab-pane label="执行中任务" name="running">
        <!-- 无任务时 -->
        <el-card v-if="!taskRunning" shadow="never" class="empty-card">
          <el-empty description="当前没有正在执行的任务" />
        </el-card>

        <!-- 有任务时 -->
        <template v-else>
          <!-- 手动操作提示 -->
          <el-alert
            v-if="manualRequired"
            :title="manualMessage || '需要人工操作'"
            type="warning"
            :closable="false"
            show-icon
            class="manual-alert"
          >
            <template #default>
              <el-button
                type="primary"
                size="small"
                @click="continueAfterManual"
              >
                已完成操作，继续
              </el-button>
            </template>
          </el-alert>

          <!-- 任务进度卡片 -->
          <el-card shadow="never" class="progress-card">
            <template #header>
              <div class="card-header">
                <span class="task-name">{{ activeTaskName || '发布任务' }}</span>
                <el-button type="danger" size="small" @click="stopTask">
                  停止
                </el-button>
              </div>
            </template>

            <!-- 总体进度 -->
            <div class="progress-section">
              <div class="progress-label">
                总体进度：{{ completedCount }} / {{ totalCount }}
              </div>
              <el-progress
                :percentage="progressPercent"
                :status="progressPercent === 100 ? 'success' : undefined"
                :stroke-width="20"
              />
            </div>

            <!-- 记录列表 -->
            <el-table
              :data="records"
              stripe
              style="width: 100%; margin-top: 16px"
              max-height="400"
            >
              <el-table-column label="序号" type="index" width="60" />
              <el-table-column label="文章标题" prop="title" min-width="200" show-overflow-tooltip />
              <el-table-column label="目标平台" prop="platform" width="100" />
              <el-table-column label="状态" width="120" align="center">
                <template #default="{ row }">
                  <el-tag
                    :type="statusTagType(row.status)"
                    size="small"
                  >
                    {{ statusLabel(row.status) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="备注" prop="message" min-width="160" show-overflow-tooltip />
            </el-table>
          </el-card>
        </template>
      </el-tab-pane>

      <!-- ==================== Tab 3: 历史记录 ==================== -->
      <el-tab-pane label="历史记录" name="history">
        <el-card shadow="never" class="history-card">
          <template #header>
            <div class="card-header">
              <span>最近完成的发布任务</span>
              <el-button
                size="small"
                :loading="refreshingHistory"
                @click="refreshHistory"
              >
                刷新
              </el-button>
            </div>
          </template>

          <el-table
            :data="historyList"
            stripe
            style="width: 100%"
            v-loading="refreshingHistory"
          >
            <el-table-column label="任务名称" prop="name" min-width="180" show-overflow-tooltip />
            <el-table-column label="完成时间" prop="time" width="180" />
            <el-table-column label="发布结果" width="160">
              <template #default="{ row }">
                成功 {{ row.successCount }} / 总数 {{ row.totalCount }}
              </template>
            </el-table-column>
            <el-table-column label="状态" width="100" align="center">
              <template #default="{ row }">
                <el-tag
                  :type="row.allSuccess ? 'success' : 'warning'"
                  size="small"
                >
                  {{ row.allSuccess ? '全部成功' : '部分失败' }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>

          <el-empty
            v-if="!refreshingHistory && historyList.length === 0"
            description="暂无历史记录"
          />
        </el-card>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
/**
 * 本地发布管理页面
 * 管理平台账号绑定、执行中任务和历史记录
 */
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Monitor, Link, Reading } from '@element-plus/icons-vue'

// ==================== 类型定义 ====================

interface PlatformItem {
  key: string
  label: string
  icon: any
  color: string
  bound: boolean
  accountName: string | null
  accountId: number | null
}

interface BoundAccount {
  platform: string
  name: string
  active: boolean
  accountId: number
}

interface TaskRecord {
  title: string
  platform: string
  status: 'pending' | 'publishing' | 'success' | 'failed'
  message: string
}

interface HistoryItem {
  name: string
  time: string
  successCount: number
  totalCount: number
  allSuccess: boolean
}

// ==================== 平台列表 ====================

const platformConfig: Record<string, { label: string; icon: any; color: string }> = {
  zhihu: { label: '知乎', icon: Reading, color: '#0084FF' },
  baijiahao: { label: '百家号', icon: Link, color: '#E53935' },
  xiaohongshu: { label: '小红书', icon: Monitor, color: '#FF2442' },
  toutiao: { label: '头条号', icon: Monitor, color: '#E53333' },
}

// ==================== 状态管理 ====================

const activeTab = ref('binding')

// Tab 1: 账号绑定
const platformList = ref<PlatformItem[]>([])
const authingPlatform = ref<string | null>(null)
const refreshing = ref(false)

// Tab 2: 执行中任务
const taskRunning = ref(false)
const activeTaskName = ref('')
const completedCount = ref(0)
const totalCount = ref(0)
const records = ref<TaskRecord[]>([])
const manualRequired = ref(false)
const manualMessage = ref('')

// Tab 3: 历史记录
const historyList = ref<HistoryItem[]>([])
const refreshingHistory = ref(false)

// ==================== 计算属性 ====================

const progressPercent = computed(() => {
  if (totalCount.value === 0) return 0
  return Math.round((completedCount.value / totalCount.value) * 100)
})

// ==================== 工具函数 ====================

function getPlatformLabel(key: string): string {
  return platformConfig[key]?.label || key
}

function statusTagType(status: string): 'info' | 'warning' | 'success' | 'danger' {
  const map: Record<string, 'info' | 'warning' | 'success' | 'danger'> = {
    pending: 'info',
    publishing: 'warning',
    success: 'success',
    failed: 'danger',
  }
  return map[status] || 'info'
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    pending: '等待中',
    publishing: '发布中',
    success: '成功',
    failed: '失败',
  }
  return map[status] || status
}

// ==================== Tab 1: 账号绑定 ====================

/** 初始化平台列表（全部未绑定） */
function initPlatformList() {
  const keys = ['zhihu', 'baijiahao', 'xiaohongshu', 'toutiao']
  platformList.value = keys.map((key) => ({
    key,
    label: platformConfig[key]?.label || key,
    icon: platformConfig[key]?.icon || Monitor,
    color: platformConfig[key]?.color || '#666',
    bound: false,
    accountName: null,
    accountId: null,
  }))
}

/** 刷新已绑定账号列表 */
async function refreshAccounts() {
  refreshing.value = true
  try {
    // 从主进程获取已绑定的账号列表
    const accounts: BoundAccount[] =
      (await window.electronAPI?.localAuth?.getBoundAccounts()) || []

    // 重置为未绑定状态
    initPlatformList()

    // 标记已绑定的平台
    for (const acc of accounts) {
      const item = platformList.value.find((p) => p.key === acc.platform)
      if (item) {
        item.bound = true
        item.accountName = acc.name
        item.accountId = acc.accountId
      }
    }
  } catch (err: any) {
    console.error('[LocalPublish] 刷新账号列表失败:', err)
    ElMessage.error('获取绑定账号列表失败')
  } finally {
    refreshing.value = false
  }
}

/** 开始授权 */
async function startAuth(platform: string) {
  if (authingPlatform.value !== null) {
    ElMessage.warning('已有授权正在进行中，请稍后')
    return
  }

  authingPlatform.value = platform
  try {
    const result = await window.electronAPI?.localAuth?.startAuth(platform)
    if (!result?.success) {
      ElMessage.error(result?.error || '授权失败，请重试')
    }
    // 授权结果通过 onAuthResult 事件异步返回
  } catch (err: any) {
    console.error(`[LocalPublish] 授权失败:`, err)
    ElMessage.error(err?.message || '授权过程中发生错误')
    authingPlatform.value = null
  }
}

/** 授权结果回调 */
function handleAuthResult(data: { platform: string; success: boolean; nickname?: string; error?: string }) {
  authingPlatform.value = null
  if (data.success) {
    ElMessage.success(`「${getPlatformLabel(data.platform)}」授权成功！账号：${data.nickname || '未知'}`)
    refreshAccounts()
  } else {
    ElMessage.error(data.error || `「${getPlatformLabel(data.platform)}」授权失败`)
  }
}

// ==================== Tab 2: 执行中任务 ====================

/** 任务进度回调 */
function handleTaskProgress(data: {
  taskName?: string
  completed?: number
  total?: number
  records?: TaskRecord[]
}) {
  if (data.taskName) activeTaskName.value = data.taskName
  if (data.completed !== undefined) completedCount.value = data.completed
  if (data.total !== undefined) totalCount.value = data.total
  if (data.records) records.value = data.records
}

/** 手动操作回调 */
function handleManualRequired(data: { message?: string }) {
  manualRequired.value = true
  manualMessage.value = data.message || '需要人工操作，请完成浏览器中的操作后继续'
}

/** 人工操作完成后继续 */
async function continueAfterManual() {
  manualRequired.value = false
  manualMessage.value = ''
  try {
    const token = localStorage.getItem('autogeo_token') || ''
    if (!token) {
      ElMessage.error('请先登录后再启动本地发布引擎')
      return
    }
    const result = await window.electronAPI?.publishEngine?.start(token)
    if (result && !result.success) {
      throw new Error(result.error || '本地发布引擎启动失败')
    }
  } catch (err: any) {
    ElMessage.error('继续执行失败: ' + (err?.message || '未知错误'))
  }
}

/** 停止任务 */
async function stopTask() {
  try {
    await ElMessageBox.confirm('确定要停止当前发布任务吗？', '确认停止', {
      confirmButtonText: '停止',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await window.electronAPI?.publishEngine?.stop()
    ElMessage.success('任务已停止')
  } catch {
    // 用户取消
  }
}

// ==================== Tab 3: 历史记录 ====================

async function refreshHistory() {
  refreshingHistory.value = true
  try {
    // 历史记录暂时使用本地存储的 mock 数据
    // 后续接入后端 API: GET /api/publish/history
    const mockHistory: HistoryItem[] = [
      { name: '批量发布测试文章', time: '2026-06-22 15:30:00', successCount: 8, totalCount: 10, allSuccess: false },
      { name: '知乎专栏发布', time: '2026-06-22 14:00:00', successCount: 3, totalCount: 3, allSuccess: true },
      { name: '百家号同步发布', time: '2026-06-21 18:20:00', successCount: 5, totalCount: 6, allSuccess: false },
    ]
    historyList.value = mockHistory
  } catch (err: any) {
    ElMessage.error('获取历史记录失败')
  } finally {
    refreshingHistory.value = false
  }
}

// ==================== 生命周期 ====================

/** 注册 IPC 事件监听 */
function registerListeners() {
  // 授权结果监听
  window.electronAPI?.onAuthResult?.(handleAuthResult)

  // 任务进度监听
  window.electronAPI?.onTaskProgress?.(handleTaskProgress)

  // 手动操作监听
  window.electronAPI?.onManualRequired?.(handleManualRequired)
}

/** 移除 IPC 事件监听 */
const cleanupFns: (() => void)[] = []

function setupListeners() {
  // 使用 addEventListener 模式（兼容 preload 的返回清理函数模式）

  // 授权结果
  const removeAuth = window.electronAPI?.onAuthResult?.(handleAuthResult)
  if (typeof removeAuth === 'function') cleanupFns.push(removeAuth)

  // 任务进度
  const removeProgress = window.electronAPI?.onTaskProgress?.(handleTaskProgress)
  if (typeof removeProgress === 'function') cleanupFns.push(removeProgress)

  // 手动操作
  const removeManual = window.electronAPI?.onManualRequired?.(handleManualRequired)
  if (typeof removeManual === 'function') cleanupFns.push(removeManual)
}

onMounted(async () => {
  // 初始化平台列表
  initPlatformList()

  // 注册事件监听
  setupListeners()

  // 加载已绑定账号
  await refreshAccounts()

  // 加载历史记录
  refreshHistory()

  // 获取当前任务状态（如果引擎已在运行）
  try {
    const status = await window.electronAPI?.publishEngine?.getStatus?.()
    if (status?.running) {
      taskRunning.value = true
      activeTaskName.value = status.activeTask || '发布任务'
      if (status.progress) {
        completedCount.value = status.progress.completed || 0
        totalCount.value = status.progress.total || 0
        records.value = (status.progress.records || []) as TaskRecord[]
      }
    }
  } catch {
    // 获取状态失败，忽略
  }
})

onUnmounted(() => {
  // 清理所有事件监听
  cleanupFns.forEach((fn) => fn())
})
</script>

<style scoped lang="scss">
.local-publish-page {
  padding: 16px;

  .publish-tabs {
    :deep(.el-tabs__header) {
      margin-bottom: 16px;
    }
  }

  .binding-card,
  .progress-card,
  .history-card {
    :deep(.el-card__header) {
      padding: 12px 16px;
      background-color: #fafafa;
      border-bottom: 1px solid #ebeef5;
    }

    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;

      .task-name {
        font-weight: 600;
        font-size: 15px;
        color: #303133;
      }
    }
  }

  .platform-cell {
    display: flex;
    align-items: center;
    gap: 8px;

    .platform-name {
      font-size: 14px;
      color: #303133;
    }
  }

  .account-name {
    color: #67c23a;
    font-weight: 500;
  }

  .no-account {
    color: #c0c4cc;
  }

  .manual-alert {
    margin-bottom: 12px;
  }

  .progress-section {
    .progress-label {
      margin-bottom: 8px;
      font-size: 14px;
      color: #606266;
    }
  }

  .empty-card {
    :deep(.el-card__body) {
      padding: 40px 0;
    }
  }
}
</style>
