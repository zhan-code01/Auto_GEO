<template>
  <div class="smart-articles-page">
    <header class="studio-hero">
      <div class="hero-copy">
        <div class="eyebrow">
          <span class="eyebrow-dot" />
          GEO CONTENT STUDIO
        </div>
        <h1>把用户问题，变成值得发布的内容</h1>
        <p>从真实搜索意图出发，规划问题、生成文章，再一键分发到目标平台。</p>
        <div class="workflow-rail" aria-label="内容生成流程">
          <div class="workflow-step is-active">
            <span class="step-index">01</span>
            <span>规划问题</span>
          </div>
          <span class="workflow-line" />
          <div class="workflow-step">
            <span class="step-index">02</span>
            <span>生成文章</span>
          </div>
          <span class="workflow-line" />
          <div class="workflow-step">
            <span class="step-index">03</span>
            <span>审核发布</span>
          </div>
        </div>
      </div>
      <div class="hero-overview">
        <div class="overview-label">当前工作台</div>
        <div class="overview-grid">
          <div class="overview-item">
            <span class="overview-value">{{ questionTotal }}</span>
            <span class="overview-name">用户问题</span>
          </div>
        </div>
        <div class="draft-note">
          <span class="draft-note-icon"><CircleCheck /></span>
          默认保存为草稿，审核后再发布
        </div>
      </div>
    </header>

    <section class="creation-panel">
      <div class="panel-heading">
        <div class="section-identity">
          <span class="section-icon"><MagicStick /></span>
          <div>
            <div class="section-kicker">STEP 01 · QUESTION PLANNING</div>
            <h2>生成用户问题</h2>
            <p>选定业务场景，让 AI 从用户视角规划更有价值的内容选题。</p>
          </div>
        </div>
        <div class="panel-badge">AI 辅助规划</div>
      </div>

      <el-form class="creation-form" :model="form" label-position="top" @submit.prevent="submitQuestionGeneration">
        <div class="form-grid">
          <el-form-item required>
            <template #label>
              <span class="field-label"><OfficeBuilding />所属公司</span>
            </template>
            <el-select v-model="form.clientId" placeholder="选择要创作内容的公司" filterable clearable style="width: 100%" @change="onClientChange">
              <el-option v-for="client in clients" :key="client.id" :label="client.company_name || client.name" :value="client.id" />
            </el-select>
          </el-form-item>
          <el-form-item required>
            <template #label>
              <span class="field-label"><FolderOpened />关联项目</span>
            </template>
            <el-select v-model="form.projectId" placeholder="选择该公司的项目" filterable clearable :disabled="!form.clientId" style="width: 100%" @change="onProjectChange">
              <el-option v-for="project in projects" :key="project.id" :label="project.name" :value="project.id" />
            </el-select>
            <div v-if="form.clientId && projects.length === 0" class="form-tip warning-tip">该公司暂无有效项目，请先创建或关联项目。</div>
          </el-form-item>
          <el-form-item required>
            <template #label>
              <span class="field-label"><CollectionTag />问题数量</span>
            </template>
            <el-input-number v-model="form.questionCount" :min="1" :max="30" controls-position="right" style="width: 100%" />
            <div class="form-tip">AI 会生成候选问题并筛选优质问题，单次最多生成 30 个。</div>
          </el-form-item>
        </div>

        <div class="creation-footer">
          <div class="creation-hint">
            <span class="hint-orb"><MagicStick /></span>
            <span>{{ `预计生成 ${form.questionCount} 个经过筛选的用户问题` }}</span>
          </div>
          <el-button class="primary-action" type="primary" size="large" :loading="questionGenerating" :disabled="!form.projectId" @click="submitQuestionGeneration">
            <MagicStick />
            生成用户问题
          </el-button>
        </div>
      </el-form>
    </section>

    <section class="content-panel">
      <div class="content-header">
        <div class="section-identity compact">
          <span class="section-icon teal"><CollectionTag /></span>
          <div>
            <div class="section-kicker">STEP 02 · CONTENT QUEUE</div>
            <h2>用户问题池</h2>
            <p>{{ form.projectId ? '选择值得回答的问题，批量生成对应的深度文章。' : '选择公司和项目后，生成的问题会汇集在这里。' }}</p>
          </div>
        </div>
        <div class="filters">
          <el-select v-model="questionFilter" placeholder="全部问题" clearable :disabled="!form.projectId" @change="loadQuestions">
            <el-option label="未生成文章" :value="false" />
            <el-option label="已生成文章" :value="true" />
          </el-select>
          <el-button :icon="Refresh" circle title="刷新问题" :disabled="!form.projectId" @click="loadQuestions" />
          <el-button :icon="Delete" type="danger" plain :disabled="selectedQuestionIds.length === 0" @click="deleteSelectedQuestions">删除</el-button>
          <el-button :icon="Promotion" type="primary" plain @click="goToArticles">前往文章管理</el-button>
        </div>
      </div>
      <div v-if="questionBatch" class="panel-progress">
        <div class="progress-copy">
          <span class="progress-icon"><Clock /></span>
          <div>
            <strong>问题生成进度</strong>
            <span>{{ questionBatch.success_count || 0 }}/{{ questionBatch.requested_count || 0 }} 个问题已保存</span>
          </div>
        </div>
        <el-progress :percentage="questionProgress" :status="questionBatch.status === 'failed' ? 'exception' : undefined" />
        <div v-if="questionBatch.note" class="error-note">{{ questionBatch.note }}</div>
      </div>
      <div v-if="articleBatch" class="panel-progress">
        <div class="progress-copy">
          <span class="progress-icon"><Document /></span>
          <div>
            <strong>文章生成进度</strong>
            <span>{{ articleBatch.success_count || 0 }}/{{ articleBatch.requested_count || 0 }} 篇已完成，{{ articleBatch.failed_count || 0 }} 篇失败</span>
          </div>
        </div>
        <el-progress :percentage="articleProgress" :status="articleBatch.status === 'failed' ? 'exception' : undefined" />
        <div v-if="articleBatch.note" class="error-note">{{ articleBatch.note }}</div>
      </div>
      <div class="selection-bar" :class="{ 'has-selection': selectedQuestionIds.length > 0 }">
        <div>
          <span class="selection-count">{{ selectedQuestionIds.length }}</span>
          <span>条已选择</span>
          <span class="selection-divider">·</span>
          <span>其中 {{ selectableQuestionCount }} 条可生成文章</span>
        </div>
        <el-button type="primary" :disabled="selectableQuestionCount === 0" :loading="articleGenerating" @click="generateSelectedArticles">
          <Document />
          生成 {{ selectableQuestionCount }} 篇文章
        </el-button>
      </div>
      <el-table row-key="id" class="studio-table" v-loading="questionsLoading" :data="questions" :empty-text="form.projectId ? '暂无问题，先在上方生成一些选题吧' : '请先选择公司与项目，用户问题将在这里展示'">
        <el-table-column width="52" align="center">
          <template #header>
            <el-checkbox :model-value="isCurrentPageAllSelected" :indeterminate="isCurrentPageIndeterminate" :disabled="questions.length === 0" @change="toggleSelectAllCurrentPage" />
          </template>
          <template #default="{ row }">
            <el-checkbox :model-value="isQuestionSelected(row)" @change="(checked) => toggleQuestionSelected(row, checked)" @click.stop />
          </template>
        </el-table-column>
        <el-table-column label="用户问题" min-width="420">
          <template #default="{ row }">
            <div class="question-cell">
              <span class="question-mark">Q</span>
              <span class="question-text">{{ row.question }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="问题类型" width="120">
          <template #default="{ row }"><span class="type-chip">{{ intentText(row.intent_type) }}</span></template>
        </el-table-column>
        <el-table-column label="文章状态" width="140">
          <template #default="{ row }"><el-tag round :type="questionStatusType(row)">{{ questionStatusText(row) }}</el-tag></template>
        </el-table-column>
        <el-table-column label="创建时间" width="180"><template #default="{ row }"><span class="muted-cell">{{ formatTime(row.created_at) }}</span></template></el-table-column>
      </el-table>
      <div class="pagination-wrap">
        <el-pagination v-model:current-page="questionPage" v-model:page-size="questionLimit" :page-sizes="[20, 50]" layout="total, sizes, prev, pager, next" :total="questionTotal" @current-change="loadQuestions" @size-change="onQuestionLimitChange" />
      </div>
    </section>

    <!-- 智能文章列表（STEP 03）已移除：文章查看/编辑/发布统一在「文章管理」模块进行，避免功能重复。文章生成进度已上移至上方「用户问题池」区域展示。 -->

  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, type CheckboxValueType } from 'element-plus'
