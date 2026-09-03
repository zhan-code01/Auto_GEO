<template>
  <div class="batch-publish-page">
    <!-- 顶部标题栏 -->
    <div class="page-header">
      <div class="header-left">
        <el-button text @click="goBack">
          <el-icon><ArrowLeft /></el-icon>
          返回
        </el-button>
        <h2>批量发布文章</h2>
      </div>
    </div>

    <!-- 步骤条 -->
    <el-steps :active="currentStep" finish-status="success" class="steps-bar">
      <el-step title="选择文章" description="确认要发布的文章" />
      <el-step title="选择平台" description="选择发布平台和账号" />
      <el-step title="确认发布" description="确认发布配置" />
      <el-step title="进度监控" description="查看发布状态" />
    </el-steps>

    <!-- 步骤内容 -->
    <div class="step-content">
      <!-- 步骤1: 选择文章 -->
      <div v-show="currentStep === 0" class="step-panel">
        <div class="panel-header">
          <h3>已选择的文章 ({{ selectedArticles.length }} 篇)</h3>
          <el-button text type="primary" @click="goBackToList">重新选择</el-button>
        </div>
        <div class="article-list">
          <div v-for="article in selectedArticles" :key="article.id" class="article-card">
            <div class="article-info">
              <span class="article-title">{{ article.title }}</span>
              <el-tag :type="getStatusType(article.publish_status)" size="small">
                {{ getStatusText(article.publish_status) }}
              </el-tag>
            </div>
            <div class="article-meta">
              <span>创建于 {{ formatDate(article.created_at) }}</span>
            </div>
          </div>
        </div>
        <div v-if="selectedArticles.length === 0" class="empty-tip">
          <el-empty description="未选择文章" />
        </div>
      </div>

      <!-- 步骤2: 选择平台 -->
      <div v-show="currentStep === 1" class="step-panel">
        <div class="panel-header">
          <div>
            <h3>选择发布平台</h3>
            <p class="panel-sub">为每篇文章勾选要发布的平台，勾选后可多选该平台下的账号（默认第一个已授权账号）；灰色平台表示尚未登录。</p>
          </div>
        </div>
        <div class="quick-batch">
          <div class="quick-batch-header">
            <span class="quick-batch-title">快速配置：勾选平台并选择账号后一键应用到全部文章</span>
            <el-button
              size="small"
              type="primary"
              :disabled="quickPlatforms.length === 0 || selectedArticles.length === 0"
              @click="applyQuickSelectionToAll"
            >应用到全部文章</el-button>
          </div>
          <div v-if="publishPlatformRows.length" class="quick-batch-platforms">
            <div v-for="p in publishPlatformRows" :key="p.value" class="quick-batch-item">
              <el-checkbox
                :model-value="quickPlatforms.includes(p.value)"
                :disabled="p.accounts.length === 0"
                @update:model-value="(val) => onQuickPlatformToggle(p, val as boolean)"
              >
                <span class="quick-platform-label"><PlatformIcon :platform="p.value" :size="16" /> {{ p.label }}</span>
              </el-checkbox>
              <el-select
                v-if="quickPlatforms.includes(p.value) && p.accounts.length"
                :model-value="quickAccounts[p.value] || []"
                multiple
                collapse-tags
                size="small"
                class="quick-account-select"
                placeholder="选择账号"
                @update:model-value="(val) => setQuickAccounts(p.value, val as number[])"
              >
                <el-option
                  v-for="acc in p.accounts"
                  :key="acc.id"
                  :label="acc.account_name || acc.username || `账号 ${acc.id}`"
                  :value="acc.id"
                />
              </el-select>
            </div>
          </div>
          <div v-else class="form-tip">暂无支持发布的平台</div>
        </div>
        <div v-loading="loadingPlatforms" class="article-list">
          <div v-for="article in selectedArticles" :key="article.id" class="article-card">
            <div class="article-info">
              <span class="article-title">{{ article.title }}</span>
              <el-tag :type="getStatusType(article.publish_status)" size="small">
                {{ getStatusText(article.publish_status) }}
              </el-tag>
            </div>
            <div class="platform-grid">
              <div
                v-for="p in publishPlatformRows"
                :key="p.value"
                class="platform-cell"
                :class="{ disabled: p.accounts.length === 0, checked: isPlatformChecked(article.id, p.value) }"
              >
                <el-checkbox
                  :model-value="isPlatformChecked(article.id, p.value)"
                  :disabled="p.accounts.length === 0"
                  @update:model-value="(val) => onPlatformToggle(article.id, p, val as boolean)"
                >
                  <PlatformIcon :platform="p.value" :size="16" />
                  <span class="platform-name">{{ p.label }}</span>
                </el-checkbox>
                <el-select
                  v-if="isPlatformChecked(article.id, p.value) && p.accounts.length"
                  :model-value="getArticlePlatformAccountIds(article.id, p.value)"
                  multiple
                  collapse-tags
                  size="small"
                  class="account-select"
                  placeholder="选择账号"
                  @update:model-value="(val) => setAccounts(article.id, p.value, val as number[])"
                >
                  <el-option
                    v-for="acc in p.accounts"
                    :key="acc.id"
                    :label="acc.account_name || acc.username || `账号 ${acc.id}`"
                    :value="acc.id"
                  />
                </el-select>
                <span v-else-if="p.accounts.length === 0" class="not-bound">未登录</span>
              </div>
            </div>
          </div>
          <div v-if="!loadingPlatforms && publishPlatformRows.length === 0" class="form-tip">
            暂无支持发布的平台
          </div>
        </div>
        <div class="publish-summary-box">
          <div class="summary-item">
            <span class="label">已选文章：</span>
            <span class="value">{{ selectedArticles.length }} 篇</span>
          </div>
          <div class="summary-item">
            <span class="label">已选平台：</span>
            <span class="value">{{ selectedPlatformIds.length }} 个</span>
          </div>
          <div class="summary-item">
            <span class="label">已选账号：</span>
            <span class="value">{{ selectedAccountIds.length }} 个</span>
          </div>
          <div class="summary-item highlight">
            <span class="label">发布任务：</span>
            <span class="value">{{ publishTargets.length }} 个独立任务</span>
          </div>
        </div>
      </div>

      <!-- 步骤3: 确认发布 -->
      <div v-show="currentStep === 2" class="step-panel">
        <div class="panel-header">
          <h3>确认发布配置</h3>
        </div>
        <el-alert
          title="请核对每篇文章的发布平台与账号，确认无误后点击「开始批量发布」，发布过程将在后台执行"
          type="warning"
          :closable="false"
          show-icon
          style="margin-bottom: 20px"
        />
        <!-- 发布时机选择 -->
        <div class="publish-timing">
          <span class="timing-label">发布时机：</span>
          <el-radio-group v-model="publishTiming">
            <el-radio value="immediate">立即发布</el-radio>
            <el-radio value="scheduled">定时发布</el-radio>
          </el-radio-group>
        </div>
        <div v-if="publishTiming === 'scheduled'" class="scheduled-config">
          <div class="quick-times">
            <span class="quick-label">快捷选择：</span>
            <el-button size="small" @click="setQuickTime(30)">30分钟后</el-button>
            <el-button size="small" @click="setQuickTime(60)">1小时后</el-button>
            <el-button size="small" @click="setQuickTime(120)">2小时后</el-button>
            <el-button size="small" @click="setQuickTomorrow(9, 0)">明天上午9点</el-button>
            <el-button size="small" @click="setQuickTomorrow(20, 0)">明天晚上8点</el-button>
          </div>
          <el-date-picker
            v-model="scheduledTime"
            type="datetime"
            placeholder="或手动选择时间"
            format="YYYY-MM-DD HH:mm"
            value-format="YYYY-MM-DDTHH:mm"
            :disabled-date="disabledPastDate"
            :disabled-hours="disabledPastHours"
            :disabled-minutes="disabledPastMinutes"
            style="width: 100%; margin-top: 8px"
          />
        </div>
        <div class="confirm-list">
          <div v-for="group in groupedTargets" :key="group.articleId" class="confirm-group">
            <div class="confirm-group-title">
              <span class="article-title">{{ group.title }}</span>
              <el-tag size="small" type="info" effect="plain">{{ group.items.length }} 个任务</el-tag>
            </div>
            <div class="confirm-tags">
              <el-tag
                v-for="t in group.items"
                :key="t.account_id"
                class="confirm-tag"
                type="success"
                effect="light"
              >
                <PlatformIcon :platform="getAccountPlatform(t.account_id)" :size="14" />
                <span>{{ getPlatformName(getAccountPlatform(t.account_id)) }} · {{ getAccountNameById(t.account_id) }}</span>
              </el-tag>
            </div>
          </div>
          <div v-if="groupedTargets.length === 0" class="form-tip">
            尚未选择任何发布平台，请返回上一步勾选
          </div>
        </div>
      </div>

      <!-- 步骤4: 进度监控 -->
      <div v-show="currentStep === 3" class="step-panel">
        <div class="panel-header">
          <h3>发布进度</h3>
          <el-tag :type="allCompleted ? 'success' : 'primary'" size="large">
            {{ completedCount }} / {{ totalCount }} 完成
          </el-tag>
        </div>
        <el-progress
          :percentage="progressPercentage"
          :status="allCompleted ? (failedCount > 0 ? 'warning' : 'success') : undefined"
          :stroke-width="20"
          style="margin-bottom: 20px"
        />
        <div class="progress-stats">
          <div class="stat-item success">
            <span class="stat-count">{{ successCount }}</span>
            <span class="stat-label">成功</span>
          </div>
          <div class="stat-item failed">
            <span class="stat-count">{{ failedCount }}</span>
            <span class="stat-label">失败</span>
          </div>
          <div class="stat-item pending">
            <span class="stat-count">{{ pendingCount }}</span>
            <span class="stat-label">待发布</span>
          </div>
        </div>
        <div v-loading="loadingProgress" class="progress-list">
          <div
            v-for="item in progressItems"
            :key="`${item.article_id}-${item.account_id}`"
            class="progress-item"
            :class="getProgressItemClass(item.status)"
          >
            <div class="progress-info">
              <PlatformIcon :platform="item.platform" :size="24" />
              <div class="progress-detail">
                <span class="article-title">{{ item.article_title }}</span>
                <span class="platform-name">{{ item.platform_name }} → {{ item.account_name }}</span>
              </div>
            </div>
            <div class="progress-status">
              <el-tag v-if="item.status === 2" type="success" size="small">成功</el-tag>
              <el-tag v-else-if="item.status === 3" type="danger" size="small">失败</el-tag>
              <el-tag v-else type="info" size="small">待发布</el-tag>
              <a
                v-if="item.platform_url"
                :href="item.platform_url"
                target="_blank"
                class="view-link"
              >查看</a>
              <el-tooltip v-if="item.error_msg" :content="item.error_msg" placement="top">
                <el-icon class="error-icon"><Warning /></el-icon>
              </el-tooltip>
            </div>
          </div>
        </div>
        <div v-if="allCompleted" class="completed-tip">
          <el-alert
            :title="failedCount > 0 ? `批量发布完成，${failedCount} 个任务失败` : '所有发布任务已完成！'"
            :type="failedCount > 0 ? 'warning' : 'success'"
            :closable="false"
            show-icon
          />
        </div>
      </div>
    </div>

    <!-- 底部操作栏 -->
    <div class="action-bar">
      <el-button v-if="currentStep > 0 && currentStep < 3" @click="prevStep">上一步</el-button>
      <el-button v-if="currentStep < 2" type="primary" :disabled="!canNext" @click="nextStep">
        下一步
      </el-button>
      <el-button
        v-if="currentStep === 2"
        type="warning"
        :loading="submitting"
        :disabled="publishTargets.length === 0"
        @click="startPublish"
      >
        开始批量发布
      </el-button>
      <el-button v-if="currentStep === 3 && !allCompleted" type="primary" @click="refreshProgress">
        刷新进度
      </el-button>
      <el-button v-if="currentStep === 3" @click="goBackToList">返回列表</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Warning } from '@element-plus/icons-vue'
