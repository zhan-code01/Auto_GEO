<template>
  <div class="article-management-page">
    <section class="content-panel">
      <div class="content-header">
        <div class="section-identity compact">
          <span class="section-icon"><Document /></span>
          <div>
            <div class="section-kicker">ARTICLE MANAGEMENT</div>
            <h2>文章管理</h2>
            <p>按项目筛选并管理你的文章，支持批量发布与批量删除。</p>
          </div>
        </div>
        <div class="filters">
          <el-select v-model="projectFilter" placeholder="按项目分类" clearable filterable style="width: 180px" @change="handleSearch">
            <el-option
              v-for="project in projects"
              :key="project.id"
              :label="project.name"
              :value="project.id"
            />
          </el-select>
          <el-select v-model="statusFilter" placeholder="状态筛选" clearable style="width: 130px" @change="handleSearch">
            <el-option label="待分发" value="completed" />
            <el-option label="已发布" value="published" />
            <el-option label="失败" value="failed" />
          </el-select>
          <el-button :icon="Refresh" circle title="刷新" @click="handleSearch" />
          <el-button
            type="warning"
            :disabled="selectedArticleIds.length === 0"
            @click="goToBatchPublish"
          >
            <el-icon><Promotion /></el-icon>
            批量发布 {{ selectedArticleIds.length ? `(${selectedArticleIds.length})` : '' }}
          </el-button>
        </div>
      </div>

      <div v-if="selectedArticleIds.length" class="selection-bar has-selection">
        <div>
          <span class="selection-count">{{ selectedArticleIds.length }}</span>
          篇已选择
        </div>
        <el-button type="danger" plain :icon="Delete" @click="batchDeleteArticles">批量删除</el-button>
      </div>

      <el-table
        row-key="id"
        class="studio-table"
        v-loading="articleStore.loading"
        :data="articleStore.articles"
        empty-text="暂无文章"
      >
        <el-table-column width="52" align="center">
          <template #header>
            <el-checkbox :model-value="isCurrentPageAllSelected" :indeterminate="isCurrentPageIndeterminate" :disabled="articleStore.articles.length === 0" @change="toggleSelectAllCurrentPage" />
          </template>
          <template #default="{ row }">
            <el-checkbox :model-value="isArticleSelected(row)" @change="(checked) => toggleArticleSelected(row, checked)" @click.stop />
          </template>
        </el-table-column>
        <el-table-column label="文章标题" min-width="320">
          <template #default="{ row }">
            <div class="article-title-cell">
              <span class="article-icon"><Document /></span>
              <div>
                <strong>{{ row.title || '未命名文章' }}</strong>
                <span>{{ projectName(row.project_id) }}</span>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }"><el-tag round :type="statusType(row)">{{ statusText(row) }}</el-tag></template>
        </el-table-column>
        <el-table-column label="阅读数" width="100">
          <template #default="{ row }"><span class="muted-cell">{{ row.view_count || 0 }}</span></template>
        </el-table-column>
        <el-table-column label="创建时间" width="180">
          <template #default="{ row }"><span class="muted-cell">{{ formatTime(row.created_at) }}</span></template>
        </el-table-column>
        <el-table-column label="操作" width="230" fixed="right" align="right">
          <template #default="{ row }">
            <div class="row-actions">
              <el-button link type="primary" @click="preview(row)"><el-icon><View /></el-icon>预览</el-button>
              <el-button link type="primary" @click="editArticle(row.id)"><el-icon><EditPen /></el-icon>编辑</el-button>
              <el-button
                link
                type="warning"
                :disabled="isPublishActionDisabled(row)"
                @click="openPublishDialog(row)"
              ><el-icon><Promotion /></el-icon>{{ getPublishActionText(row) }}</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-wrap">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :page-sizes="[20, 50]"
          layout="total, sizes, prev, pager, next"
          :total="articleStore.pagination.total"
          @current-change="handlePageChange"
          @size-change="handlePageSizeChange"
        />
      </div>
    </section>

    <el-dialog v-model="previewVisible" title="文章预览" width="800px">
      <h2>{{ previewArticle?.title }}</h2>
      <div class="preview-body" v-html="renderPreview(previewArticle?.content || '', previewArticle?.title || '')" />
    </el-dialog>

    <el-dialog v-model="showPublishDialog" title="发布文章" width="560px" destroy-on-close>
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
                <el-tag size="small" type="success">可用</el-tag>
              </div>
            </el-option>
          </el-select>
          <div v-if="publishForm.platform && availablePublishAccounts.length === 0" class="publish-form-tip">
            当前平台暂无可用账号，请先在账号管理中完成授权。
          </div>
        </el-form-item>

        <el-form-item v-if="publishForm.mode === 'scheduled'" label="发布时间">
          <el-date-picker
            v-model="publishForm.scheduledTime"
            type="datetime"
            placeholder="选择发布时间"
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
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, type CheckboxValueType } from 'element-plus'
import {
  Delete,
  Document,
  EditPen,
  Promotion,
  Refresh,
  View,
} from '@element-plus/icons-vue'
import MarkdownIt from 'markdown-it'
import { accountApi, autoPublishApi, geoKeywordApi } from '@/services/api'
import { getEnabledPlatforms } from '@/core/config/platform'
import { useArticleStore } from '@/stores/modules/article'
import { defaultScheduleTime, disabledPastDate, disabledPastHours, disabledPastMinutes, isPastScheduleTime } from '@/utils/scheduleTime'