import {
  CircleCheck,
  Clock,
  CollectionTag,
  Delete,
  Document,
  FolderOpened,
  MagicStick,
  OfficeBuilding,
  Promotion,
  Refresh,
} from '@element-plus/icons-vue'
import { clientApi } from '@/services/api'
import { smartArticleApi, type SmartArticleBatch, type SmartArticleProject, type SmartArticleQuestion } from '@/services/smartArticleApi'

interface SmartArticleClient {
  id: number
  name: string
  company_name?: string | null
}

const router = useRouter()
const clients = ref<SmartArticleClient[]>([])
const allProjects = ref<SmartArticleProject[]>([])
const questions = ref<SmartArticleQuestion[]>([])
const questionGenerating = ref(false)
const articleGenerating = ref(false)
const questionsLoading = ref(false)
const questionBatch = ref<SmartArticleBatch | null>(null)
const articleBatch = ref<SmartArticleBatch | null>(null)
const questionTotal = ref(0)
const questionPage = ref(1)
const questionLimit = ref(20)
const questionFilter = ref<boolean | undefined>(undefined)
const selectedQuestionIds = ref<number[]>([])
const selectedQuestionRows = ref<SmartArticleQuestion[]>([])
let pollTimer: ReturnType<typeof setInterval> | undefined

