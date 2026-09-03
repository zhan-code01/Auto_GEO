<template>
  <div class="auto-publish-page">
    <!-- 页面头部 -->
    <div class="page-header">
      <h2>自动发布任务管理</h2>
      <el-button type="primary" @click="showCreateDialog = true">
        <el-icon><Plus /></el-icon>
        创建任务
      </el-button>
    </div>

    <!-- 任务状态过滤 -->
    <div class="filter-bar">
      <div class="filter-left">
        <el-radio-group v-model="statusFilter" @change="loadTasks">
          <el-radio-button value="">全部</el-radio-button>
          <el-radio-button value="completed">成功</el-radio-button>
          <el-radio-button value="failed,cancelled">失败</el-radio-button>
        </el-radio-group>
        <el-select
          v-model="platformFilter"
          placeholder="筛选平台"
          clearable
          @change="loadTasks"
          style="width: 150px; margin-left: 12px"
        >
          <el-option label="全部平台" value="" />
          <el-option
            v-for="platform in availablePlatforms"
            :key="platform.key"
            :label="platform.name"
            :value="platform.key"
          />
        </el-select>
      </div>
      <el-button @click="loadTasks" :loading="loading">
        <el-icon><Refresh /></el-icon>
        刷新
      </el-button>
    </div>

    <!-- 任务列表 -->
    <div v-loading="loading" class="task-list">
      <div
        v-for="task in tasks"
        :key="task.id"
        class="task-card"
        :class="`status-${task.status}`"
      >
        <div class="task-header">
          <div class="task-title">
            <h3>{{ task.name }}</h3>
            <el-tag :type="getStatusType(task.status)" size="small">
              {{ getStatusText(task.status) }}
            </el-tag>
            <el-tag v-if="task.exec_type === 'scheduled'" type="warning" size="small">定时</el-tag>
            <el-tag v-else-if="task.exec_type === 'interval'" type="success" size="small">间隔</el-tag>
            <el-tag
              v-for="platform in (task.platforms || [])"
              :key="platform"
              size="small"
              effect="plain"
              style="margin-left: 4px"
            >
              {{ PLATFORMS[platform]?.name || platform }}
            </el-tag>
          </div>
          <div class="task-actions">
            <el-button
              v-if="task.status === 'pending' || task.status === 'failed'"
              type="primary"
              size="small"
              @click="startTask(task.id)"
              :loading="task.id === startingTaskId"
            >
              启动
            </el-button>
            <el-button
              v-if="task.status === 'running'"
              type="danger"
              size="small"
              @click="cancelTask(task.id)"
            >
              取消
            </el-button>
            <el-button
              v-if="task.status === 'failed'"
              type="warning"
              size="small"
              @click="retryTask(task.id)"
              :loading="task.id === retryingTaskId"
            >
              重试
            </el-button>
            <el-button size="small" @click="viewTaskDetail(task)">
              详情
            </el-button>
            <el-dropdown @command="(cmd) => handleTaskAction(cmd, task)">
              <el-button size="small" :icon="MoreFilled" circle />
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="delete" v-if="task.status !== 'running'">删除</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </div>

        <div class="task-description" v-if="task.description">
          {{ task.description }}
        </div>

        <div class="task-info">
          <div class="info-item">
            <span class="label">文章数量:</span>
            <span class="value">{{ task.article_ids?.length || 0 }}</span>
          </div>
          <div class="info-item">
            <span class="label">账号数量:</span>
            <span class="value">{{ task.account_ids?.length || 0 }}</span>
          </div>
          <div class="info-item">
            <span class="label">总任务数:</span>
            <span class="value">{{ task.total_count }}</span>
          </div>
          <div class="info-item">
            <span class="label">已完成:</span>
            <span class="value success">{{ task.completed_count }}</span>
          </div>
          <div class="info-item">
            <span class="label">失败:</span>
            <span class="value danger">{{ task.failed_count }}</span>
          </div>
          <div class="info-item" v-if="task.scheduled_at">
            <span class="label">定时时间:</span>
            <span class="value">{{ formatTime(task.scheduled_at) }}</span>
          </div>
        </div>

        <div class="task-progress" v-if="task.status === 'running' || task.total_count > 0">
          <el-progress
            :percentage="getProgress(task)"
            :status="task.failed_count > 0 ? 'exception' : (getProgress(task) === 100 ? 'success' : undefined)"
          />
        </div>

        <div class="task-error" v-if="task.error_msg">
          <el-icon><Warning /></el-icon>
          {{ task.error_msg }}
        </div>

        <div class="task-time">
          创建时间: {{ formatTime(task.created_at) }}
          <span v-if="task.started_at"> | 开始: {{ formatTime(task.started_at) }}</span>
          <span v-if="task.completed_at"> | 完成: {{ formatTime(task.completed_at) }}</span>
        </div>
      </div>

      <!-- 空状态 -->
      <div v-if="!loading && tasks.length === 0" class="empty-state">
        <el-empty description="暂无自动发布任务">
          <el-button type="primary" @click="showCreateDialog = true">创建第一个任务</el-button>
        </el-empty>
      </div>
    </div>

    <!-- 创建任务对话框 -->
    <el-dialog
      v-model="showCreateDialog"
      width="680px"
      :close-on-click-modal="false"
      class="create-task-dialog"
    >
      <template #header>
        <div class="dialog-header">
          <div class="dialog-header-icon">
            <el-icon><Promotion /></el-icon>
          </div>
          <div class="dialog-header-text">
            <div class="dialog-header-title">创建自动发布任务</div>
            <div class="dialog-header-subtitle">选择文章与发布账号，配置执行方式</div>
          </div>
        </div>
      </template>

      <el-form
        :model="createForm"
        label-width="96px"
        :rules="formRules"
        ref="createFormRef"
        class="create-task-form"
      >
        <el-form-item label="任务名称" prop="name">
          <el-input v-model="createForm.name" placeholder="请输入任务名称" />
        </el-form-item>

        <el-form-item label="任务描述" prop="description">
          <el-input v-model="createForm.description" type="textarea" :rows="2" placeholder="可选：任务描述" />
        </el-form-item>

        <el-form-item label="选择文章" prop="article_ids">
          <el-select
            v-model="createForm.article_ids"
            multiple
            filterable
            placeholder="请选择要发布的文章"
            style="width: 100%"
          >
            <el-option
              v-for="article in availableArticles"
              :key="article.id"
              :label="article.title || '无标题'"
              :value="article.id"
            >
              <div class="article-option">
                <span class="article-option-title">{{ article.title || '无标题' }}</span>
                <el-tag size="small" :type="getArticlePublishTagType(article)" effect="light" class="article-status-tag">
                  <span class="status-dot" :class="article.publish_status === 'published' ? 'is-published' : 'is-unpublished'"></span>
                  {{ getArticlePublishLabel(article) }}
                </el-tag>
              </div>
            </el-option>
          </el-select>
        </el-form-item>

        <el-form-item label="选择账号" prop="account_ids">
          <el-tree-select
            v-model="createForm.account_ids"
            :data="publishAccountTree"
            multiple
            show-checkbox
            node-key="id"
            :render-after-expand="false"
            expand-on-click-node
            collapse-tags
            clearable
            placeholder="请选择要发布的平台账号"
            style="width: 100%"
          >
            <template #default="{ data }">
              <div class="account-tree-node">
                <template v-if="data.isPlatform">
                  <span class="atn-platform-name">{{ data.platformName }}</span>
                  <span class="atn-count">{{ data.accountCount }}个账号</span>
                </template>
                <template v-else>
                  <span class="atn-dot" :style="{ backgroundColor: data.color }"></span>
                  <span class="atn-account-name">{{ data.label }}</span>
                </template>
              </div>
            </template>
          </el-tree-select>
          <div class="form-tip">勾选平台可选中其全部账号，展开平台后可逐账号选择。</div>
        </el-form-item>

        <el-form-item label="执行类型" prop="exec_type">
          <el-radio-group v-model="createForm.exec_type" @change="onExecTypeChange" class="exec-type-cards">
            <el-radio value="immediate" class="exec-card" border>
              <span class="exec-card-title">立即执行</span>
              <span class="exec-card-desc">创建后立即开始发布</span>
            </el-radio>
            <el-radio value="scheduled" class="exec-card" border>
              <span class="exec-card-title">定时执行</span>
              <span class="exec-card-desc">到设定时间自动发布</span>
            </el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item
          v-if="createForm.exec_type === 'scheduled'"
          label="执行时间"
          prop="scheduled_at"
        >
          <el-date-picker
            v-model="createForm.scheduled_at"
            type="datetime"
            placeholder="选择执行时间"
            format="YYYY-MM-DD HH:mm"
            value-format="YYYY-MM-DDTHH:mm"
            :disabled-date="disabledPastDate"
            :disabled-hours="disabledPastHours"
            :disabled-minutes="disabledPastMinutes"
            style="width: 100%"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <div class="dialog-footer">
          <el-button @click="showCreateDialog = false">取消</el-button>
          <el-button type="primary" @click="createTask" :loading="creating">
            <el-icon v-if="!creating"><Promotion /></el-icon>
            创建任务
          </el-button>
        </div>
      </template>
    </el-dialog>

    <!-- 任务详情对话框 -->
    <el-dialog
      v-model="showDetailDialog"
      :title="`任务详情 - ${currentTask?.name}`"
      width="800px"
    >
      <div v-if="currentTask" class="task-detail">
        <div class="detail-section">
          <h4>基本信息</h4>
          <div class="detail-grid">
            <div class="detail-item">
              <span class="label">状态:</span>
              <el-tag :type="getStatusType(currentTask.status)">{{ getStatusText(currentTask.status) }}</el-tag>
            </div>
            <div class="detail-item">
              <span class="label">执行类型:</span>
              <span>{{ getExecTypeText(currentTask.exec_type) }}</span>
            </div>
            <div class="detail-item">
              <span class="label">文章数量:</span>
              <span>{{ currentTask.article_ids?.length || 0 }}</span>
            </div>
            <div class="detail-item">
              <span class="label">账号数量:</span>
              <span>{{ currentTask.account_ids?.length || 0 }}</span>
            </div>
            <div class="detail-item">
              <span class="label">总任务数:</span>
              <span>{{ currentTask.total_count }}</span>
            </div>
            <div class="detail-item">
              <span class="label">已完成:</span>
              <span class="success">{{ currentTask.completed_count }}</span>
            </div>
            <div class="detail-item">
              <span class="label">失败:</span>
              <span class="danger">{{ currentTask.failed_count }}</span>
            </div>
          </div>
        </div>

        <div class="detail-section">
          <h4>子任务记录</h4>
          <el-table :data="taskRecords" style="width: 100%" max-height="400">
            <el-table-column prop="article_title" label="文章" width="200" show-overflow-tooltip />
            <el-table-column prop="account_name" label="账号" width="120" />
            <el-table-column prop="platform" label="平台" width="100">
              <template #default="{ row }">
                <el-tag size="small" :color="PLATFORMS[row.platform]?.color">
                  {{ PLATFORMS[row.platform]?.name || row.platform }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="status" label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="getRecordStatusType(row.status)" size="small">
                  {{ getRecordStatusText(row.status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="platform_url" label="链接" width="150" show-overflow-tooltip>
              <template #default="{ row }">
                <a v-if="row.platform_url" :href="row.platform_url" target="_blank">查看</a>
              </template>
            </el-table-column>
            <el-table-column prop="error_msg" label="错误" show-overflow-tooltip />
            <el-table-column prop="created_at" label="创建时间" width="160">
              <template #default="{ row }">
                {{ formatTime(row.created_at) }}
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { Plus, Refresh, MoreFilled, Warning, Promotion } from '@element-plus/icons-vue'
import { autoPublishApi, geoArticleApi, accountApi } from '@/services/api'
import { useWebSocket } from '@/composables/useWebSocket'
import { PLATFORMS, getEnabledPlatforms } from '@/core/config/platform'
import { defaultScheduleTime, disabledPastDate, disabledPastHours, disabledPastMinutes, isPastScheduleTime } from '@/utils/scheduleTime'

// WebSocket
const { onAutoPublishProgress } = useWebSocket()
let unsubscribeAutoPublishProgress: (() => void) | null = null

// 数据
const tasks = ref<any[]>([])
const loading = ref(false)
const statusFilter = ref('')
const platformFilter = ref('')
const availableArticles = ref<any[]>([])
const availableAccounts = ref<any[]>([])
const localSessionStatus = ref<Record<string, boolean>>({})

// 平台筛选下拉框：从已加载的账号中提取有账号的平台
const availablePlatforms = computed(() => {
  const platformSet = new Set<string>()
  availableAccounts.value.forEach((account: any) => {
    if (account.platform) {
      platformSet.add(account.platform)
    }
  })
  // 过滤掉 AI 收录监控平台（不参与发布任务）
  const excludedPlatforms = new Set(['deepseek', 'doubao', 'qianwen'])
  return Array.from(platformSet)
    .filter(key => !excludedPlatforms.has(key))
    .map(key => ({
      key,
      name: PLATFORMS[key]?.name || key
    }))
})

// 创建任务「选择平台」下拉：与账号管理一致，只展示已实现可发布的平台
// （不含 AI 评测平台 doubao/qianwen/deepseek，也不含「自定义」占位平台）
const publishPlatformOptions = computed(() =>
  getEnabledPlatforms().map(p => ({ key: p.id, name: p.name }))
)

// 创建任务「选择账号」树：一级为平台（显示账号数），二级为该平台下的账号。
// 叶子节点 key 使用账号 ID，勾选平台 = 选中其全部可用账号，也可展开逐账号勾选。
const publishAccountTree = computed(() => {
  return publishPlatformOptions.value.map(p => {
    const accounts = availableAccounts.value.filter((a: any) => a.platform === p.key)
    return {
      id: `platform:${p.key}`,
      label: `${p.name}（${accounts.length}个账号）`,
      platformName: p.name,
      accountCount: accounts.length,
      isPlatform: true,
      disabled: getPlatformOptionDisabled(p.key),
      children: accounts.map((a: any) => ({
        id: a.id,
        label: a.account_name || a.username || `账号 ${a.id}`,
        platformName: p.name,
        color: PLATFORMS[p.key]?.color || '#c4741c',
        isPlatform: false,
        disabled: !a.is_authorized || !getPlatformLocalLoginOk(p.key)
      }))
    }
  })
})

// 创建任务对话框
const showCreateDialog = ref(false)
const creating = ref(false)
const createForm = ref({
  name: '',
  description: '',
  article_ids: [] as number[],
  account_ids: [] as number[],
  exec_type: 'immediate' as 'immediate' | 'scheduled',
  scheduled_at: '',
})
const createFormRef = ref<FormInstance>()
const formRules: FormRules = {
  name: [{ required: true, message: '请输入任务名称', trigger: 'blur' }],
  article_ids: [{ required: true, message: '请选择文章', trigger: 'change' }],
  account_ids: [{ required: true, message: '请选择发布账号', trigger: 'change' }],
  scheduled_at: [{ required: true, message: '请选择执行时间', trigger: 'change' }],
}

// 任务详情对话框
const showDetailDialog = ref(false)
const currentTask = ref<any>(null)
const taskRecords = ref<any[]>([])

// 操作状态
const startingTaskId = ref<number | null>(null)
const retryingTaskId = ref<number | null>(null)

// 加载任务列表
const loadTasks = async () => {
  loading.value = true
  try {
    const params: any = { limit: 100 }
    if (statusFilter.value) {
      params.status = statusFilter.value
    }
    if (platformFilter.value) {
      params.platform = platformFilter.value
    }
    const res: any = await autoPublishApi.getTasks(params)
    tasks.value = res.data?.items || []
  } catch (e) {
    console.error('加载任务失败:', e)
  } finally {
    loading.value = false
  }
}

// 加载可用文章和账号
const loadAvailableData = async () => {
  try {
    // 加载可用文章：后端创建任务接口已移除文章状态限制（允许任何有内容的文章重复发布），
    // 因此不再按 publish_status 过滤，加载全部文章并在选项中展示「已发布 / 未发布」两态。
    const articlesRes: any = await geoArticleApi.getArticles({ limit: 1000 })
    availableArticles.value = Array.isArray(articlesRes) ? articlesRes : (articlesRes?.data || articlesRes?.items || [])

    // 加载可用账号（后端返回 PaginatedResponse，数据在 items 字段，limit 最大 100）
    const accountsRes: any = await accountApi.getList({ status: 1, limit: 100 })
    availableAccounts.value = Array.isArray(accountsRes) ? accountsRes : (accountsRes?.items || accountsRes?.data || [])
    await loadLocalSessionStatus()
  } catch (e) {
    console.error('加载数据失败:', e)
  }
}

// 加载当前 EXE 本机保存的平台登录态
const loadLocalSessionStatus = async () => {
  const platforms = Object.keys(PLATFORMS)
  if (!window.electronAPI?.localAuth?.getSessionStatus) {
    localSessionStatus.value = Object.fromEntries(platforms.map(platform => [platform, true]))
    return
  }

  try {
    const result = await window.electronAPI.localAuth.getSessionStatus(platforms)
    localSessionStatus.value = result?.sessions || {}
  } catch (e) {
    console.error('加载本机登录态失败:', e)
    localSessionStatus.value = {}
  }
}

// 获取平台的账号数量
const getPlatformAccountCount = (platform: string) => {
  return availableAccounts.value.filter((a: any) => a.platform === platform).length
}

// 获取平台"已授权（真正持有登录凭证）"的账号数量。
// is_authorized 由后端按授权模式派生：本地客户端(local_only)看是否已绑定设备，
// 云端浏览器(server)看 cookies && storage_state。status=1 只表示启用不代表已登录。
const getPlatformAuthorizedCount = (platform: string) => {
  return availableAccounts.value.filter((a: any) => a.platform === platform && a.is_authorized).length
}

const getPlatformLocalLoginOk = (platform: string) => {
  return Boolean(localSessionStatus.value[platform])
}

const getPlatformOptionDisabled = (platform: string) => {
  return getPlatformAccountCount(platform) === 0
    || getPlatformAuthorizedCount(platform) === 0
    || !getPlatformLocalLoginOk(platform)
}

const getBlockedPlatforms = (platforms: string[]) => {
  return platforms.filter(platform => getPlatformOptionDisabled(platform))
}

const getPlatformPublishBlockReason = (platform: string) => {
  const name = PLATFORMS[platform]?.name || platform
  if (getPlatformAccountCount(platform) === 0) return `${name}没有可用账号`
  if (getPlatformAuthorizedCount(platform) === 0) return `${name}账号尚未登录，请先在「账号管理」完成授权`
  if (!getPlatformLocalLoginOk(platform)) return `${name}未在当前 EXE 本机登录`
  return `${name}不可发布`
}

// 创建任务
const createTask = async () => {
  if (creating.value) return
  if (!createFormRef.value) return
  await createFormRef.value.validate(async (valid) => {
    if (!valid) return
    if (
      createForm.value.exec_type === 'scheduled' &&
      createForm.value.scheduled_at &&
      isPastScheduleTime(createForm.value.scheduled_at)
    ) {
      ElMessage.warning('定时发布时间必须晚于当前时间')
      creating.value = false
      return
    }
    creating.value = true
    try {
      // 账号已在「选择账号」树中直接选定，这里仅做兜底校验：
      // 剔除已失去授权/被禁用的账号（正常情况下这些账号在树里已被置灰）。
      const accountIds = createForm.value.account_ids
      const validAccountIds = availableAccounts.value
        .filter((a: any) => accountIds.includes(a.id) && a.is_authorized)
        .map((a: any) => a.id)

      if (validAccountIds.length === 0) {
        ElMessage.warning('所选账号暂无可用授权，请先在「账号管理」中完成授权')
        creating.value = false
        return
      }

      await autoPublishApi.create({
        name: createForm.value.name,
        description: createForm.value.description || undefined,
        article_ids: createForm.value.article_ids,
        account_ids: validAccountIds,
        exec_type: createForm.value.exec_type,
        scheduled_at: createForm.value.scheduled_at || undefined,
        execution_mode: 'local_client'
      })
      if (window.electronAPI?.publishEngine?.start) {
        const token = localStorage.getItem('autogeo_token') || ''
        if (token) {
          const engineResult = await window.electronAPI.publishEngine.start(token)
          if (!engineResult?.success) {
            ElMessage.warning(`本地客户端发布引擎启动失败：${engineResult?.error || '未知错误'}`)
          }
        } else {
          ElMessage.warning('本地客户端发布引擎需要登录后启动')
        }
      }
      ElMessage.success('任务创建成功')
      showCreateDialog.value = false
      resetCreateForm()
      await loadTasks()
    } catch (e) {
      console.error('创建任务失败:', e)
    } finally {
      creating.value = false
    }
  })
}

// 重置创建表单
const resetCreateForm = () => {
  createForm.value = {
    name: '',
    description: '',
    article_ids: [],
    account_ids: [],
    exec_type: 'immediate',
    scheduled_at: '',
  }
  createFormRef.value?.resetFields()
}

const onExecTypeChange = (value: string | number | boolean | undefined) => {
  if (value === 'scheduled') {
    createForm.value.scheduled_at = defaultScheduleTime()
  }
}

// 启动任务
const startTask = async (taskId: number) => {
  startingTaskId.value = taskId
  try {
    await loadLocalSessionStatus()
    const task = tasks.value.find(t => t.id === taskId)
    const taskPlatforms = task?.platforms || []
    const blockedPlatforms = getBlockedPlatforms(taskPlatforms)
    if (blockedPlatforms.length > 0) {
      ElMessage.warning(`任务包含未就绪平台：${blockedPlatforms.map(getPlatformPublishBlockReason).join('、')}`)
      return
    }

    await autoPublishApi.start(taskId)
    ElMessage.success('任务已启动')
    await loadTasks()
  } catch (e) {
    console.error('启动任务失败:', e)
  } finally {
    startingTaskId.value = null
  }
}

// 取消任务
const cancelTask = async (taskId: number) => {
  try {
    await ElMessageBox.confirm('确认取消此任务？', '提示', {
      type: 'warning'
    })
    await autoPublishApi.cancel(taskId)
    ElMessage.success('任务已取消')
    await loadTasks()
  } catch (e) {
    if (e !== 'cancel') console.error('取消任务失败:', e)
  }
}

// 重试任务
const retryTask = async (taskId: number) => {
  retryingTaskId.value = taskId
  try {
    await autoPublishApi.retry(taskId)
    ElMessage.success('任务已重试')
    await loadTasks()
  } catch (e) {
    console.error('重试任务失败:', e)
  } finally {
    retryingTaskId.value = null
  }
}

// 查看任务详情
const viewTaskDetail = async (task: any) => {
  currentTask.value = task
  showDetailDialog.value = true
  try {
    const res: any = await autoPublishApi.getTask(task.id)
    taskRecords.value = res.data?.records || []
  } catch (e) {
    console.error('加载任务详情失败:', e)
  }
}

// 处理任务操作
const handleTaskAction = async (command: string, task: any) => {
  if (command === 'delete') {
    try {
      await ElMessageBox.confirm('确认删除此任务？', '提示', {
        type: 'warning'
      })
      await autoPublishApi.delete(task.id)
      ElMessage.success('任务已删除')
      await loadTasks()
    } catch (e) {
      if (e !== 'cancel') console.error('删除任务失败:', e)
    }
  }
}

// 工具方法
// 文章发布状态：选择文章时只区分「已发布 / 未发布」两态
// （与后端 auto_publish 已移除状态限制、允许重复发布的新逻辑一致）
const getArticlePublishLabel = (article: any) => {
  return article?.publish_status === 'published' ? '已发布' : '未发布'
}

const getArticlePublishTagType = (article: any) => {
  return article?.publish_status === 'published' ? 'success' : 'info'
}

const getStatusType = (status: string) => {
  const typeMap: Record<string, any> = {
    pending: 'info',
    running: 'warning',
    completed: 'success',
    failed: 'danger',
    cancelled: 'info'
  }
  return typeMap[status] || 'info'
}

const getStatusText = (status: string) => {
  const textMap: Record<string, string> = {
    pending: '待执行',
    running: '执行中',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消'
  }
  return textMap[status] || status
}

const getExecTypeText = (execType: string) => {
  const textMap: Record<string, string> = {
    immediate: '立即执行',
    scheduled: '定时执行',
    interval: '间隔执行'
  }
  return textMap[execType] || execType
}

const getRecordStatusType = (status: string) => {
  const typeMap: Record<string, any> = {
    pending: 'info',
    publishing: 'warning',
    success: 'success',
    failed: 'danger',
    skipped: 'info'
  }
  return typeMap[status] || 'info'
}

const getRecordStatusText = (status: string) => {
  const textMap: Record<string, string> = {
    pending: '待发布',
    publishing: '发布中',
    success: '成功',
    failed: '失败',
    skipped: '跳过'
  }
  return textMap[status] || status
}

const getProgress = (task: any) => {
  if (task.total_count === 0) return 0
  return Math.round((task.completed_count / task.total_count) * 100)
}

const formatTime = (time: string) => {
  if (!time) return '-'
  return new Date(time).toLocaleString('zh-CN')
}

// WebSocket 监听进度更新
const setupWebSocket = () => {
  unsubscribeAutoPublishProgress = onAutoPublishProgress((data: any) => {
    // 更新任务列表中的进度
    const task = tasks.value.find(t => t.id === data.task_id)
    if (task) {
      task.completed_count = data.completed_count || task.completed_count
      task.failed_count = data.failed_count || task.failed_count
    }

    // 如果详情页打开，也更新详情
    if (currentTask.value && currentTask.value.id === data.task_id) {
      const record = taskRecords.value.find(r => r.id === data.record_id)
      if (record) {
        record.status = data.status
        record.platform_url = data.platform_url
        record.error_msg = data.error_msg
      }
    }
  })
}

onMounted(async () => {
  await loadAvailableData()
  await loadTasks()
  setupWebSocket()
})

onUnmounted(() => {
  unsubscribeAutoPublishProgress?.()
  unsubscribeAutoPublishProgress = null
})
</script>

<style scoped lang="scss">
.auto-publish-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--surface-root);
  padding: 24px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;

  h2 {
    margin: 0;
    color: var(--text-head);
    font-size: 20px;
    font-weight: 600;
  }
}

.filter-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  padding: 16px 20px;
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.05);

  .filter-left {
    display: flex;
    align-items: center;
    gap: 12px;
  }
}

