<template>
  <div class="articles-page">
    <!-- ========== 页面头部 ========== -->
    <div class="page-hero">
      <div class="hero-content">
        <span class="hero-badge">Content Studio</span>
        <div class="hero-title-row">
          <h1 class="hero-title">文章生成</h1>
          <span class="deprecated-badge">已废弃，请转到智能文章生成模块</span>
        </div>
        <p class="hero-desc">AI 驱动的多平台内容创作与分发引擎</p>
      </div>
      <div class="hero-stats">
        <div class="hero-stat">
          <span class="hero-stat-value">{{ articles.length }}</span>
          <span class="hero-stat-label">文章总数</span>
        </div>
        <div class="hero-stat">
          <span class="hero-stat-value">{{ articles.filter(function(a) { return a.publish_status === 'published' }).length }}</span>
          <span class="hero-stat-label">已发布</span>
        </div>
      </div>
    </div>

    <!-- 选择区域 -->
    <div class="section">
      <h2 class="section-title">生成文章</h2>
      <el-form :inline="true" :model="generateForm" class="generate-form">
        <el-form-item label="选择项目">
          <el-select
            v-model="generateForm.projectId"
            placeholder="请选择项目"
            style="width: 180px"
            @change="onProjectChange"
          >
            <el-option
              v-for="project in validProjects"
              :key="project.id"
              :label="project.name"
              :value="project.id"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="选择搜索问题">
          <el-select
            v-model="generateForm.keywordId"
            placeholder="请选择搜索问题"
            style="width: 180px"
            :disabled="!generateForm.projectId"
          >
            <el-option
              v-for="keyword in questionKeywords"
              :key="keyword.id"
              :label="keyword.keyword || keyword.name"
              :value="keyword.id"
            />
          </el-select>
          <p v-if="generateForm.projectId && questionKeywords.length === 0" class="empty-hint">
            该任务需选择搜索问题，当前项目暂无搜索问题，请先在项目中添加搜索问题。
          </p>
        </el-form-item>

        <el-form-item label="发布平台">
          <el-select
            v-model="generateForm.targetPlatforms"
            placeholder="请选择发布平台"
            multiple
            style="width: 220px"
            clearable
          >
            <el-option
              v-for="platform in PLATFORM_OPTIONS"
              :key="platform.value"
              :label="platform.label"
              :value="platform.value"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="发布策略">
          <el-radio-group v-model="generateForm.publishStrategy" size="small" @change="onPublishStrategyChange">
            <el-radio label="draft">仅生成草稿</el-radio>
            <el-radio label="immediate">生成后立即发布</el-radio>
            <el-radio label="scheduled">定时发布</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item v-if="generateForm.publishStrategy === 'scheduled'" label="发布时间">
          <el-date-picker
            v-model="generateForm.scheduledAt"
            type="datetime"
            placeholder="选择发布时间"
            format="YYYY-MM-DD HH:mm"
            value-format="YYYY-MM-DDTHH:mm"
            :disabled-date="disabledPastDate"
            :disabled-hours="disabledPastHours"
            :disabled-minutes="disabledPastMinutes"
            style="width: 220px"
          />
        </el-form-item>

        <el-form-item>
          <div class="generate-actions">
            <el-button
              type="primary"
              :loading="generating"
              :disabled="!generateForm.keywordId || questionKeywords.length === 0 || bulkGenerating"
              @click="generateArticle"
            >
              <el-icon><MagicStick /></el-icon>
              生成文章
            </el-button>
            <el-button
              type="warning"
              plain
              :loading="bulkGenerating"
              :disabled="!generateForm.projectId || questionKeywords.length === 0 || generating"
              @click="generateProjectArticles"
            >
              <el-icon><MagicStick /></el-icon>
              生成全部文章
            </el-button>
          </div>
          <p v-if="bulkQueueHint" class="queue-hint">{{ bulkQueueHint }}</p>
        </el-form-item>
      </el-form>
    </div>

    <!-- 文章列表 -->
    <div class="section section-list">
      <div class="section-header">
        <div class="header-left">
          <h2 class="section-title">文章列表</h2>
          <span class="filter-label">所属项目</span>
          <el-select
            v-model="filterProjectId"
            placeholder="全部项目"
            clearable
            style="width: 150px;"
            size="small"
            @change="loadArticles"
          >
            <el-option
              v-for="p in validProjects"
              :key="p.id"
              :label="p.name"
              :value="p.id"
            />
          </el-select>

          <span class="filter-label">生成状态</span>
          <el-select
            v-model="filterPublishStatus"
            placeholder="全部状态"
            clearable
            style="width: 140px; margin-left: 12px;"
            size="small"
            @change="loadArticles"
          >
            <el-option label="已生成/待分发" value="completed" />
            <el-option label="已配置定时" value="scheduled" />
            <el-option label="生成中" value="generating" />
            <el-option label="失败" value="failed" />
            <el-option label="发布中" value="publishing" />
            <el-option label="已发布" value="published" />
          </el-select>
        </div>
        <div class="table-actions">
          <el-button
            type="danger"
            size="small"
            plain
            :loading="batchDeleting"
            :disabled="selectedArticleIds.length === 0"
            @click="deleteSelectedArticles"
          >
            <el-icon><DeleteIcon /></el-icon>
            删除选中{{ selectedArticleIds.length ? `（${selectedArticleIds.length}）` : '' }}
          </el-button>
          <el-button @click="loadArticles" size="small" type="primary" plain>
            <el-icon><Refresh /></el-icon>
            刷新列表
          </el-button>
        </div>
      </div>

      <el-table
        v-loading="articlesLoading"
        :data="filteredArticles"
        stripe
        style="width: 100%"
        height="500"
        row-key="id"
      >
        <el-table-column width="42" align="center">
          <template #header>
            <el-checkbox
              :model-value="isCurrentPageAllSelected"
              :indeterminate="isCurrentPageIndeterminate"
              :disabled="filteredArticles.length === 0"
              @change="toggleSelectAllCurrentPage"
            />
          </template>
          <template #default="{ row }">
            <el-checkbox
              :model-value="isArticleSelected(row)"
              @change="(checked) => toggleArticleSelected(row, checked)"
              @click.stop
            />
          </template>
        </el-table-column>

        <el-table-column prop="title" label="标题" min-width="180">
          <template #default="{ row }">
            <div class="title-cell">
              <span class="title-text">{{ row.title || '（内容生成中...）' }}</span>
              <el-tag v-if="isGenerating(row)" type="warning" size="small" style="margin-left: 8px;">
                生成中
              </el-tag>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="所属项目" width="140">
          <template #default="{ row }">
            <span class="text-muted">{{ getProjectName(row.project_id) }}</span>
          </template>
        </el-table-column>

        <el-table-column label="生成状态" width="110">
          <template #default="{ row }">
            <el-tag :type="getGenerateStatusType(row.publish_status)" size="small">
              {{ getArticleStatusText(row) }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="发布策略" width="120">
          <template #default="{ row }">
            <span class="text-muted" style="font-size: 12px;">
              {{ getStrategyDisplay(row) }}
            </span>
          </template>
        </el-table-column>

        <el-table-column label="评分" width="70">
          <template #default="{ row }">
            <span v-if="row.quality_score" :class="getScoreClass(row.quality_score)">
              {{ row.quality_score }}
            </span>
            <span v-else>-</span>
          </template>
        </el-table-column>

        <el-table-column label="创建时间" width="160">
          <template #default="{ row }">
            <span class="text-muted">{{ formatDate(row.created_at) }}</span>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" size="small" link @click="previewArticle(row)">预览</el-button>
            <el-button
              type="primary"
              size="small"
              link
              :disabled="isGenerating(row)"
              @click="openEditDialog(row)"
            >编辑</el-button>
            <el-button
              type="success"
              size="small"
              link
              :disabled="isGenerating(row)"
              @click="handleCheckQuality(row)"
            >质检</el-button>
            <el-button
              v-if="isGenerated(row)"
              type="info"
              size="small"
              link
              :disabled="isPublishActionDisabled(row)"
              @click="openPublishDialog(row)"
            >{{ getPublishActionText(row) }}</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 文章预览对话框 -->
    <el-dialog
      v-model="showPreviewDialog"
      :title="currentArticle?.title || '文章预览'"
      width="800px"
      destroy-on-close
    >
      <div v-if="currentArticle" class="article-preview-scroll">
        <div class="markdown-body" v-html="renderMarkdown(currentArticle.content)"></div>
      </div>
    </el-dialog>

    <!-- 文章编辑对话框 -->
    <el-dialog
      v-model="showEditDialog"
      title="编辑文章"
      width="900px"
      destroy-on-close
    >
      <el-form :model="editForm" label-position="top" class="edit-form">
        <el-form-item label="标题">
          <el-input
            v-model="editForm.title"
            placeholder="请输入文章标题"
            size="large"
            maxlength="200"
            show-word-limit
          />
        </el-form-item>
        <el-form-item label="正文">
          <WangEditor v-model="editForm.content" height="420px" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="showEditDialog = false">取消</el-button>
        <el-button type="primary" :loading="savingEdit" @click="saveEdit">
          保存
        </el-button>
      </template>
    </el-dialog>

    <!-- 发布配置对话框 -->
    <el-dialog
      v-model="showPublishDialog"
      title="发布文章"
      width="560px"
      destroy-on-close
    >
      <div v-if="publishArticle" class="publish-summary">
        <div class="publish-title">{{ publishArticle.title || '未命名文章' }}</div>
        <div class="text-muted">选择发布账号后即可提交发布任务</div>
      </div>

      <el-form :model="publishForm" label-width="90px" class="publish-form">
        <el-form-item label="发布方式">
          <el-radio-group v-model="publishForm.mode">
            <el-radio label="immediate">立即发布</el-radio>
            <el-radio label="scheduled">定时发布</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="发布平台">
          <el-select
            v-model="publishForm.platform"
            placeholder="请选择平台"
            style="width: 100%"
            @change="onPublishPlatformChange"
          >
            <el-option
              v-for="platform in PLATFORM_OPTIONS"
              :key="platform.value"
              :label="platform.label"
              :value="platform.value"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="发布账号">
          <el-select
            :key="publishForm.platform"
            v-model="publishForm.accountId"
            placeholder="请选择已授权账号"
            style="width: 100%"
            :loading="accountsLoading"
            :disabled="!publishForm.platform"
          >
            <el-option
              v-for="account in availablePublishAccounts"
              :key="account.id"
              :label="account.account_name || account.username || `账号 ${account.id}`"
              :value="account.id"
            >
              <div class="account-option">
                <span>{{ account.account_name || account.username || `账号 ${account.id}` }}</span>
                <el-tag size="small" :type="accountStatusMeta(account).type">{{ accountStatusMeta(account).text }}</el-tag>
              </div>
            </el-option>
          </el-select>
          <div v-if="publishForm.platform && availablePublishAccounts.length === 0" class="form-tip">
            当前平台暂无可用账号，请先在账号管理中完成授权。
          </div>
        </el-form-item>

        <el-form-item v-if="publishForm.mode === 'scheduled'" label="发布时间">
          <div class="quick-times" style="margin-bottom: 8px">
            <el-button size="small" @click="setQuickTime(30)">30分钟后</el-button>
            <el-button size="small" @click="setQuickTime(60)">1小时后</el-button>
            <el-button size="small" @click="setQuickTime(120)">2小时后</el-button>
            <el-button size="small" @click="setQuickTomorrow(9, 0)">明天上午9点</el-button>
            <el-button size="small" @click="setQuickTomorrow(20, 0)">明天晚上8点</el-button>
          </div>
          <el-date-picker
            v-model="publishForm.scheduledTime"
            type="datetime"
            placeholder="或手动选择时间"
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
        <el-button @click="showPublishDialog = false">取消</el-button>
        <el-button type="primary" :loading="submittingPublish" @click="submitPublish">
          {{ publishForm.mode === 'scheduled' ? '配置定时发布' : '立即发布' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox, type CheckboxValueType } from 'element-plus'
import { Delete as DeleteIcon, MagicStick, Refresh } from '@element-plus/icons-vue'
import { useWebSocket } from '@/composables/useWebSocket'
import { accountApi, autoPublishApi, geoKeywordApi, geoArticleApi, publishApi } from '@/services/api'
import { getEnabledPlatforms } from '@/core/config/platform'
import { defaultScheduleTime, disabledPastDate, disabledPastHours, disabledPastMinutes, isPastScheduleTime } from '@/utils/scheduleTime'
import MarkdownIt from 'markdown-it'
import WangEditor from '@/components/business/editor/WangEditor.vue'

const md = new MarkdownIt({ html: true, linkify: true })
const renderMarkdown = (content: string) => content ? md.render(content) : '暂无内容'

// 状态
const projects = ref<any[]>([])
const keywords = ref<any[]>([])
const articles = ref<any[]>([])
const articlesLoading = ref(false)
const generating = ref(false)
const showPreviewDialog = ref(false)
const showPublishDialog = ref(false)
const showEditDialog = ref(false)
const currentArticle = ref<any>(null)
const publishArticle = ref<any>(null)
const editArticle = ref<any>(null)
const editForm = ref({ title: '', content: '' })
const savingEdit = ref(false)
const filterProjectId = ref<number | null>(null)
const filterPublishStatus = ref<string | null>(null)
const accounts = ref<any[]>([])
const accountsLoading = ref(false)
const submittingPublish = ref(false)
const bulkGenerating = ref(false)
const bulkQueueHint = ref('')
const selectedArticleIds = ref<number[]>([])
const batchDeleting = ref(false)
let bulkPollTimer: ReturnType<typeof setTimeout> | null = null

// 发布平台选项
const PLATFORM_OPTIONS = getEnabledPlatforms()
  .filter(platform => platform.features?.article)
  .map(platform => ({ label: platform.name, value: platform.id }))

const generateForm = ref({
  projectId: null as number | null,
  keywordId: null as number | null,
  targetPlatforms: [] as string[],
  publishStrategy: 'draft' as 'draft' | 'immediate' | 'scheduled',
  scheduledAt: '' as string
})

const publishForm = ref({
  mode: 'immediate' as 'immediate' | 'scheduled',
  platform: '',
  accountId: null as number | null,
  scheduledTime: ''
})

const onPublishStrategyChange = (value: string | number | boolean | undefined) => {
  if (value === 'scheduled') {
    generateForm.value.scheduledAt = defaultScheduleTime()
  }
}

// 🌟 有效项目列表（过滤掉没有 id 的项目，防止 el-option 报错）
const validProjects = computed(() => {
  return (projects.value || []).filter(p => p?.id !== undefined && p?.id !== null)
})

const filteredArticles = computed(() => articles.value)

const currentPageArticleIds = computed(() => filteredArticles.value.map(article => Number(article.id)))
const isCurrentPageAllSelected = computed(() => {
  const ids = currentPageArticleIds.value
  return ids.length > 0 && ids.every(id => selectedArticleIds.value.includes(id))
})
const isCurrentPageIndeterminate = computed(() => {
  const ids = currentPageArticleIds.value
  const selectedCount = ids.filter(id => selectedArticleIds.value.includes(id)).length
  return selectedCount > 0 && selectedCount < ids.length
})
function isArticleSelected(row: any): boolean {
  return selectedArticleIds.value.includes(Number(row.id))
}
function toggleArticleSelected(row: any, checked: CheckboxValueType) {
  const id = Number(row.id)
  const shouldSelect = checked === true
  if (shouldSelect) {
    if (!selectedArticleIds.value.includes(id)) {
      selectedArticleIds.value = [...selectedArticleIds.value, id]
    }
  } else {
    selectedArticleIds.value = selectedArticleIds.value.filter(item => item !== id)
  }
}
function toggleSelectAllCurrentPage(checked: CheckboxValueType) {
  const currentIds = new Set(currentPageArticleIds.value)
  if (checked === true) {
    const existingIds = new Set(selectedArticleIds.value)
    const addedIds = currentPageArticleIds.value.filter(id => !existingIds.has(id))
    if (addedIds.length) {
      selectedArticleIds.value = [...selectedArticleIds.value, ...addedIds]
    }
  } else {
    selectedArticleIds.value = selectedArticleIds.value.filter(id => !currentIds.has(id))
  }
}

// 🌟 搜索问题（keyword_type === 'question'）：文章生成只针对搜索问题
const questionKeywords = computed(() => {
  return keywords.value.filter(k => k.keyword_type === 'question')
})

const availablePublishAccounts = computed(() => {
  if (!publishForm.value.platform) return []
  return accounts.value.filter(account => {
    const status = Number(account.status)
    return account.platform === publishForm.value.platform && status === 1
  })
})

// 账号授权状态标签（按真实 status 显示，不再写死"可用"）
// status: 1=已授权 / 0=待授权 / -1=已失效
const accountStatusMeta = (account: any) => {
  const status = Number(account.status)
  if (status === -1) return { text: '已失效', type: 'danger' as const }
  if (status === 0) return { text: '待授权', type: 'warning' as const }
  // 已授权：结合最近真实验证时间给出可信度提示（last_check_time 由一键检测/发布成功写入）
  const checked = account.last_check_time
  if (checked) {
    const days = Math.floor((Date.now() - new Date(checked).getTime()) / 86400000)
    return days > 30
      ? { text: '已授权·较久未验证', type: 'warning' as const }
      : { text: '已授权', type: 'success' as const }
  }
  return { text: '已授权·未验证', type: 'info' as const }
}

const getAccountById = (accountId: number | null) => {
  if (!accountId) return null
  return accounts.value.find(account => account.id === accountId) || null
}

const pickAccountForPlatform = (platform: string, preferredAccountId?: number | null) => {
  const platformAccounts = accounts.value.filter(account => {
    const status = Number(account.status)
    return account.platform === platform && status === 1
  })
  if (!platformAccounts.length) return null

  const preferred = preferredAccountId
    ? platformAccounts.find(account => account.id === preferredAccountId)
    : null
  return preferred?.id || platformAccounts[0].id
}

const getElectronServerBaseUrl = () => {
  const configured = import.meta.env.VITE_API_BASE_URL || ''
  if (!configured || configured.startsWith('/')) return undefined
  return configured.replace(/\/api\/?$/, '').replace(/\/+$/, '')
}

const ensureLocalPublishEngineStarted = async () => {
  if (!window.electronAPI?.publishEngine?.start) {
    throw new Error('请在 AutoGEO 客户端中执行本地发布')
  }
  const token = localStorage.getItem('autogeo_token') || ''
  if (!token) {
    throw new Error('本地发布需要先登录')
  }
  const result = await window.electronAPI.publishEngine.start(token, getElectronServerBaseUrl(), 2000)
  if (!result?.success) {
    throw new Error(result?.error || '本地发布引擎启动失败')
  }
}

const getProjectName = (projectId?: number | null) => {
  if (!projectId) return '-'
  return validProjects.value.find(project => project.id === projectId)?.name || `项目 #${projectId}`
}

// 状态判断辅助函数
const isGenerating = (row: any) => row.publish_status === 'generating'
const PUBLISHING_STALE_MINUTES = 3
const isPublishingStale = (row: any) => {
  if (row?.publish_status !== 'publishing') return false
  const updatedAt = row.updated_at || row.created_at
  if (!updatedAt) return true
  const time = new Date(updatedAt).getTime()
  if (Number.isNaN(time)) return false
  return Date.now() - time > PUBLISHING_STALE_MINUTES * 60 * 1000
}
const isPublishActionDisabled = (row: any) => row.publish_status === 'publishing' && !isPublishingStale(row)
const getPublishActionText = (row: any) => isPublishingStale(row) ? '重新发布' : '去发布'
const hasGeneratedContent = (row: any) => {
  return !!row?.title && !!row?.content && !String(row.title).includes('创作中') && !String(row.content).includes('正在努力写作')
}
const isGenerated = (row: any) => {
  return ['completed', 'scheduled', 'published', 'publishing'].includes(row.publish_status) ||
    (row.publish_status === 'failed' && hasGeneratedContent(row))
}

// 数据加载
const loadProjects = async () => {
  try {
    const res: any = await geoKeywordApi.getProjects()
    projects.value = Array.isArray(res) ? res : (res?.data || [])
  } catch (error) { console.error(error) }
}

const onProjectChange = async () => {
  generateForm.value.keywordId = null
  keywords.value = []
  if (generateForm.value.projectId) {
    try {
      const res: any = await geoKeywordApi.getProjectKeywords(generateForm.value.projectId)
      keywords.value = Array.isArray(res) ? res : (res?.data || [])
    } catch (error) { console.error(error) }
  }
}

const loadArticles = async () => {
  articlesLoading.value = true
  try {
    const params: { limit: number; project_id?: number; publish_status?: string } = { limit: 100 }
    if (filterProjectId.value) {
      params.project_id = filterProjectId.value
    }
    if (filterPublishStatus.value) {
      params.publish_status = filterPublishStatus.value
    }

    const res: any = await geoArticleApi.getArticles(params)
    articles.value = Array.isArray(res) ? res : (res?.data || [])

    // 加载所有项目用于过滤
    if (projects.value.length === 0) {
      await loadProjects()
    }
  } catch (error) {
    console.error('加载文章失败:', error)
  } finally {
    articlesLoading.value = false
  }
}

const normalizeListResponse = (res: any) => {
  if (Array.isArray(res)) return res
  if (Array.isArray(res?.data)) return res.data
  if (Array.isArray(res?.data?.items)) return res.data.items
  if (Array.isArray(res?.items)) return res.items
  return []
}

const loadAccounts = async () => {
  accountsLoading.value = true
  try {
    const res: any = await accountApi.getList({ status: 1 })
    accounts.value = normalizeListResponse(res)
  } catch (error) {
    console.error('加载账号失败:', error)
  } finally {
    accountsLoading.value = false
  }
}

// 操作
const generateArticle = async () => {
  if (!generateForm.value.keywordId) return
  if (generateForm.value.publishStrategy === 'scheduled' && !generateForm.value.scheduledAt) {
    ElMessage.warning('请选择发布时间')
    return
  }
  if (
    generateForm.value.publishStrategy === 'scheduled' &&
    generateForm.value.scheduledAt &&
    isPastScheduleTime(generateForm.value.scheduledAt)
  ) {
    ElMessage.warning('定时发布时间必须晚于当前时间')
    return
  }
  const project = projects.value.find(p => p.id === generateForm.value.projectId)

  generating.value = true
  try {
    const res = await geoArticleApi.generate({
      keyword_id: generateForm.value.keywordId as number,
      company_name: project?.company_name || '默认公司',
      // 新增：发布策略相关参数
      target_platforms: generateForm.value.targetPlatforms,
      publish_strategy: generateForm.value.publishStrategy,
      scheduled_at: generateForm.value.publishStrategy === 'scheduled' ? generateForm.value.scheduledAt : undefined
    })
    if (res.success) {
      const strategyText = {
        draft: '仅生成草稿',
        immediate: '立即发布',
        scheduled: '定时发布'
      }
      ElMessage.success(`任务提交成功，策略：${strategyText[generateForm.value.publishStrategy]}`)
      // 立即刷新列表以显示 generating 状态
      await loadArticles()

      // 启动轮询等待生成完成
      pollArticleGeneration()
    }
  } finally { generating.value = false }
}

const stopBulkPolling = () => {
  if (bulkPollTimer) {
    clearTimeout(bulkPollTimer)
    bulkPollTimer = null
  }
}

const pollProjectGeneration = (projectId: number, queuedCount: number) => {
  stopBulkPolling()
  let pollCount = 0
  const maxPolls = Math.max(60, queuedCount * 60)

  const poll = async () => {
    pollCount++
    await loadArticles()

    const projectArticles = articles.value.filter(a => a.project_id === projectId)
    const activeCount = projectArticles.filter(a => ['generating', 'publishing'].includes(a.publish_status)).length
    const finishedCount = projectArticles.filter(a => ['completed', 'scheduled', 'published', 'failed'].includes(a.publish_status)).length

    if (activeCount > 0) {
      bulkQueueHint.value = `队列执行中：${activeCount} 篇处理中，已生成/结束 ${finishedCount} 篇`
    }

    if (pollCount >= maxPolls || (pollCount > 5 && activeCount === 0)) {
      bulkGenerating.value = false
      bulkQueueHint.value = activeCount === 0
        ? `本轮队列已暂无处理中任务，已提交 ${queuedCount} 个搜索问题`
        : '队列仍在后台执行，可稍后刷新列表查看'
      stopBulkPolling()
      return
    }

    bulkPollTimer = setTimeout(poll, 4000)
  }

  bulkPollTimer = setTimeout(poll, 1200)
}

const generateProjectArticles = async () => {
  if (!generateForm.value.projectId || bulkGenerating.value) return
  if (generateForm.value.publishStrategy === 'scheduled' && !generateForm.value.scheduledAt) {
    ElMessage.warning('请选择发布时间')
    return
  }
  if (
    generateForm.value.publishStrategy === 'scheduled' &&
    generateForm.value.scheduledAt &&
    isPastScheduleTime(generateForm.value.scheduledAt)
  ) {
    ElMessage.warning('定时发布时间必须晚于当前时间')
    return
  }

  bulkGenerating.value = true
  bulkQueueHint.value = '正在提交项目文章生成队列...'
  try {
    const res: any = await geoArticleApi.generateProject({
      project_id: generateForm.value.projectId,
      target_platforms: generateForm.value.targetPlatforms,
      publish_strategy: generateForm.value.publishStrategy,
      scheduled_at: generateForm.value.publishStrategy === 'scheduled' ? generateForm.value.scheduledAt : undefined
    })
    const queuedCount = Number(res?.data?.queued_count || 0)
    if (res.success && queuedCount > 0) {
      ElMessage.success(res.message || `已加入队列，将按顺序生成 ${queuedCount} 篇文章`)
      bulkQueueHint.value = `已加入队列：${queuedCount} 个搜索问题将逐个生成`
      filterProjectId.value = generateForm.value.projectId
      await loadArticles()
      pollProjectGeneration(generateForm.value.projectId, queuedCount)
    } else {
      bulkGenerating.value = false
      bulkQueueHint.value = res.message || '当前项目没有待生成文章的搜索问题'
      ElMessage.info(bulkQueueHint.value)
    }
  } catch (error) {
    console.error('项目批量生成提交失败:', error)
    bulkGenerating.value = false
    bulkQueueHint.value = ''
    ElMessage.error((error as any)?.message || '项目批量生成提交失败')
  }
}

// 轮询文章生成状态
const pollArticleGeneration = async () => {
  let pollCount = 0
  const maxPolls = 30 // 最多轮询 5 分钟

  const poll = async () => {
    if (pollCount >= maxPolls) {
      console.log('轮询超时，停止')
      return
    }

    pollCount++
    await loadArticles()

    // 检查是否有刚刚生成的文章变为 completed 状态
    const updatedArticle = articles.value.find(a => a.keyword_id === generateForm.value.keywordId)
    if (updatedArticle && ['completed', 'scheduled'].includes(updatedArticle.publish_status)) {
      console.log('文章生成完成')
      ElMessage.success(updatedArticle.publish_status === 'scheduled' ? '文章生成完成，已配置定时发布' : '文章生成完成')
      return
    }

    // 如果文章状态为 failed，也停止
    if (updatedArticle && updatedArticle.publish_status === 'failed') {
      const failedText = hasGeneratedContent(updatedArticle) ? '发布失败' : '文章生成失败'
      console.log(failedText)
      ElMessage.error(updatedArticle.error_msg || failedText)
      return
    }

    // 1 秒后继续轮询
    setTimeout(poll, 2000)
  }

  await poll()
}

const handleCheckQuality = async (row: any) => {
  try {
    const res = await geoArticleApi.checkQuality(row.id)
    if (res.success) {
      ElMessage.success('质检评分已更新')
      await loadArticles()
    }
  } catch (e) { console.error(e) }
}

const deleteSelectedArticles = async () => {
  if (selectedArticleIds.value.length === 0 || batchDeleting.value) return
  const ids = [...selectedArticleIds.value]
  try {
    await ElMessageBox.confirm(
      `确定删除选中的 ${ids.length} 篇文章吗？此操作不可恢复。`,
      '批量删除',
      { type: 'warning' }
    )
    batchDeleting.value = true
    for (const id of ids) {
      await geoArticleApi.delete(id)
    }
    selectedArticleIds.value = []
    ElMessage.success(`已删除 ${ids.length} 篇文章`)
    await loadArticles()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      console.error('批量删除文章失败:', error)
      ElMessage.error('批量删除失败')
    }
  } finally {
    batchDeleting.value = false
  }
}

const previewArticle = (article: any) => {
  currentArticle.value = article
  showPreviewDialog.value = true
}

// 编辑文章：列表数据已含完整 content，直接基于行数据编辑
const openEditDialog = (article: any) => {
  editArticle.value = article
  editForm.value = {
    title: article.title || '',
    content: article.content || ''
  }
  showEditDialog.value = true
}

const saveEdit = async () => {
  if (!editArticle.value) return
  if (!editForm.value.title.trim()) {
    ElMessage.warning('请输入文章标题')
    return
  }
  if (!editForm.value.content.trim()) {
    ElMessage.warning('请输入文章正文')
    return
  }

  savingEdit.value = true
  try {
    const res: any = await geoArticleApi.update(editArticle.value.id, {
      title: editForm.value.title,
      content: editForm.value.content
    })
    if (res.success) {
      ElMessage.success('文章已保存')
      showEditDialog.value = false
      await loadArticles()
    } else {
      ElMessage.error(res.message || '保存失败')
    }
  } catch (error) {
    console.error('保存文章失败:', error)
    ElMessage.error('保存失败')
  } finally {
    savingEdit.value = false
  }
}

const getDefaultPlatform = (article: any) => {
  if (article.platform) return article.platform
  if (Array.isArray(article.target_platforms) && article.target_platforms.length > 0) {
    return article.target_platforms[0]
  }
  if (generateForm.value.targetPlatforms[0]) return generateForm.value.targetPlatforms[0]
  const firstAvailableAccount = accounts.value.find(account => Number(account.status) === 1)
  return firstAvailableAccount?.platform || PLATFORM_OPTIONS[0]?.value || ''
}

const openPublishDialog = async (article: any) => {
  publishArticle.value = article
  if (accounts.value.length === 0) {
    await loadAccounts()
  }
  const platform = getDefaultPlatform(article)
  publishForm.value = {
    mode: article.publish_status === 'scheduled' ? 'scheduled' : 'immediate',
    platform,
    accountId: pickAccountForPlatform(platform, article.account_id),
    scheduledTime: article.publish_status === 'scheduled' ? defaultScheduleTime() : ''
  }
  showPublishDialog.value = true
}

const onPublishPlatformChange = () => {
  publishForm.value.accountId = pickAccountForPlatform(publishForm.value.platform)
}

const submitPublish = async () => {
  if (submittingPublish.value) return
  if (!publishArticle.value) return
  if (!publishForm.value.platform) {
    ElMessage.warning('请选择发布平台')
    return
  }
  if (!publishForm.value.accountId) {
    ElMessage.warning('请选择发布账号')
    return
  }
  if (publishForm.value.mode === 'scheduled' && !publishForm.value.scheduledTime) {
    ElMessage.warning('请选择发布时间')
    return
  }
  if (
    publishForm.value.mode === 'scheduled' &&
    publishForm.value.scheduledTime &&
    isPastScheduleTime(publishForm.value.scheduledTime)
  ) {
    ElMessage.warning('定时发布时间必须晚于当前时间')
    return
  }

  const accountId = publishForm.value.accountId
  if (!accountId) return
  const selectedAccount = getAccountById(accountId)
  if (!selectedAccount || selectedAccount.platform !== publishForm.value.platform) {
    publishForm.value.accountId = pickAccountForPlatform(publishForm.value.platform)
    ElMessage.warning('发布账号与发布平台不匹配，已为你切换到当前平台的可用账号')
    return
  }

  submittingPublish.value = true
  try {
    const payload = {
      article_ids: [publishArticle.value.id],
      account_ids: [accountId]
    }
    if (publishForm.value.mode === 'scheduled') {
      await autoPublishApi.create({
        name: `定时发布-${publishArticle.value.title || publishArticle.value.id}`,
        article_ids: payload.article_ids,
        account_ids: payload.account_ids,
        exec_type: 'scheduled',
        scheduled_at: publishForm.value.scheduledTime,
        execution_mode: 'local_client',
      })
      await ensureLocalPublishEngineStarted()
      ElMessage.success('定时发布已配置，将在设定时间由本地客户端自动执行')
    } else {
      await autoPublishApi.create({
        name: `立即发布-${publishArticle.value.title || publishArticle.value.id}`,
        article_ids: payload.article_ids,
        account_ids: payload.account_ids,
        exec_type: 'immediate',
        execution_mode: 'local_client',
      })
      await ensureLocalPublishEngineStarted()
      ElMessage.success('本地发布任务已创建，客户端正在执行')
    }
    showPublishDialog.value = false
    await loadArticles()
  } catch (error) {
    console.error('提交发布失败:', error)
    ElMessage.error((error as any)?.message || '提交发布失败')
  } finally {
    submittingPublish.value = false
  }
}

// 渲染工具
const getGenerateStatusType = (s: string): 'primary' | 'success' | 'warning' | 'info' | 'danger' => {
  const statusMap: Record<string, 'primary' | 'success' | 'warning' | 'info' | 'danger'> = {
    generating: 'warning',     // 生成中
    completed: 'success',      // 已生成/待分发
    scheduled: 'primary',      // 已配置定时发布
    failed: 'danger',          // 生成失败
    publishing: 'primary',     // 发布中
    published: 'success',      // 已发布
    draft: 'info'             // 草稿
  }
  return statusMap[s] || 'info'
}

const isPublishFailure = (article: any) => {
  if (!article || article.publish_status !== 'failed') return false
  if (article.platform || article.account_id) return true
  const message = article.error_msg || ''
  return /发布|授权|Session|账号|频率|平台/.test(message)
}

const getArticleStatusText = (article: any) => {
  if (article?.publish_status === 'failed') {
    return isPublishFailure(article) ? '发布失败' : '生成失败'
  }
  return getGenerateStatusText(article?.publish_status)
}

const getGenerateStatusText = (s: string) => {
  const textMap: Record<string, string> = {
    generating: '生成中',
    completed: '已生成/待分发',
    scheduled: '已配置定时发布',
    failed: '失败',
    publishing: '发布中',
    published: '已发布',
    draft: '草稿'
  }
  return textMap[s] || s
}

const getScoreClass = (s: number) => s >= 80 ? 'text-success' : (s >= 60 ? 'text-warning' : 'text-danger')
const formatDate = (d?: string) => d ? new Date(d).toLocaleString() : '-'

// 快捷时间：N 分钟后
const setQuickTime = (minutes: number) => {
  const d = new Date()
  d.setMinutes(d.getMinutes() + minutes, 0, 0)
  publishForm.value.scheduledTime = formatDateTime(d)
}

// 快捷时间：明天某时某分
const setQuickTomorrow = (hour: number, minute: number) => {
  const d = new Date()
  d.setDate(d.getDate() + 1)
  d.setHours(hour, minute, 0, 0)
  publishForm.value.scheduledTime = formatDateTime(d)
}

const formatDateTime = (d: Date): string => {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:00`
}

// 获取发布策略显示文本
const getStrategyDisplay = (article: any) => {
  if (!article.publish_strategy || article.publish_strategy === 'draft') {
    return '仅草稿'
  }
  if (article.publish_strategy === 'immediate') {
    return '立即发布'
  }
  if (article.publish_strategy === 'scheduled' && article.scheduled_at) {
    const date = new Date(article.scheduled_at)
    return `定时: ${date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}`
  }
  return article.publish_strategy || '未知'
}

const formatPublishFailureMessage = (progressData: any) => {
  const platformName = progressData?.platform_name || progressData?.platform || '平台'
  const rawMessage = String(progressData?.error_msg || '发布失败')
  const waitMatch = rawMessage.match(/请等\s*(\d+)\s*分钟后再试/)
  if (waitMatch) {
    return `${platformName}发布太频繁了，请等 ${waitMatch[1]} 分钟后再试`
  }

  const intervalMatch = rawMessage.match(/距离上次发布仅(\d+)分钟，需要至少(\d+)分钟间隔/)
  if (intervalMatch) {
    const elapsed = Number(intervalMatch[1])
    const interval = Number(intervalMatch[2])
    const waitMinutes = Math.max(1, interval - elapsed)
    return `${platformName}发布太频繁了，请等 ${waitMinutes} 分钟后再试`
  }

  return rawMessage
}

// 发布进度订阅的取消函数：组件卸载时只退订，不关闭全局共享的 WebSocket 连接。
let unsubscribePublishProgress: (() => void) | null = null

onMounted(() => {
  loadProjects()
  loadArticles()

  // 🌟 订阅 WebSocket 发布进度（全局连接由 MainLayout 统一维护）
  const { onPublishProgress } = useWebSocket()

  // 监听发布进度事件，实时更新文章状态
  unsubscribePublishProgress = onPublishProgress((message: any) => {
    const progressData = message?.data || message
    if (progressData.article_id && progressData.publish_status) {
      const articleIndex = articles.value.findIndex(a => a.id === progressData.article_id)
      if (articleIndex !== -1) {
        const oldStatus = articles.value[articleIndex].publish_status
        articles.value[articleIndex].publish_status = progressData.publish_status

        // 如果有 platform_url，也更新
        if (progressData.platform_url) {
          articles.value[articleIndex].platform_url = progressData.platform_url
        }

        // 如果有 error_msg，也更新
        if (progressData.error_msg) {
          articles.value[articleIndex].error_msg = progressData.error_msg
        }

        console.log(`[Articles] 文章状态已同步: article_id=${progressData.article_id}, ${oldStatus} -> ${progressData.publish_status}`)

        // 发布成功时显示提示
        if (progressData.status === 2 && oldStatus !== 'published') {
          const article = articles.value[articleIndex]
          ElMessage.success(`《${article.title?.substring(0, 20)}...》已成功发布`)
        }

        if ((progressData.status === 3 || progressData.publish_status === 'failed') && oldStatus !== 'failed') {
          ElMessage.error(formatPublishFailureMessage(progressData))
        }
      }
    }
  })
})

// 组件卸载时退订 WebSocket 监听（不关闭全局共享连接）
onUnmounted(() => {
  stopBulkPolling()
  unsubscribePublishProgress?.()
  unsubscribePublishProgress = null
})
</script>

<style scoped lang="scss">
/* ==============================================
   Articles Page — Warm Studio
   Uses global design tokens; overrides only
   where page-specific styling is needed.
   ============================================== */

.articles-page {
  padding: 24px 28px;
  min-height: 100%;
  background: transparent;
}

// ---------- Page Hero ----------
.page-hero {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  padding: 28px 32px;
  margin-bottom: 24px;
  background:
    linear-gradient(135deg, rgba(212, 168, 83, 0.06) 0%, transparent 50%),
    var(--surface-raised);
  border: 1px solid var(--border-thin);
  border-radius: var(--radius-lg);
  position: relative;
  overflow: hidden;

  &::after {
    content: '';
    position: absolute;
    top: -60px;
    right: -40px;
    width: 280px;
    height: 280px;
    background: radial-gradient(circle, rgba(212, 168, 83, 0.10) 0%, transparent 70%);
    pointer-events: none;
  }
}

.hero-content {
  position: relative;
  z-index: 1;
}

.hero-badge {
  display: inline-block;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: var(--accent);
  padding: 4px 12px;
  background: var(--accent-soft);
  border: 1px solid rgba(212, 168, 83, 0.18);
  border-radius: 4px;
  margin-bottom: 10px;
}

.hero-title {
  font-family: var(--font-display);
  font-size: 28px;
  font-weight: 700;
  color: var(--text-head);
  margin: 0 0 6px;
  letter-spacing: -0.02em;
  line-height: 1.15;
}

.hero-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 6px;
  flex-wrap: wrap;

  .hero-title {
    margin-bottom: 0;
  }
}

.deprecated-badge {
  display: inline-flex;
  align-items: center;
  padding: 5px 10px;
  color: var(--danger);
  font-size: 12px;
  font-weight: 600;
  line-height: 1;
  background: var(--danger-soft);
  border: 1px solid rgba(210, 74, 60, 0.22);
  border-radius: 999px;
}

.hero-desc {
  font-size: 14px;
  color: var(--text-muted);
  margin: 0;
  line-height: 1.5;
}

.hero-stats {
  display: flex;
  gap: 32px;
  position: relative;
  z-index: 1;
}

.hero-stat {
  text-align: right;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.hero-stat-value {
  font-size: 32px;
  font-weight: 700;
  color: var(--text-head);
  line-height: 1;
  font-family: var(--font-display);
}

.hero-stat-label {
  font-size: 12px;
  color: var(--text-muted);
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

// ---------- Section Cards ----------
.section {
  background: var(--surface-raised);
  border: 1px solid var(--border-thin);
  border-radius: var(--radius-lg);
  padding: 24px 28px;
  margin-bottom: 20px;
  transition: border-color var(--duration-fast) var(--ease-out);

  &:hover {
    border-color: var(--border-soft);
  }

  &.section-list {
    padding-bottom: 20px;
  }
}

.section-title {
  color: var(--text-head);
  margin-bottom: 16px;
  font-size: 16px;
  font-weight: 600;
  letter-spacing: -0.01em;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;

  .section-title {
    margin-bottom: 0;
  }
}

.table-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.filter-label {
  font-size: 13px;
  color: var(--text-muted);
  white-space: nowrap;
}

// ---------- Generate Form ----------
.generate-form {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: flex-end;

  :deep(.el-form-item) {
    margin-bottom: 0;
    margin-right: 8px;
  }

  :deep(.el-form-item__label) {
    color: var(--text-muted);
    font-weight: 500;
    font-size: 13px;
  }
}

// 空状态提示：项目无搜索问题时引导用户去关键词蒸馏
.empty-hint {
  display: block;
  width: 100%;
  margin: 6px 0 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--warning);
}

.generate-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.queue-hint {
  width: 100%;
  margin: 6px 0 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-muted);
}

// ---------- Typography ----------
.text-muted {
  color: var(--text-muted);
  font-size: 13px;
}

.text-success {
  color: var(--success);
  font-weight: 700;
}

.text-warning {
  color: var(--warning);
  font-weight: 700;
}

.text-danger {
  color: var(--danger);
  font-weight: 700;
}

// ---------- Title Cell ----------
.title-cell {
  display: flex;
  align-items: center;

  .title-text {
    flex: 1;
    color: var(--text-body);
    font-weight: 500;
  }
}

// ---------- Preview Scroll ----------
.article-preview-scroll {
  // 高度按视口算，留出弹窗 header + 边距的空间，避免滚动链到 .el-overlay
  max-height: calc(100vh - 200px);
  overflow-y: auto;
  // 关键：内层滚到边界后不再把滚轮事件冒泡到弹窗外层，消除"滚轮没反应"的体感
  overscroll-behavior: contain;
  -webkit-overflow-scrolling: touch;
  padding: 24px;
  background: #f5f0e7;
  color: #2d2418;
  border-radius: var(--radius-md);
  border: 1px solid rgba(180, 160, 130, 0.2);

  .markdown-body {
    line-height: 1.85;
    font-size: 15px;
    color: #2d2418;

    :deep(img) {
      max-width: 100%;
      border-radius: 8px;
      margin: 10px 0;
    }

    :deep(h1), :deep(h2), :deep(h3) {
      font-family: var(--font-display);
      color: #1a1208;
      margin-top: 1.4em;
      margin-bottom: 0.5em;
    }

    :deep(code) {
      background: #e8dfd0;
      padding: 2px 6px;
      border-radius: 4px;
      font-size: 0.9em;
      color: #5c3d1e;
    }

    :deep(pre) {
      background: #2d2418;
      color: #e6dccb;
      padding: 16px 20px;
      border-radius: var(--radius-md);
      overflow-x: auto;

      code {
        background: transparent;
        color: inherit;
      }
    }

    :deep(blockquote) {
      border-left: 3px solid var(--accent);
      padding-left: 16px;
      color: #6b5d48;
      margin: 14px 0;
    }

    :deep(a) {
      color: #b8861e;
      text-decoration: none;
      &:hover { text-decoration: underline; }
    }
  }
}

// ---------- Publish Dialog ----------
.publish-summary {
  padding: 16px 20px;
  margin-bottom: 20px;
  background: var(--surface-base);
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-md);
}

.publish-title {
  color: var(--text-head);
  font-weight: 600;
  font-size: 15px;
  line-height: 1.5;
  margin-bottom: 6px;
}

.publish-form {
  :deep(.el-form-item__label) {
    color: var(--text-muted);
    font-weight: 500;
  }
}

.account-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}

.form-tip {
  color: var(--warning);
  font-size: 12px;
  line-height: 1.5;
  margin-top: 6px;
}

// ==============================================
//   Element Plus Page-Level Overrides
//   (global overrides handle most; these are
//    Articles-page-specific refinements)
// ==============================================

// Table — page-specific refinements
:deep(.el-table) {
  .el-table__header-wrapper th {
    background: rgba(74, 53, 24, 0.04) !important;
    border-bottom: 1px solid var(--border-thin) !important;
    font-size: 11px;
    font-weight: 700;
    color: var(--text-muted);
    letter-spacing: 0.07em;
    text-transform: uppercase;
    padding: 14px 0;
  }

  .el-table__body-wrapper td {
    border-bottom: 1px solid rgba(74, 53, 24, 0.04);
    padding: 14px 0;
    color: var(--text-body);
    font-size: 13px;
  }

  .el-table__row:hover td {
    background: rgba(212, 168, 83, 0.05) !important;
  }
}

// Tags — rounded pill style
:deep(.el-tag) {
  border-radius: 20px;
  font-weight: 500;
  letter-spacing: 0.02em;
  padding: 0 10px;
}

// Generate button — prominent gold
.generate-form :deep(.el-button--primary) {
  font-weight: 600;
  letter-spacing: 0.02em;
  padding: 10px 24px;
  transition: all var(--duration-normal) var(--ease-out);

  &:not(:disabled):hover {
    transform: translateY(-1px);
    box-shadow: 0 6px 24px rgba(212, 168, 83, 0.32);
  }
}

// Refresh button
.section-header :deep(.el-button--primary.is-plain) {
  border-color: var(--border-soft);
  color: var(--text-muted);

  &:hover {
    border-color: var(--accent);
    color: var(--accent);
  }
}

// 发布弹窗 - 快捷时间按钮
.quick-times {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
</style>