import { get, publishApi, accountApi, autoPublishApi } from '@/services/api'
import { IMPLEMENTED_PLATFORM_IDS } from '@/core/config/platform'
import PlatformIcon from '@/components/business/account/PlatformIcon.vue'
import { defaultScheduleTime, disabledPastDate, disabledPastHours, disabledPastMinutes, isPastScheduleTime } from '@/utils/scheduleTime'

const router = useRouter()
const route = useRoute()

// 步骤控制
const currentStep = ref(0)

// 文章数据
const selectedArticles = ref<any[]>([])
const articleIds = ref<number[]>([])

// 平台和账号数据
const publishPlatforms = ref<any[]>([])
const accounts = ref<any[]>([])
const loadingPlatforms = ref(false)
const articlePlatformAccountIds = ref<Record<string, number[]>>({})

// 步骤2 全局快速配置：勾选平台并选择账号后一键应用到全部已选文章
const quickPlatforms = ref<string[]>([])
const quickAccounts = ref<Record<string, number[]>>({})

// 发布控制
const submitting = ref(false)
const taskId = ref<number | null>(null)

// 发布时机：立即发布 / 定时发布
const publishTiming = ref<'immediate' | 'scheduled'>('immediate')
const scheduledTime = ref<string>('')

const onPublishTimingChange = (value: string | number | boolean | undefined) => {
  if (value === 'scheduled') {
    scheduledTime.value = defaultScheduleTime()
  }
}