.task-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.task-card {
  background: #fff;
  border-radius: 8px;
  padding: 20px;
  border-left: 4px solid transparent;
  transition: all 0.3s;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.05);

  &:hover {
    box-shadow: 0 4px 16px 0 rgba(0, 0, 0, 0.1);
  }

  &.status-pending {
    border-left-color: #909399;
  }

  &.status-running {
    border-left-color: #e6a23c;
  }

  &.status-completed {
    border-left-color: #67c23a;
  }

  &.status-failed {
    border-left-color: #f56c6c;
  }
}

.task-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
}

.task-title {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;

  h3 {
    margin: 0;
    color: #303133;
    font-size: 16px;
    font-weight: 600;
  }
}

.task-actions {
  display: flex;
  gap: 8px;
}

.task-description {
  color: #606266;
  margin-bottom: 16px;
  font-size: 14px;
  line-height: 1.5;
}

.task-info {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 16px;
  margin-bottom: 16px;

  .info-item {
    display: flex;
    align-items: center;
    gap: 8px;

    .label {
      color: #909399;
      font-size: 14px;
    }

    .value {
      color: #303133;
      font-weight: 600;
      font-size: 15px;

      &.success {
        color: #67c23a;
      }

      &.danger {
        color: #f56c6c;
      }
    }
  }
}