const router = useRouter()
const articleStore = useArticleStore()
const markdown = new MarkdownIt({ html: true, linkify: true })

const statusFilter = ref<string | undefined>(undefined)
const projectFilter = ref<number | undefined>(undefined)
const projects = ref<any[]>([])
const currentPage = ref(1)
const pageSize = ref(20)

// 选中文章（本地维护，与批量删除/批量发布共用）
const selectedArticleIds = ref<number[]>([])
const currentPageArticleIds = computed(() => articleStore.articles.map(item => item.id))
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
  return selectedArticleIds.value.includes(row.id)
}
function toggleArticleSelected(row: any, checked: CheckboxValueType) {
  if (checked === true) {
    if (!selectedArticleIds.value.includes(row.id)) {
      selectedArticleIds.value = [...selectedArticleIds.value, row.id]
    }
  } else {
    selectedArticleIds.value = selectedArticleIds.value.filter(id => id !== row.id)
  }
}
function toggleSelectAllCurrentPage(checked: CheckboxValueType) {
  const currentIds = new Set(currentPageArticleIds.value)
  if (checked === true) {
    const existingIds = new Set(selectedArticleIds.value)
    const addedIds = articleStore.articles.filter(item => !existingIds.has(item.id)).map(item => item.id)
    if (addedIds.length) {
      selectedArticleIds.value = [...selectedArticleIds.value, ...addedIds]
    }
  } else {
    selectedArticleIds.value = selectedArticleIds.value.filter(id => !currentIds.has(id))
  }
}
function clearArticleSelection() {
  selectedArticleIds.value = []
}

// ==================== 发布对话框状态（与智能文章生成模块一致） ====================
const showPublishDialog = ref(false)
const publishArticle = ref<any>(null)
const accounts = ref<any[]>([])
const accountsLoading = ref(false)
const submittingPublish = ref(false)
const previewVisible = ref(false)
const previewArticle = ref<any>(null)

const publishForm = ref({
  mode: 'immediate' as 'immediate' | 'scheduled',
  platform: '',
  accountId: null as number | null,
  scheduledTime: '',
})
const PLATFORM_OPTIONS = getEnabledPlatforms()
  .filter(platform => platform.features?.article)
  .map(platform => ({ label: platform.name, value: platform.id }))

const availablePublishAccounts = computed(() => {
  if (!publishForm.value.platform) return []
  return accounts.value.filter(account =>
    account.platform === publishForm.value.platform && Number(account.status) === 1
  )
})

onMounted(() => {
  fetchArticles()
  loadProjects()
  loadAccounts()
})

const loadProjects = async () => {
  try {
    const res: any = await geoKeywordApi.getProjects()
    projects.value = Array.isArray(res) ? res : (res?.data || [])
  } catch {
    projects.value = []
  }
}

const projectName = (projectId?: number | null) => {
  if (!projectId) return '未关联项目'
  const project = projects.value.find(p => p.id === projectId)
  return project?.name || `项目 #${projectId}`
}

const fetchArticles = () => {
  articleStore.loadArticles({
    page: currentPage.value,
    pageSize: pageSize.value,
    publish_status: statusFilter.value,
    project_id: projectFilter.value,
  })
}

const handleSearch = () => {
  currentPage.value = 1
  clearArticleSelection()
  fetchArticles()
}

const handlePageChange = (page: number) => {
  currentPage.value = page
  fetchArticles()
}