// 快捷时间：N 分钟后
const setQuickTime = (minutes: number) => {
  const d = new Date()
  d.setMinutes(d.getMinutes() + minutes, 0, 0)
  scheduledTime.value = formatDateTime(d)
}

// 快捷时间：明天某时某分
const setQuickTomorrow = (hour: number, minute: number) => {
  const d = new Date()
  d.setDate(d.getDate() + 1)
  d.setHours(hour, minute, 0, 0)
  scheduledTime.value = formatDateTime(d)
}

const formatDateTime = (d: Date): string => {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:00`
}

// 进度控制
const progressItems = ref<any[]>([])
const loadingProgress = ref(false)
let progressTimer: number | null = null

// 计算属性
const publishPlatformRows = computed(() => {
  return publishPlatforms.value.map((p) => {
    const platformAccounts = accounts.value.filter(
      (account) => account.platform === p.value && Number(account.status) === 1 && Boolean(account.is_authorized)
    )
    return {
      value: p.value,
      label: p.label,
      accounts: platformAccounts,
    }
  })
})

const publishTargets = computed(() => Object.entries(articlePlatformAccountIds.value).flatMap(([key, accountIds]) => {
  const [articleId] = key.split(':').map(Number)
  return accountIds.map(accountId => ({ article_id: articleId, account_id: accountId }))
}))
const selectedPlatformIds = computed(() => [...new Set(publishTargets.value.map(target => accounts.value.find(a => a.id === target.account_id)?.platform).filter(Boolean))])
const selectedAccountIds = computed(() => [...new Set(publishTargets.value.map(target => target.account_id))])

const canNext = computed(() => {
  if (currentStep.value === 0) {
    return selectedArticles.value.length > 0
  }
  if (currentStep.value === 1) {
    return publishTargets.value.length > 0
  }
  return true
})

const totalCount = computed(() => publishTargets.value.length)

const completedCount = computed(() => {
  return progressItems.value.filter(item => item.status === 2 || item.status === 3).length
})

const successCount = computed(() => {
  return progressItems.value.filter(item => item.status === 2).length
})

const failedCount = computed(() => {
  return progressItems.value.filter(item => item.status === 3).length
})

const pendingCount = computed(() => {
  return progressItems.value.filter(item => item.status === 0 || item.status === 1).length
})

const progressPercentage = computed(() => {
  if (totalCount.value === 0) return 0
  return Math.round((completedCount.value / totalCount.value) * 100)
})

const allCompleted = computed(() => {
  return completedCount.value > 0 && completedCount.value === totalCount.value
})

// 方法
const loadSelectedArticles = async () => {
  // 从 URL query 获取文章 ID
  const idsParam = route.query.ids as string
  if (idsParam) {
    articleIds.value = idsParam.split(',').map(Number).filter(Boolean)
  }
  // 如果没有传入 ID，从 store 获取（如果用户从列表页导航过来）
  if (articleIds.value.length === 0) {
    ElMessage.warning('未选择文章')
    goBackToList()
    return
  }

  // 先以占位标题渲染，保证页面立即可见
  selectedArticles.value = articleIds.value.map(id => ({
    id,
    title: `文章 #${id}`,
    publish_status: 'draft',
    created_at: new Date().toISOString()
  }))

  // 优先使用列表页可能写入的缓存（完整标题/状态/时间）
  const storedArticles = sessionStorage.getItem('batch_publish_articles')
  if (storedArticles) {
    try {
      const parsed = JSON.parse(storedArticles)
      const matched = parsed.filter((a: any) => articleIds.value.includes(a.id))
      if (matched.length) {
        const cacheMap = new Map<number, any>()
        matched.forEach((a: any) => cacheMap.set(a.id, a))
        selectedArticles.value = selectedArticles.value.map(a => {
          const cached = cacheMap.get(a.id)
          return cached ? { ...a, ...cached } : a
        })
      }
    } catch (e) {
      console.error('解析文章数据失败', e)
    }
  }

  // 兜底：若仍有标题是占位符，按 id 从后端拉取真实标题/状态，避免界面只显示"文章 #xxx"
  await fetchMissingArticleDetails()
}