.task-progress {
  margin-bottom: 16px;
}

.task-error {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  background: #fef0f0;
  border-radius: 6px;
  color: #f56c6c;
  font-size: 14px;
  margin-bottom: 16px;
}

.task-time {
  color: #909399;
  font-size: 13px;
}

.empty-state {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 300px;
}

.article-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  width: 100%;
}

.article-option-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.article-status-tag {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;

  &.is-published {
    background: var(--success);
  }

  &.is-unpublished {
    background: #b8ad99;
  }
}

.form-tip {
  margin-top: 6px;
  padding: 0 4px;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.5;
}

.task-detail {
  .detail-section {
    margin-bottom: 24px;

    h4 {
      margin: 0 0 16px 0;
      color: #303133;
      font-size: 16px;
      font-weight: 600;
    }
  }

  .detail-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 16px;

    .detail-item {
      display: flex;
      flex-direction: column;
      gap: 8px;
      padding: 16px;
      background: #f5f7fa;
      border-radius: 8px;

      .label {
        color: #909399;
        font-size: 13px;
      }

      .success {
        color: #67c23a;
      }

      .danger {
        color: #f56c6c;
      }
    }
  }
}

/* ================================================================
   创建任务对话框 — Atelier Lumière 风格优化
   ================================================================ */