const handlePageSizeChange = () => {
  currentPage.value = 1
  fetchArticles()
}

const goToBatchPublish = () => {
  if (selectedArticleIds.value.length === 0) {
    ElMessage.warning('请先选择要发布的文章')
    return
  }
  router.push({
    path: '/articles/batch-publish',
    query: { ids: selectedArticleIds.value.join(',') },
  })
}

// ==================== 批量删除（保留全选 + 批量删除） ====================
const batchDeleteArticles = async () => {
  const ids = selectedArticleIds.value
  if (ids.length === 0) {
    ElMessage.warning('请先选择要删除的文章')
    return
  }

  try {
    await ElMessageBox.confirm(
      `确定要删除选中的 ${ids.length} 篇文章吗？删除后不可恢复！`,
      '确认批量删除',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger',
      }
    )

    const result = await articleStore.batchDeleteArticles(ids)
    if (result.success) {
      ElMessage.success('批量删除成功')
      clearArticleSelection()
      fetchArticles()
    } else {
      ElMessage.error(result.message || '批量删除失败')
    }
  } catch {
    // 用户取消
  }
}

const editArticle = (id: number) => {
  router.push(`/articles/edit/${id}`)
}

// ==================== 字段映射（与后端 GeoArticle.publish_status 枚举一致） ====================
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
const statusText = (row: any) => {
  const publishStatus = row.publish_status || (row.status === 1 ? 'published' : 'draft')
  return STATUS_TEXT_MAP[publishStatus] || '草稿'
}
const statusType = (row: any) => {
  const publishStatus = row.publish_status || (row.status === 1 ? 'published' : 'draft')
  return STATUS_TYPE_MAP[publishStatus] || 'info'
}
const formatTime = (value?: string | null) => (value ? new Date(value).toLocaleString('zh-CN') : '-')

// ==================== 预览 ====================
const preview = (article: any) => {
  previewArticle.value = article
  previewVisible.value = true
}
const renderPreview = (content: string, title: string) => {
  const rendered = content.trimStart().startsWith('<') ? content : markdown.render(content)
  const leadingH1 = rendered.match(/^\s*<h1\b[^>]*>([\s\S]*?)<\/h1>\s*/i)
  if (!leadingH1) return rendered
  const visibleHeading = leadingH1[1].replace(/<[^>]+>/g, '').replace(/&nbsp;/gi, ' ').trim()
  const normalize = (value: string) => value.replace(/\s+/g, '').toLocaleLowerCase()
  return normalize(visibleHeading) === normalize(title) ? rendered.slice(leadingH1[0].length) : rendered
}