const form = reactive({ clientId: undefined as number | undefined, projectId: undefined as number | undefined, questionCount: 10 })
const projects = computed(() => allProjects.value.filter(project => project.client_id === form.clientId))
const selectableQuestionCount = computed(() => selectedQuestionRows.value.filter(item => !item.has_article && item.article_generation_status !== 'generating').length)
const questionProgress = computed(() => progressPercent(questionBatch.value))
const articleProgress = computed(() => progressPercent(articleBatch.value))
const currentPageQuestionIds = computed(() => questions.value.map(item => item.id))
const isCurrentPageAllSelected = computed(() => {
  const ids = currentPageQuestionIds.value
  return ids.length > 0 && ids.every(id => selectedQuestionIds.value.includes(id))
})
const isCurrentPageIndeterminate = computed(() => {
  const ids = currentPageQuestionIds.value
  const selectedCount = ids.filter(id => selectedQuestionIds.value.includes(id)).length
  return selectedCount > 0 && selectedCount < ids.length
})
function isQuestionSelected(row: SmartArticleQuestion): boolean {
  return selectedQuestionIds.value.includes(row.id)
}
function toggleQuestionSelected(row: SmartArticleQuestion, checked: CheckboxValueType) {
  const shouldSelect = checked === true
  if (shouldSelect) {
    if (!selectedQuestionIds.value.includes(row.id)) {
      selectedQuestionIds.value = [...selectedQuestionIds.value, row.id]
      selectedQuestionRows.value = [...selectedQuestionRows.value, row]
    }
  } else {
    selectedQuestionIds.value = selectedQuestionIds.value.filter(id => id !== row.id)
    selectedQuestionRows.value = selectedQuestionRows.value.filter(item => item.id !== row.id)
  }
}
function toggleSelectAllCurrentPage(checked: CheckboxValueType) {
  const currentIds = new Set(currentPageQuestionIds.value)
  if (checked === true) {
    const existingIds = new Set(selectedQuestionIds.value)
    const addedRows = questions.value.filter(item => !existingIds.has(item.id))
    if (addedRows.length) {
      selectedQuestionIds.value = [...selectedQuestionIds.value, ...addedRows.map(item => item.id)]
      selectedQuestionRows.value = [...selectedQuestionRows.value, ...addedRows]
    }
  } else {
    selectedQuestionIds.value = selectedQuestionIds.value.filter(id => !currentIds.has(id))
    selectedQuestionRows.value = selectedQuestionRows.value.filter(item => !currentIds.has(item.id))
  }
}
function clearQuestionSelection() {
  selectedQuestionIds.value = []
  selectedQuestionRows.value = []
}
function onQuestionLimitChange() {
  questionPage.value = 1
  loadQuestions()
}