/* 对话框整体覆盖 */
.create-task-dialog {
  :deep(.el-dialog) {
    background:
      linear-gradient(180deg, rgba(255, 253, 247, 0.7), rgba(251, 248, 242, 0.5) 40%, transparent),
      var(--surface-raised);
    border-radius: var(--radius-xl) !important;
    box-shadow:
      0 24px 64px rgba(74, 53, 24, 0.14),
      0 8px 24px rgba(74, 53, 24, 0.08);
    overflow: hidden;
  }

  :deep(.el-dialog__header) {
    padding: 28px 32px 0 !important;
  }

  :deep(.el-dialog__body) {
    padding: 24px 32px 28px !important;
  }

  :deep(.el-dialog__footer) {
    padding: 0 32px 24px !important;
  }
}

/* ---- 头部区域 ---- */
.dialog-header {
  display: flex;
  align-items: center;
  gap: 16px;
}

.dialog-header-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 48px;
  height: 48px;
  border-radius: 14px;
  background:
    linear-gradient(135deg, var(--accent-hover), var(--accent));
  color: #fff;
  font-size: 22px;
  flex-shrink: 0;
  box-shadow: 0 4px 14px rgba(196, 116, 28, 0.3);
}

.dialog-header-text {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.dialog-header-title {
  font-family: var(--font-display);
  font-size: 20px;
  font-weight: 700;
  color: var(--text-head);
  letter-spacing: -0.01em;
}

.dialog-header-subtitle {
  font-size: 13px;
  color: var(--text-muted);
  font-weight: 400;
}

/* ---- 表单容器 ---- */
.create-task-form {
  margin-top: 4px;
}

/* ---- 扁平表单（不分类，统一间距）---- */
.create-task-form {
  margin-top: 4px;

  .el-form-item {
    margin-bottom: 20px;

    &:last-child {
      margin-bottom: 0;
    }
  }

  /* 标签文字 */
  :deep(.el-form-item__label) {
    font-weight: 500;
    font-size: 13px;
    color: var(--text-body);
    padding-right: 12px;
  }

  /* 输入框增强 */
  :deep(.el-input__wrapper),
  :deep(.el-select__wrapper),
  :deep(.el-textarea__inner) {
    border-radius: var(--radius-sm) !important;
    transition: all var(--duration-fast) var(--ease-out);
  }

  :deep(.el-textarea__inner) {
    background: var(--surface-raised) !important;
  }
}

/* ---- 底部操作栏 ---- */
.dialog-footer {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 14px;
  padding-top: 8px;

  .el-button:not(.el-button--primary) {
    padding: 10px 22px;
    font-weight: 500;
    border-radius: var(--radius-sm);
  }

  .el-button--primary {
    padding: 10px 26px;
    font-weight: 600;
    border-radius: var(--radius-sm);
    letter-spacing: 0.02em;
  }
}

/* ================================================================
   账号树节点美化
   ================================================================ */
.account-tree-node {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  min-width: 0;
  padding: 2px 0;
}

.atn-platform-name {
  font-weight: 650;
  color: var(--text-head);
  white-space: nowrap;
  font-size: 14px;
}

.atn-count {
  margin-left: auto;
  flex-shrink: 0;
  padding: 1px 10px;
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 12px;
  font-weight: 600;
  line-height: 20px;
  letter-spacing: 0.01em;
}

.atn-dot {
  flex-shrink: 0;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.15);
}