// ==================== 发布逻辑（与智能文章生成模块完全一致） ====================
function normalizeListResponse(res: any) {
  if (Array.isArray(res)) return res
  if (Array.isArray(res?.data)) return res.data
  if (Array.isArray(res?.data?.items)) return res.data.items
  if (Array.isArray(res?.items)) return res.items
  return []
}
async function loadAccounts() {
  accountsLoading.value = true
  try {
    accounts.value = normalizeListResponse(await accountApi.getList({ status: 1 }))
  } catch (error) {
    console.error('加载账号失败:', error)
    accounts.value = []
  } finally {
    accountsLoading.value = false
  }
}
function getAccountById(accountId: number | null) {
  if (!accountId) return null
  return accounts.value.find(account => account.id === accountId) || null
}
function pickAccountForPlatform(platform: string, preferredAccountId?: number | null) {
  const platformAccounts = accounts.value.filter(account =>
    account.platform === platform && Number(account.status) === 1
  )
  if (!platformAccounts.length) return null
  const preferred = preferredAccountId
    ? platformAccounts.find(account => account.id === preferredAccountId)
    : null
  return preferred?.id || platformAccounts[0].id
}
function getDefaultPlatform(article: any) {
  const row = article || {}
  if (row.platform) return row.platform
  if (Array.isArray(row.target_platforms) && row.target_platforms.length > 0) {
    return row.target_platforms[0]
  }
  const firstAvailableAccount = accounts.value.find(account => Number(account.status) === 1)
  return firstAvailableAccount?.platform || PLATFORM_OPTIONS[0]?.value || ''
}
function getElectronServerBaseUrl() {
  const configured = import.meta.env.VITE_API_BASE_URL || ''
  if (!configured || configured.startsWith('/')) return undefined
  return configured.replace(/\/api\/?$/, '').replace(/\/+$/, '')
}
async function ensureLocalPublishEngineStarted() {
  if (!window.electronAPI?.publishEngine?.start) {
    throw new Error('请在 AutoGEO 客户端中执行本地发布')
  }
  const token = localStorage.getItem('autogeo_token') || ''
  if (!token) throw new Error('本地发布需要先登录')
  const result = await window.electronAPI.publishEngine.start(token, getElectronServerBaseUrl(), 2000)
  if (!result?.success) throw new Error(result?.error || '本地发布引擎启动失败')
}
function openPublishDialog(article: any) {
  // 网页端无法拉取浏览器，直接提示使用客户端
  if (!window.electronAPI?.publishEngine?.start) {
    ElMessageBox.alert(
      '发布文章需要启动本地浏览器，请在 AutoGEO 客户端中执行本地发布。',
      '需要桌面客户端',
      { type: 'info', confirmButtonText: '知道了' }
    )
    return
  }
  publishArticle.value = article
  if (accounts.value.length === 0) loadAccounts()
  const row = article || {}
  const platform = getDefaultPlatform(article)
  publishForm.value = {
    mode: article?.publish_status === 'scheduled' ? 'scheduled' : 'immediate',
    platform,
    accountId: pickAccountForPlatform(platform, row.account_id),
    scheduledTime: article?.publish_status === 'scheduled' ? defaultScheduleTime() : '',
  }
  showPublishDialog.value = true
}
function onPublishPlatformChange() {
  publishForm.value.accountId = pickAccountForPlatform(publishForm.value.platform)
}
async function submitPublish() {
  if (submittingPublish.value || !publishArticle.value) return
  if (!publishForm.value.platform) return ElMessage.warning('请选择发布平台')
  if (!publishForm.value.accountId) return ElMessage.warning('请选择发布账号')
  if (publishForm.value.mode === 'scheduled' && !publishForm.value.scheduledTime) {
    return ElMessage.warning('请选择发布时间')
  }
  if (publishForm.value.mode === 'scheduled' && isPastScheduleTime(publishForm.value.scheduledTime)) {
    return ElMessage.warning('定时发布时间必须晚于当前时间')
  }

  const accountId = publishForm.value.accountId
  const selectedAccount = getAccountById(accountId)
  if (!selectedAccount || selectedAccount.platform !== publishForm.value.platform) {
    publishForm.value.accountId = pickAccountForPlatform(publishForm.value.platform)
    return ElMessage.warning('发布账号与发布平台不匹配，已为你切换到当前平台的可用账号')
  }

  submittingPublish.value = true
  try {
    const payload = { article_ids: [publishArticle.value.id], account_ids: [accountId] }
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
    fetchArticles()
  } catch (error) {
    console.error('提交发布失败:', error)
    ElMessage.error((error as any)?.message || '提交发布失败')
  } finally {
    submittingPublish.value = false
  }
}
const PUBLISHING_STALE_MINUTES = 3
function isPublishingStale(article: any) {
  if (!article || article.publish_status !== 'publishing') return false
  const updatedAt = article.updated_at || article.created_at
  if (!updatedAt) return true
  const time = new Date(updatedAt).getTime()
  if (Number.isNaN(time)) return false
  return Date.now() - time > PUBLISHING_STALE_MINUTES * 60 * 1000
}
function isPublishActionDisabled(article: any) {
  return article?.publish_status === 'publishing' && !isPublishingStale(article)
}
function getPublishActionText(article: any) {
  return isPublishingStale(article) ? '重新发布' : '去发布'
}
</script>

<style scoped>
.article-management-page {
  width: 100%;
  max-width: 1560px;
  min-height: 100%;
  margin: 0 auto;
  padding: 30px clamp(20px, 2.6vw, 42px) 52px;
  color: var(--text-body);
}

.content-panel {
  margin-bottom: 24px;
  background: var(--surface-raised);
  border: 1px solid var(--border-soft);
  border-radius: 18px;
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}

.content-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  padding: 25px 28px 22px;
  border-bottom: 1px solid var(--border-thin);
}