// 按 id 从后端补全文章真实信息（标题/发布状态/创建时间），仅补全仍为占位符的条目
const fetchMissingArticleDetails = async () => {
  const needFetchIds = selectedArticles.value
    .filter(a => a.title === `文章 #${a.id}`)
    .map(a => a.id)
  if (needFetchIds.length === 0) return

  const results = await Promise.all(
    needFetchIds.map(async (id) => {
      try {
        const data: any = await get(`/articles/${id}`, undefined, { silent: true })
        const detail = data?.data || data
        if (detail && detail.id !== undefined) return detail
      } catch (e) {
        console.warn('获取文章详情失败', id, e)
      }
      return null
    })
  )

  const detailMap = new Map(results.filter(Boolean).map((d: any) => [d.id, d]))
  if (detailMap.size === 0) return

  selectedArticles.value = selectedArticles.value.map(a =>
    detailMap.has(a.id)
      ? {
          ...a,
          title: detailMap.get(a.id).title || a.title,
          publish_status: detailMap.get(a.id).publish_status || a.publish_status,
          created_at: detailMap.get(a.id).created_at || a.created_at,
        }
      : a
  )
}

const loadPublishPlatforms = async () => {
  loadingPlatforms.value = true
  try {
    const res: any = await publishApi.getPlatforms()
    const platforms = Array.isArray(res?.data?.platforms) ? res.data.platforms : []
    publishPlatforms.value = platforms
      .filter(
        (platform: any) =>
          platform.publish_supported && IMPLEMENTED_PLATFORM_IDS.includes(platform.id)
      )
      .map((platform: any) => ({
        label: platform.name || platform.id,
        value: platform.id,
      }))
  } catch (error) {
    console.error('加载发布平台失败:', error)
    publishPlatforms.value = []
  } finally {
    loadingPlatforms.value = false
  }
}