.atn-account-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-body);
  font-size: 14px;
}

/* 树形选择器下拉面板增强 */
:deep(.el-tree-select) {
  --el-tree-node-content-height: 36px;
}

:deep(.el-select-dropdown__item.is-hovering) {
  background: var(--accent-soft) !important;
}

/* ================================================================
   执行类型卡片 — 完全重新设计
   ================================================================ */
.exec-type-cards {
  display: flex;
  gap: 14px;
  width: 100%;
}

.exec-card {
  flex: 1;
  position: relative;
  height: auto !important;
  margin-right: 0 !important;
  padding: 18px 20px !important;
  border-radius: var(--radius-md) !important;
  border: 1.5px solid var(--border-thin) !important;
  background: var(--surface-raised) !important;
  cursor: pointer;
  overflow: hidden;
  transition: all var(--duration-normal) var(--ease-out) !important;

  .exec-card-title {
    display: flex;
    align-items: center;
    gap: 8px;
    font-weight: 700;
    font-size: 15px;
    color: var(--text-head);

    &::before {
      content: '';
      display: inline-block;
      width: 20px;
      height: 20px;
      border-radius: 6px;
      background: var(--surface-field);
      flex-shrink: 0;
      transition: all var(--duration-fast) var(--ease-out);
      background-size: contain;
      background-position: center;
      background-repeat: no-repeat;
    }
  }

  /* 立即执行 — 闪电图标 */
  &:first-of-type .exec-card-title::before {
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%238a7d68' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M13 2L3 14h9l-1 8 10-12h-9l1-8z'/%3E%3C/svg%3E");
  }

  /* 定时执行 — 时钟图标 */
  &:last-of-type .exec-card-title::before {
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%238a7d68' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='12' cy='12' r='10'/%3E%3Cpolyline points='12 6 12 12 16 14'/%3E%3C/svg%3E");
  }

  .exec-card-desc {
    display: block;
    margin-top: 6px;
    font-size: 12px;
    color: var(--text-muted);
    line-height: 1.5;
    padding-left: 28px;
  }

  :deep(.el-radio__label) {
    white-space: normal;
    line-height: 1.5;
    width: 100%;
  }

  :deep(.el-radio__input) {
    position: absolute;
    right: 16px;
    top: 16px;
  }

  /* hover 态 */
  &:hover {
    border-color: var(--border-hover) !important;

    .exec-card-title::before {
      background-color: var(--accent-soft);
    }
  }

  /* 选中态 */
  &.is-checked {
    border-color: var(--accent) !important;
    background: var(--accent-soft) !important;

    .exec-card-title {
      color: var(--accent);
    }

    .exec-card-title::before {
      background-color: var(--accent-soft);
    }

    .exec-card-desc {
      color: var(--text-body);
    }
  }
}

/* 文章选项内的 tag 微调 */
:deep(.article-option .el-tag) {
  border-radius: 999px;
  font-size: 11px;
  padding: 0 10px;
}
</style>