.section-identity { display: flex; align-items: flex-start; gap: 15px; }
.section-identity.compact { align-items: center; }
.section-icon {
  display: grid;
  flex: 0 0 auto;
  width: 44px;
  height: 44px;
  place-items: center;
  color: #fff;
  background: linear-gradient(145deg, var(--accent), #df963f);
  border-radius: 13px;
  box-shadow: 0 8px 20px rgba(196, 116, 28, 0.2);
}
.section-icon svg { width: 21px; }
.section-kicker {
  margin: 1px 0 5px;
  color: var(--accent);
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .09em;
}
.section-identity h2 {
  margin: 0;
  color: var(--text-head);
  font-family: var(--font-display);
  font-size: 22px;
  font-weight: 600;
}
.section-identity p { margin: 6px 0 0; color: var(--text-muted); font-size: 13px; line-height: 1.55; }

.filters { display: flex; align-items: center; justify-content: flex-end; gap: 9px; flex-wrap: wrap; }
.filters .el-select { width: 140px; }

.selection-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  margin: 16px 20px;
  padding: 11px 14px;
  color: var(--text-muted);
  background: var(--surface-base);
  border: 1px solid var(--border-thin);
  border-radius: 10px;
  font-size: 12px;
  transition: all var(--duration-fast);
}
.selection-bar.has-selection {
  color: var(--text-body);
  background: var(--accent-soft);
  border-color: rgba(196, 116, 28, 0.2);
}
.selection-count {
  margin-right: 3px;
  color: var(--accent);
  font-family: var(--font-mono);
  font-size: 17px;
  font-weight: 700;
}

.studio-table {
  width: calc(100% - 40px);
  margin: 0 20px;
  --el-table-border-color: var(--border-thin);
  --el-table-header-bg-color: var(--surface-base);
  --el-table-row-hover-bg-color: var(--surface-hover);
}
.studio-table :deep(th.el-table__cell) { height: 44px; color: var(--text-muted); font-size: 11px; font-weight: 600; letter-spacing: .03em; }
.studio-table :deep(td.el-table__cell) { padding: 13px 0; }
.studio-table :deep(.el-table__inner-wrapper::before) { display: none; }
.muted-cell { color: var(--text-muted); font-size: 12px; }
.article-title-cell { display: flex; align-items: center; gap: 12px; padding-right: 16px; }
.article-icon { display: grid; flex: 0 0 auto; width: 36px; height: 36px; place-items: center; color: var(--accent); background: var(--accent-soft); border-radius: 10px; }
.article-icon svg { width: 17px; }
.article-title-cell > div { display: flex; min-width: 0; flex-direction: column; gap: 4px; }
.article-title-cell strong { overflow: hidden; color: var(--text-head); font-size: 13px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.article-title-cell span { color: var(--text-muted); font-size: 11px; }
.row-actions { display: flex; justify-content: flex-end; gap: 1px; }
.row-actions :deep(.el-button.is-link) {
  padding: 4px 5px;
  color: var(--text-muted);
  background: transparent !important;
  border: 0 !important;
  box-shadow: none !important;
}
.row-actions :deep(.el-button.is-link:hover) { color: var(--accent); }
.row-actions :deep(.el-button--warning.is-link) { color: var(--accent); }
.row-actions :deep(.el-button svg) { width: 14px; margin-right: 3px; }
.pagination-wrap { display: flex; justify-content: flex-end; padding: 18px 24px 22px; }

.preview-body { max-height: 65vh; min-width: 0; overflow-x: hidden; overflow-y: auto; color: var(--text-body); line-height: 1.85; }
.preview-body :deep(img) { display: block; width: min(100%, 680px); max-width: 100%; height: auto; max-height: 382px; object-fit: cover; margin: 16px auto; border-radius: 10px; }
.publish-summary { padding: 16px 20px; margin-bottom: 20px; background: var(--surface-base); border: 1px solid var(--border-soft); border-radius: 10px; }
.publish-title { margin-bottom: 6px; color: var(--text-head); font-size: 15px; font-weight: 600; line-height: 1.5; }
.text-muted { color: var(--text-muted); }
.publish-form :deep(.el-form-item__label) { color: var(--text-muted); font-weight: 500; }
.account-option { display: flex; align-items: center; justify-content: space-between; width: 100%; }
.publish-form-tip { margin-top: 6px; color: var(--warning); font-size: 12px; line-height: 1.5; }

@media (max-width: 1100px) {
  .content-header { align-items: flex-start; flex-direction: column; }
  .filters { width: 100%; justify-content: flex-start; }
}

@media (max-width: 760px) {
  .article-management-page { padding: 16px 12px 36px; }
  .content-header { padding: 22px 18px; }
  .filters .el-select { width: calc(50% - 24px); }
  .studio-table { width: calc(100% - 24px); margin: 0 12px; }
  .pagination-wrap { padding: 16px 14px 20px; overflow-x: auto; }
}
</style>