const loadAccounts = async () => {
  try {
    const res: any = await accountApi.getList({ status: 1, limit: 100 })
    accounts.value = normalizeListResponse(res)
  } catch (error) {
    console.error('加载账号失败:', error)
    accounts.value = []
  }
}

const normalizeListResponse = (res: any) => {
  if (Array.isArray(res)) return res
  if (Array.isArray(res?.data)) return res.data
  if (Array.isArray(res?.data?.items)) return res.data.items
  if (Array.isArray(res?.items)) return res.items
  return []
}

const articlePlatformKey = (articleId: number, platform: string) => `${articleId}:${platform}`
const getArticlePlatformAccountIds = (articleId: number, platform: string) =>
  articlePlatformAccountIds.value[articlePlatformKey(articleId, platform)] || []
const setArticlePlatformAccountIds = (articleId: number, platform: string, accountIds: number[]) => {
  articlePlatformAccountIds.value = {
    ...articlePlatformAccountIds.value,
    [articlePlatformKey(articleId, platform)]: accountIds.map(Number),
  }
}

// 步骤2：以「平台」为复选单位（而非逐账号复选），勾选即发布到该平台（默认第一个授权账号）
const isPlatformChecked = (articleId: number, platform: string) =>
  getArticlePlatformAccountIds(articleId, platform).length > 0

const onPlatformToggle = (articleId: number, platform: any, checked: boolean) => {
  if (!checked) {
    setArticlePlatformAccountIds(articleId, platform.value, [])
    return
  }
  const platformAccounts = accounts.value.filter(
    (a) => a.platform === platform.value && Number(a.status) === 1 && Boolean(a.is_authorized)
  )
  if (platformAccounts.length === 0) return
  setArticlePlatformAccountIds(articleId, platform.value, [Number(platformAccounts[0].id)])
}

const setAccounts = (articleId: number, platform: string, accountIds: number[]) => {
  setArticlePlatformAccountIds(articleId, platform, accountIds.map(Number))
}

// 步骤2 便捷操作：顶部快速配置 —— 勾选平台并选择账号后，批量应用到全部已选文章
const onQuickPlatformToggle = (platform: any, checked: boolean) => {
  if (!checked) {
    quickPlatforms.value = quickPlatforms.value.filter(v => v !== platform.value)
    const next = { ...quickAccounts.value }
    delete next[platform.value]
    quickAccounts.value = next
    return
  }
  if (!quickPlatforms.value.includes(platform.value)) {
    quickPlatforms.value = [...quickPlatforms.value, platform.value]
  }
  if (!(quickAccounts.value[platform.value]?.length)) {
    const platformAccounts = accounts.value.filter(
      (a) => a.platform === platform.value && Number(a.status) === 1 && Boolean(a.is_authorized)
    )
    if (platformAccounts.length) {
      quickAccounts.value = { ...quickAccounts.value, [platform.value]: [Number(platformAccounts[0].id)] }
    }
  }
}

const setQuickAccounts = (platform: string, accountIds: number[]) => {
  quickAccounts.value = { ...quickAccounts.value, [platform]: accountIds.map(Number) }
}