function unwrap<T>(res: any, fallback: T): T { return Array.isArray(res) ? res as T : (res?.data ?? fallback) }
function progressPercent(batch: SmartArticleBatch | null) {
  if (!batch?.requested_count) return 0
  return Math.min(100, Math.round(((batch.success_count || 0) + (batch.failed_count || 0)) / batch.requested_count * 100))
}
async function loadClients() {
  try {
    const res: any = await clientApi.getList({ status: 1, limit: 100 })
    const data = res?.data ?? res ?? {}
    clients.value = Array.isArray(data) ? data : (data.items || [])
  } catch { clients.value = [] }
}
async function loadProjects() { try { allProjects.value = unwrap(await smartArticleApi.getProjects(), []) } catch { allProjects.value = [] } }
function normalizeListResponse(res: any) {
  if (Array.isArray(res)) return res
  if (Array.isArray(res?.data)) return res.data
  if (Array.isArray(res?.data?.items)) return res.data.items
  if (Array.isArray(res?.items)) return res.items
  return []
}
function onClientChange() {
  stopPolling()
  form.projectId = undefined
  questions.value = []
  questionTotal.value = 0
  clearQuestionSelection()
  questionPage.value = 1
  questionBatch.value = null
  articleBatch.value = null
}
function onProjectChange() {
  clearQuestionSelection()
  questionPage.value = 1
  questionBatch.value = null
  articleBatch.value = null
  loadQuestions()
}
async function loadQuestions() {
  if (!form.projectId) { questions.value = []; questionTotal.value = 0; return }
  questionsLoading.value = true
  try {
    const res: any = await smartArticleApi.getQuestions({ project_id: form.projectId, has_article: questionFilter.value, page: questionPage.value, limit: questionLimit.value })
    const data = unwrap(res, { items: [], total: 0 })
    questions.value = data.items || []
    questionTotal.value = data.total || 0
  } finally { questionsLoading.value = false }
}
async function submitQuestionGeneration() {
  if (!form.projectId) return ElMessage.warning('请选择项目')
  questionGenerating.value = true
  try {
    const res: any = await smartArticleApi.generateQuestions({ project_id: form.projectId, question_count: form.questionCount, custom_question: null })
    const data = unwrap<{ batch_id: number }>(res, { batch_id: 0 })
    if (!data.batch_id) throw new Error('问题批次创建失败')
    ElMessage.success('问题生成任务已提交')
    await refreshQuestionBatch(data.batch_id)
    startQuestionPolling(data.batch_id)
  } catch { /* axios拦截器已提示 */ } finally { questionGenerating.value = false }
}
async function refreshQuestionBatch(batchId: number) {
  const res: any = await smartArticleApi.getQuestionBatch(batchId)
  questionBatch.value = unwrap<SmartArticleBatch | null>(res, null)
  if (questionBatch.value?.status === 'completed') await loadQuestions()
}
function startQuestionPolling(batchId: number) {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = setInterval(async () => {
    await refreshQuestionBatch(batchId)
    if (questionBatch.value && ['completed', 'failed'].includes(questionBatch.value.status)) stopPolling()
  }, 2000)
}
async function generateSelectedArticles() {
  if (!form.projectId || selectableQuestionCount.value === 0) return
  const selected = selectedQuestionRows.value.filter(item => !item.has_article && item.article_generation_status !== 'generating').map(item => item.id)
  const ignored = selectedQuestionRows.value.length - selected.length
  const message = ignored ? `其中${ignored}条已经生成或正在生成，将只生成${selected.length}篇文章，是否继续？` : `确定生成${selected.length}篇文章吗？`
  await ElMessageBox.confirm(message, '确认生成', { type: 'warning' })
  articleGenerating.value = true
  try {
    const res: any = await smartArticleApi.generateSelectedArticles({ project_id: form.projectId, question_ids: selected })
    const data = unwrap<{ batch_id: number }>(res, { batch_id: 0 })
    if (!data.batch_id) throw new Error('文章批次创建失败')
    ElMessage.success('文章生成任务已提交')
    clearQuestionSelection()
    await refreshArticleBatch(data.batch_id)
    await loadQuestions()
    startArticlePolling(data.batch_id)
  } catch { /* 用户取消或axios拦截器已提示 */ } finally { articleGenerating.value = false }
}
async function refreshArticleBatch(batchId: number) { const res: any = await smartArticleApi.getBatch(batchId); articleBatch.value = unwrap<SmartArticleBatch | null>(res, null) }
function startArticlePolling(batchId: number) {
  if (pollTimer) clearInterval(pollTimer)
  let pollCount = 0
  pollTimer = setInterval(async () => {
    pollCount += 1
    await refreshArticleBatch(batchId)
    const finished = articleBatch.value && ['completed', 'partial_failed', 'failed'].includes(articleBatch.value.status)
    if (finished || pollCount % 5 === 0) {
      await loadQuestions()
    }
    if (finished) stopPolling()
  }, 2000)
}
function stopPolling() { if (pollTimer) clearInterval(pollTimer); pollTimer = undefined }
async function deleteSelectedQuestions() {
  if (!selectedQuestionIds.value.length) return
  await ElMessageBox.confirm(`确定删除选中的${selectedQuestionIds.value.length}个问题吗？已生成的文章不会被删除。`, '确认删除问题', { type: 'warning' })
  await smartArticleApi.deleteQuestions(selectedQuestionIds.value)
  clearQuestionSelection()
  ElMessage.success('问题已删除')
  await loadQuestions()
}
function projectName(id?: number | null) { return allProjects.value.find(item => item.id === id)?.name || (id ? `项目 #${id}` : '-') }
function intentText(value?: string) { return ({ provider: '推荐', selection: '选型', solution: '方案', comparison: '比较', scenario: '场景', implementation: '实施', risk: '风险', manual: '指定' } as Record<string, string>)[value || ''] || '通用' }
function questionStatusText(row: SmartArticleQuestion) { return row.has_article ? '已生成文章' : row.article_generation_status === 'generating' ? '生成中' : '未生成文章' }
function questionStatusType(row: SmartArticleQuestion) { return row.has_article ? 'success' : row.article_generation_status === 'generating' ? 'warning' : 'info' }
function formatTime(value?: string | null) { return value ? new Date(value).toLocaleString('zh-CN') : '-' }
function goToArticles() { router.push('/articles') }