const applyQuickSelectionToAll = () => {
  if (quickPlatforms.value.length === 0) return
  const next = { ...articlePlatformAccountIds.value }
  for (const article of selectedArticles.value) {
    for (const platform of quickPlatforms.value) {
      const selectedAccounts = quickAccounts.value[platform] || []
      if (selectedAccounts.length === 0) continue
      const key = articlePlatformKey(article.id, platform)
      const existing = next[key] || []
      next[key] = [...new Set([...existing, ...selectedAccounts.map(Number)])]
    }
  }
  articlePlatformAccountIds.value = next
  ElMessage.success(`已为 ${selectedArticles.value.length} 篇文章应用所选平台`)
}

const getPlatformName = (platformId: string) => {
  const platform = publishPlatforms.value.find(p => p.value === platformId)
  return platform?.label || platformId
}

const getAccountNameById = (accountId: number) => {
  const account = accounts.value.find(a => a.id === accountId)
  return account?.account_name || account?.username || `账号 ${accountId}`
}
const getArticleTitle = (articleId: number) => selectedArticles.value.find(article => article.id === articleId)?.title || `文章 #${articleId}`

// 步骤3：把扁平的发布目标按文章分组，方便逐篇核对标题与平台账号
const groupedTargets = computed(() => {
  const map = new Map<number, { articleId: number; title: string; items: any[] }>()
  for (const t of publishTargets.value) {
    if (!map.has(t.article_id)) {
      const article = selectedArticles.value.find(a => a.id === t.article_id)
      map.set(t.article_id, {
        articleId: t.article_id,
        title: article?.title || `文章 #${t.article_id}`,
        items: [],
      })
    }
    map.get(t.article_id)!.items.push(t)
  }
  return [...map.values()]
})

const getAccountPlatform = (accountId: number) =>
  accounts.value.find(a => a.id === accountId)?.platform || ''

// 业务状态只展示三类：待分发、已发布、失败。其他中间态统一归为待分发。
const STATUS_TEXT_MAP: Record<string, string> = {
  draft: '待分发',
  generating: '待分发',
  completed: '待分发',
  scheduled: '待分发',
  publishing: '待分发',
  published: '已发布',
  failed: '失败',
}
const STATUS_TYPE_MAP: Record<string, any> = {
  draft: 'warning',
  generating: 'warning',
  completed: 'warning',
  scheduled: 'warning',
  publishing: 'warning',
  published: 'success',
  failed: 'danger',
}

const getStatusType = (status: string) => STATUS_TYPE_MAP[status] || 'info'
const getStatusText = (status: string) => STATUS_TEXT_MAP[status] || '草稿'

const getProgressItemClass = (status: number) => {
  if (status === 2) return 'success'
  if (status === 3) return 'failed'
  return 'pending'
}

const formatDate = (dateStr: string) => {
  const date = new Date(dateStr)
  return date.toLocaleDateString('zh-CN')
}

const goBack = () => {
  router.back()
}

const goBackToList = () => {
  router.push('/articles')
}

const nextStep = () => {
  if (currentStep.value < 2) {
    currentStep.value++
  }
}

const prevStep = () => {
  if (currentStep.value > 0) {
    currentStep.value--
  }
}

const startPublish = async () => {
  if (submitting.value) return
  if (publishTargets.value.length === 0) {
    ElMessage.warning('请选择至少一个发布平台和账号')
    return
  }

  submitting.value = true
  try {
    if (publishTiming.value === 'scheduled' && !scheduledTime.value) {
      ElMessage.warning('请选择定时发布的时间')
      submitting.value = false
      return
    }
    if (publishTiming.value === 'scheduled' && isPastScheduleTime(scheduledTime.value)) {
      ElMessage.warning('定时发布时间必须晚于当前时间')
      submitting.value = false
      return
    }

    const res: any = await autoPublishApi.create({
      name: `批量发布-${new Date().toLocaleString('zh-CN')}`,
      article_ids: articleIds.value,
      account_ids: selectedAccountIds.value,
      targets: publishTargets.value,
      exec_type: publishTiming.value,
      execution_mode: 'local_client',
      ...(publishTiming.value === 'scheduled' ? { scheduled_at: scheduledTime.value } : {}),
    })

    if (res.success !== false) {
      taskId.value = res.data?.task_id
      await ensureLocalPublishEngineStarted()
      ElMessage.success(
        publishTiming.value === 'scheduled'
          ? '定时发布任务已创建，将在设定时间由本地客户端自动执行'
          : '批量发布任务已创建，本地客户端将逐条执行'
      )
      currentStep.value = 3

      // 初始化进度项
      initProgressItems()

      // 开始轮询进度
      startProgressPolling()
    } else {
      ElMessage.error(res.message || '启动发布失败')
    }
  } catch (error: any) {
    console.error('启动批量发布失败:', error)
    ElMessage.error(error?.response?.data?.detail || '启动发布失败')
  } finally {
    submitting.value = false
  }
}

const initProgressItems = () => {
  progressItems.value = publishTargets.value.map(target => {
    const account = accounts.value.find(item => item.id === target.account_id)
    return {
      ...target,
      article_title: getArticleTitle(target.article_id),
      account_name: getAccountNameById(target.account_id),
      platform: account?.platform || '',
      platform_name: getPlatformName(account?.platform || ''),
      status: 0,
      platform_url: null,
      error_msg: null,
    }
  })
}

const getElectronServerBaseUrl = () => {
  const configured = import.meta.env.VITE_API_BASE_URL || ''
  return !configured || configured.startsWith('/') ? undefined : configured.replace(/\/api\/?$/, '').replace(/\/+$/, '')
}
const ensureLocalPublishEngineStarted = async () => {
  if (!window.electronAPI?.publishEngine?.start) throw new Error('请在 AutoGEO 客户端中执行本地发布')
  const token = localStorage.getItem('autogeo_token') || ''
  if (!token) throw new Error('本地发布需要先登录')
  const result = await window.electronAPI.publishEngine.start(token, getElectronServerBaseUrl(), 2000)
  if (!result?.success) throw new Error(result?.error || '本地发布引擎启动失败')
}

const startProgressPolling = () => {
  if (progressTimer) {
    clearInterval(progressTimer)
  }
  progressTimer = window.setInterval(() => {
    refreshProgress()
  }, 3000)
}

const refreshProgress = async () => {
  if (!taskId.value) return

  loadingProgress.value = true
  try {
    const res: any = await autoPublishApi.getTask(taskId.value)
    if (res?.data?.records) {
      // 更新进度项状态
      for (const item of res.data.records) {
        const progressItem = progressItems.value.find(
          p => p.article_id === item.article_id && p.account_id === item.account_id
        )
        if (progressItem) {
          progressItem.status = item.status === 'success' ? 2 : item.status === 'failed' ? 3 : item.status === 'publishing' ? 1 : 0
          progressItem.platform_url = item.platform_url
          progressItem.error_msg = item.error_msg
        }
      }
    }

    // 检查是否全部完成
    if (allCompleted.value && progressTimer) {
      clearInterval(progressTimer)
      progressTimer = null
    }
  } catch (error) {
    console.error('获取进度失败:', error)
  } finally {
    loadingProgress.value = false
  }
}

// 生命周期
onMounted(async () => {
  loadSelectedArticles()
  await Promise.all([loadPublishPlatforms(), loadAccounts()])
})

onUnmounted(() => {
  if (progressTimer) {
    clearInterval(progressTimer)
  }
  // 清理 sessionStorage
  sessionStorage.removeItem('batch_publish_articles')
})
</script>

<style scoped lang="scss">
.batch-publish-page {
  padding: 20px;
  max-width: 900px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;

  .header-left {
    display: flex;
    align-items: center;
    gap: 12px;

    h2 {
      margin: 0;
      font-size: 20px;
      font-weight: 600;
    }
  }
}

.steps-bar {
  margin-bottom: 30px;
}

.step-content {
  min-height: 400px;
}

.step-panel {
  animation: fadeIn 0.3s ease;
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;

  h3 {
    margin: 0;
    font-size: 16px;
    font-weight: 600;
  }
}

.article-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: 400px;
  overflow-y: auto;
}

.article-card {
  padding: 16px;
  background: var(--bg-secondary);
  border-radius: 8px;
  border: 1px solid var(--border);

  .article-info {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;

    .article-title {
      font-weight: 500;
      color: var(--text-primary);
    }
  }

  .article-meta {
    font-size: 12px;
    color: var(--text-secondary);
  }
}

.strategy-section {
  margin-bottom: 20px;
}