onMounted(async () => { await Promise.all([loadClients(), loadProjects()]) })
onBeforeUnmount(stopPolling)
</script>

<style scoped>
.smart-articles-page {
  width: 100%;
  max-width: 1560px;
  min-height: 100%;
  margin: 0 auto;
  padding: 30px clamp(20px, 2.6vw, 42px) 52px;
  color: var(--text-body);
}

.studio-hero {
  position: relative;
  display: flex;
  align-items: stretch;
  justify-content: space-between;
  gap: 48px;
  min-height: 258px;
  margin-bottom: 24px;
  padding: 38px 42px;
  overflow: hidden;
  color: #fffaf0;
  background:
    radial-gradient(circle at 82% 12%, rgba(214, 136, 46, 0.28), transparent 28%),
    linear-gradient(125deg, #211a10 0%, #312516 54%, #194f59 130%);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 20px;
  box-shadow: 0 18px 48px rgba(50, 37, 20, 0.16);
}

.studio-hero::before,
.studio-hero::after {
  position: absolute;
  content: '';
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 50%;
  pointer-events: none;
}

.studio-hero::before { width: 280px; height: 280px; right: -70px; top: -150px; }
.studio-hero::after { width: 180px; height: 180px; right: 180px; bottom: -138px; }
.hero-copy, .hero-overview { position: relative; z-index: 1; }
.hero-copy { display: flex; flex: 1; flex-direction: column; justify-content: center; max-width: 780px; }

.eyebrow {
  display: flex;
  align-items: center;
  gap: 9px;
  margin-bottom: 14px;
  color: #edbd75;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .18em;
}

.eyebrow-dot {
  width: 7px;
  height: 7px;
  background: #e6a548;
  border-radius: 50%;
  box-shadow: 0 0 0 5px rgba(230, 165, 72, 0.13);
}

.studio-hero h1 {
  margin: 0;
  color: #fffaf0;
  font-family: var(--font-display);
  font-size: clamp(30px, 3vw, 42px);
  font-weight: 600;
  line-height: 1.22;
  letter-spacing: .01em;
}

.studio-hero p { margin: 13px 0 0; color: rgba(255, 250, 240, 0.68); font-size: 15px; line-height: 1.7; }
.workflow-rail { display: flex; align-items: center; gap: 13px; margin-top: 28px; }
.workflow-step { display: flex; align-items: center; gap: 8px; color: rgba(255, 250, 240, 0.52); font-size: 12px; white-space: nowrap; }
.workflow-step.is-active { color: #fff2db; }
.step-index { display: grid; width: 28px; height: 28px; place-items: center; color: rgba(255, 250, 240, 0.7); font-family: var(--font-mono); font-size: 9px; border: 1px solid rgba(255, 255, 255, 0.18); border-radius: 50%; }
.workflow-step.is-active .step-index { color: #3d270d; background: #e8b464; border-color: #e8b464; }
.workflow-line { width: 34px; height: 1px; background: rgba(255, 255, 255, 0.14); }

.hero-overview {
  align-self: center;
  width: 285px;
  padding: 24px;
  background: rgba(255, 255, 255, 0.07);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 16px;
  backdrop-filter: blur(12px);
}

.overview-label { color: rgba(255, 250, 240, 0.55); font-size: 11px; letter-spacing: .12em; }
.overview-grid { display: grid; grid-template-columns: 1fr 1px 1fr; align-items: center; gap: 18px; margin: 20px 0; }
.overview-item { display: flex; flex-direction: column; gap: 4px; }
.overview-value { color: #fffaf0; font-family: var(--font-display); font-size: 34px; line-height: 1; }
.overview-name { color: rgba(255, 250, 240, 0.58); font-size: 12px; }
.overview-divider { width: 1px; height: 38px; background: rgba(255, 255, 255, 0.13); }
.draft-note { display: flex; align-items: center; gap: 8px; padding-top: 16px; color: rgba(255, 250, 240, 0.72); font-size: 12px; border-top: 1px solid rgba(255, 255, 255, 0.1); }
.draft-note-icon { display: inline-flex; width: 16px; color: #8fc59a; }

.creation-panel,
.content-panel {
  margin-bottom: 24px;
  background: var(--surface-raised);
  border: 1px solid var(--border-soft);
  border-radius: 18px;
  box-shadow: var(--shadow-sm);
}

.creation-panel { padding: 30px 32px 28px; }
.panel-heading, .content-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; }
.panel-heading { margin-bottom: 28px; padding-bottom: 24px; border-bottom: 1px solid var(--border-thin); }
.section-identity { display: flex; align-items: flex-start; gap: 15px; }
.section-identity.compact { align-items: center; }
.section-icon { display: grid; flex: 0 0 auto; width: 44px; height: 44px; place-items: center; color: #fff; background: linear-gradient(145deg, var(--accent), #df963f); border-radius: 13px; box-shadow: 0 8px 20px rgba(196, 116, 28, 0.2); }
.section-icon.teal { background: linear-gradient(145deg, #1f7a92, #3b98a8); box-shadow: 0 8px 20px rgba(31, 122, 146, 0.18); }
.section-icon.amber { background: linear-gradient(145deg, #b86515, #db9134); }
.section-icon svg { width: 21px; }
.section-kicker { margin: 1px 0 5px; color: var(--accent); font-family: var(--font-mono); font-size: 10px; font-weight: 700; letter-spacing: .09em; }
.section-identity h2 { margin: 0; color: var(--text-head); font-family: var(--font-display); font-size: 22px; font-weight: 600; }
.section-identity p { margin: 6px 0 0; color: var(--text-muted); font-size: 13px; line-height: 1.55; }
.panel-badge { padding: 7px 12px; color: var(--accent); background: var(--accent-soft); border: 1px solid rgba(196, 116, 28, 0.18); border-radius: 999px; font-size: 11px; font-weight: 600; white-space: nowrap; }

.form-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 22px; }
.creation-form :deep(.el-form-item) { margin-bottom: 20px; }
.creation-form :deep(.el-form-item__label) { height: auto; padding-bottom: 9px; color: var(--text-body); font-weight: 600; line-height: 1.4; }
.field-label { display: inline-flex; align-items: center; gap: 7px; }
.field-label svg { width: 15px; color: var(--accent); }
.creation-form :deep(.el-select__wrapper),
.creation-form :deep(.el-input-number .el-input__wrapper) { min-height: 42px; }
.form-tip { margin-top: 7px; color: var(--text-muted); font-size: 11px; line-height: 1.5; }
.warning-tip { color: var(--warning); }

.creation-footer { display: flex; align-items: center; justify-content: space-between; gap: 20px; margin-top: 22px; }
.creation-hint { display: flex; align-items: center; gap: 9px; color: var(--text-muted); font-size: 12px; }
.hint-orb { display: grid; width: 28px; height: 28px; place-items: center; color: var(--accent); background: var(--accent-soft); border-radius: 50%; }
.hint-orb svg { width: 14px; }
.primary-action { min-width: 172px; height: 42px; box-shadow: 0 8px 20px rgba(196, 116, 28, 0.18); }

.panel-progress {
  display: grid;
  grid-template-columns: 260px minmax(220px, 1fr);
  align-items: center;
  gap: 24px;
  padding: 14px 28px;
  background: var(--surface-base);
  border-top: 1px solid var(--border-thin);
  border-bottom: 1px solid var(--border-thin);
}
.progress-copy { display: flex; align-items: center; gap: 12px; }
.progress-copy > div { display: flex; flex-direction: column; gap: 3px; }
.progress-copy strong { color: var(--text-head); font-size: 13px; }
.progress-copy span { color: var(--text-muted); font-size: 11px; }
.progress-icon { display: grid; width: 34px; height: 34px; place-items: center; color: var(--accent); background: var(--accent-soft); border-radius: 10px; }
.progress-icon svg { width: 17px; }
.panel-progress .error-note { grid-column: 1 / -1; color: var(--danger); font-size: 12px; }

.content-panel { overflow: hidden; }
.content-header { padding: 25px 28px 22px; border-bottom: 1px solid var(--border-thin); }
.filters { display: flex; align-items: center; justify-content: flex-end; gap: 9px; flex-wrap: wrap; }
.filters .el-select { width: 140px; }
.selection-bar { display: flex; align-items: center; justify-content: space-between; gap: 20px; margin: 16px 20px; padding: 11px 14px; color: var(--text-muted); background: var(--surface-base); border: 1px solid var(--border-thin); border-radius: 10px; font-size: 12px; transition: all var(--duration-fast); }
.selection-bar.has-selection { color: var(--text-body); background: var(--accent-soft); border-color: rgba(196, 116, 28, 0.2); }
.selection-count { margin-right: 3px; color: var(--accent); font-family: var(--font-mono); font-size: 17px; font-weight: 700; }
.selection-divider { margin: 0 7px; color: var(--text-disabled); }

.studio-table { width: calc(100% - 40px); margin: 0 20px; --el-table-border-color: var(--border-thin); --el-table-header-bg-color: var(--surface-base); --el-table-row-hover-bg-color: var(--surface-hover); }
.studio-table :deep(th.el-table__cell) { height: 44px; color: var(--text-muted); font-size: 11px; font-weight: 600; letter-spacing: .03em; }
.studio-table :deep(td.el-table__cell) { padding: 13px 0; }
.studio-table :deep(.el-table__inner-wrapper::before) { display: none; }
.question-cell { display: flex; align-items: flex-start; gap: 12px; padding-right: 18px; }
.question-mark { display: grid; flex: 0 0 auto; width: 25px; height: 25px; margin-top: 1px; place-items: center; color: var(--info); background: var(--info-soft); border-radius: 7px; font-family: var(--font-display); font-size: 12px; font-weight: 700; }
.question-text { color: var(--text-body); line-height: 1.65; }
.type-chip { display: inline-flex; padding: 4px 9px; color: var(--text-muted); background: var(--surface-field); border-radius: 6px; font-size: 11px; }
.muted-cell { color: var(--text-muted); font-size: 12px; }
.pagination-wrap { display: flex; justify-content: flex-end; padding: 18px 24px 22px; }

.text-muted { color: var(--text-muted); }

@media (max-width: 1100px) {
  .studio-hero { gap: 28px; padding: 34px; }
  .hero-overview { width: 250px; }
  .form-grid { grid-template-columns: 1fr 1fr; }
  .form-grid > :last-child { grid-column: 1 / -1; }
  .content-header { align-items: flex-start; flex-direction: column; }
  .filters { width: 100%; justify-content: flex-start; }
}

@media (max-width: 760px) {
  .smart-articles-page { padding: 16px 12px 36px; }
  .studio-hero { min-height: 0; padding: 28px 24px; flex-direction: column; border-radius: 16px; }
  .hero-overview { width: 100%; }
  .workflow-rail { gap: 8px; }
  .workflow-line { width: 16px; }
  .creation-panel { padding: 24px 18px; }
  .panel-heading, .creation-footer, .selection-bar { align-items: flex-start; flex-direction: column; }
  .panel-badge { display: none; }
  .form-grid { grid-template-columns: 1fr; gap: 0; }
  .form-grid > :last-child { grid-column: auto; }
  .primary-action { width: 100%; }
  .panel-progress { grid-template-columns: 1fr; gap: 14px; padding: 14px 18px; }
  .content-header { padding: 22px 18px; }
  .section-identity { gap: 11px; }
  .filters .el-select { width: calc(50% - 24px); }
  .selection-bar { margin: 14px 12px; }
  .studio-table { width: calc(100% - 24px); margin: 0 12px; }
  .pagination-wrap { padding: 16px 14px 20px; overflow-x: auto; }
}
</style>