.quick-batch {
  margin-bottom: 20px;
  padding: 16px;
  background: var(--bg-secondary);
  border: 1px solid var(--primary, #409eff);
  border-radius: 8px;

  .quick-batch-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;

    .quick-batch-title {
      font-size: 13px;
      font-weight: 500;
      color: var(--text-primary);
    }
  }

  .quick-batch-platforms {
    display: flex;
    flex-wrap: wrap;
    gap: 8px 20px;

    .quick-batch-item {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    :deep(.el-checkbox) {
      margin-right: 0;
    }

    .quick-platform-label {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      margin-left: 4px;
    }

    .quick-account-select {
      width: 180px;
    }
  }
}

.panel-sub {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.5;
}

.platform-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 14px;
  margin-top: 12px;
  padding-top: 14px;
  border-top: 1px dashed var(--border);

  .platform-cell {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 10px 6px 8px;
    border-radius: 8px;
    background: var(--bg-tertiary, rgba(127, 127, 127, 0.08));
    border: 1px solid transparent;
    transition: all 0.2s ease;

    &.checked {
      background: rgba(64, 158, 255, 0.1);
      border-color: var(--primary, #409eff);
    }

    &.disabled {
      opacity: 0.5;
    }

    :deep(.el-checkbox) {
      margin-right: 0;
      height: auto;
    }

    .platform-name {
      font-size: 13px;
      color: var(--text-primary);
      margin-left: 4px;
    }

    .account-select {
      width: 128px;
    }

    .not-bound {
      font-size: 12px;
      color: var(--color-danger, #f56c6c);
    }
  }
}

.publish-summary-box {
  display: flex;
  gap: 24px;
  padding: 16px;
  background: var(--bg-secondary);
  border-radius: 8px;

  .summary-item {
    .label {
      color: var(--text-secondary);
      font-size: 13px;
    }

    .value {
      font-weight: 600;
      font-size: 16px;
      margin-left: 4px;
    }

    &.highlight .value {
      color: var(--primary);
    }
  }
}

.confirm-list {
  display: flex;
  flex-direction: column;
  gap: 16px;

  .confirm-group {
    padding: 16px;
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 10px;

    .confirm-group-title {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 12px;

      .article-title {
        font-size: 15px;
        font-weight: 600;
        color: var(--text-primary);
      }
    }

    .confirm-tags {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;

      .confirm-tag {
        display: inline-flex;
        align-items: center;
        gap: 4px;
      }
    }
  }
}

.progress-stats {
  display: flex;
  gap: 24px;
  margin-bottom: 20px;

  .stat-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 16px;
    border-radius: 20px;

    .stat-count {
      font-size: 20px;
      font-weight: 700;
    }

    .stat-label {
      font-size: 13px;
    }

    &.success {
      background: rgba(103, 194, 58, 0.1);
      .stat-count { color: #67c23a; }
    }

    &.failed {
      background: rgba(245, 108, 108, 0.1);
      .stat-count { color: #f56c6c; }
    }

    &.pending {
      background: rgba(144, 147, 153, 0.1);
      .stat-count { color: #909399; }
    }
  }
}

.progress-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 350px;
  overflow-y: auto;
  margin-bottom: 20px;

  .progress-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 16px;
    background: var(--bg-secondary);
    border-radius: 8px;
    border-left: 3px solid transparent;

    &.success {
      border-left-color: #67c23a;
    }

    &.failed {
      border-left-color: #f56c6c;
    }

    &.pending {
      border-left-color: #909399;
    }

    .progress-info {
      display: flex;
      align-items: center;
      gap: 12px;

      .progress-detail {
        display: flex;
        flex-direction: column;
        gap: 2px;

        .article-title {
          font-size: 14px;
          font-weight: 500;
          color: var(--text-primary);
        }

        .platform-name {
          font-size: 12px;
          color: var(--text-secondary);
        }
      }
    }

    .progress-status {
      display: flex;
      align-items: center;
      gap: 8px;

      .view-link {
        font-size: 12px;
        color: var(--primary);
        text-decoration: none;

        &:hover {
          text-decoration: underline;
        }
      }

      .error-icon {
        color: #f56c6c;
        cursor: pointer;
      }
    }
  }
}

.completed-tip {
  margin-top: 20px;
}

.empty-tip {
  padding: 60px 0;
}

.action-bar {
  display: flex;
  justify-content: center;
  gap: 12px;
  padding-top: 20px;
  border-top: 1px solid var(--border);
  margin-top: 20px;
}

.form-tip {
  text-align: center;
  padding: 20px;
  color: var(--text-secondary);
}

.publish-timing {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;

  .timing-label {
    font-weight: 500;
    white-space: nowrap;
  }
}

.scheduled-config {
  background: var(--el-fill-color-light, #f5f7fa);
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 16px;

  .quick-times {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;

    .quick-label {
      font-size: 13px;
      color: var(--text-secondary);
      white-space: nowrap;
    }
  }
}
</style>
