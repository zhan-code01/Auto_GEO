<template>
  <div class="monitor-page" v-if="initialized">
    <div class="top-bar">
      <div class="project-selector">
        <span class="selector-label">公司</span>
        <el-select
          v-model="selectedClientId"
          placeholder="请选择公司"
          style="width: 280px"
          filterable
          @change="onClientSelect"
        >
          <el-option v-for="client in clients" :key="client.id" :label="client.company_name" :value="client.id" />
        </el-select>
      </div>

      <div class="auth-summary">
        <span
          v-for="platform in platformStatuses"
          :key="platform.id"
          :class="['auth-dot', isAuthorized(platform.status) ? 'valid' : 'invalid']"
          :title="`${platform.name}：${isAuthorized(platform.status) ? '已授权' : '未授权'}`"
        >
          {{ platform.name.charAt(0) }}
        </span>
        <el-button size="small" text @click="showAuthPanel = !showAuthPanel">
          {{ showAuthPanel ? '收起授权' : '管理授权' }}
        </el-button>
      </div>
    </div>

    <div v-if="showAuthPanel" class="auth-panel">
      <div v-for="platform in platformStatuses" :key="platform.id" class="auth-item">
        <div class="auth-item-icon" :style="{ backgroundColor: `${platform.color}20` }">
          <span :style="{ color: platform.color }">{{ platform.name.charAt(0) }}</span>
        </div>
        <div class="auth-item-info">
          <strong>{{ platform.name }}</strong>
          <el-tag :type="isAuthorized(platform.status) ? 'success' : 'danger'" size="small">
            {{ isAuthorized(platform.status) ? '已授权' : '未授权' }}
          </el-tag>
        </div>
        <el-button
          size="small"
          :type="isAuthorized(platform.status) ? 'default' : 'primary'"
          :loading="authenticatingPlatform === platform.id"
          @click="startGeoLocalAuth(platform.id)"
        >
          {{ isAuthorized(platform.status) ? '重新授权' : '去授权' }}
        </el-button>
        <el-button
          v-if="isAuthorized(platform.status) && authenticatingPlatform !== platform.id"
          size="small"
          type="danger"
          @click="deletePlatformSession(platform.id)"
        >
          取消授权
        </el-button>
      </div>
    </div>

    <div class="diagnosis-content">
      <div v-if="!selectedClientId" class="no-project-state">
        <div class="empty-hero">
          <div class="empty-copy">
            <div class="empty-kicker">GEO 四指标测评</div>
            <h2>选择一家公司，开始预览问题与基线效果</h2>
            <p>智能文章模块生成的问题会汇入这里；只有手动生成基线或继续测评时，系统才会向 AI 平台提问。</p>
          </div>
          <div class="empty-summary">
            <div class="summary-number">{{ clients.length }}</div>
            <div class="summary-label">可选公司</div>
          </div>
        </div>

        <div class="empty-metrics-grid">
          <div class="empty-metric-card primary">
            <span class="metric-label">AI 可见度</span>
            <strong>--</strong>
            <span class="metric-desc">综合覆盖、排名和情感表现</span>
          </div>
          <div class="empty-metric-card">
            <span class="metric-label">出现覆盖率</span>
            <strong>--%</strong>
            <span class="metric-desc">品牌被 AI 回答提及的比例</span>
          </div>
          <div class="empty-metric-card">
            <span class="metric-label">推荐排名</span>
            <strong>--</strong>
            <span class="metric-desc">推荐位置和推荐强度评分</span>
          </div>
          <div class="empty-metric-card">
            <span class="metric-label">情感分</span>
            <strong>--</strong>
            <span class="metric-desc">品牌出现时的正负向评价</span>
          </div>
        </div>

        <div class="empty-workflow">
          <div class="workflow-step">
            <span class="step-index">1</span>
            <div>
              <strong>选择公司</strong>
              <span>从上方下拉框选择需要测评的公司</span>
            </div>
          </div>
          <div class="workflow-step">
            <span class="step-index">2</span>
            <div>
              <strong>预览问题池</strong>
              <span>查看智能文章模块已经生成的问题及各平台测评状态</span>
            </div>
          </div>
          <div class="workflow-step">
            <span class="step-index">3</span>
            <div>
              <strong>建立基线</strong>
              <span>先生成基线，新增问题可继续测评，之后执行使用后测试</span>
            </div>
          </div>
        </div>

        <div class="empty-platforms">
          <span class="platforms-title">平台授权</span>
          <span
            v-for="platform in platformStatuses"
            :key="platform.id"
            :class="['empty-platform-pill', isAuthorized(platform.status) ? 'valid' : 'invalid']"
          >
            {{ platform.name }} · {{ isAuthorized(platform.status) ? '已授权' : '未授权' }}
          </span>
        </div>
      </div>

      <template v-else>
      <GeoEvaluationStatus
        :prompt-set="evaluationConfig.active_prompt_set"
        :baseline-status="evaluationConfig.baseline_status.status"
        :platform-statuses="evaluationConfig.baseline_status.platforms"
        v-model:selected-platform="selectedPlatformFilter"
        :platform-options="platformFilterOptions"
        :authorized-platforms="authorizedPlatformIds"
        :baseline-loading="baselineLoading"
        :recheck-loading="recheckLoading"
        :generating-prompts="generatingPrompts"
        :disabled="!selectedClientId || !selectedPlatformFilter"
        :run-active="isSelectedPlatformRunActive"
        :account-options="evaluationAccountOptions"
        v-model:selected-account="selectedEvaluationAccountId"
        @generate-prompts="handleGeneratePrompts"
        @preview-prompts="handlePreviewPrompts"
        @create-baseline="handleCreateBaseline"
        @complete-baseline="handleCompleteBaseline"
        @rebuild-baseline="handleRebuildBaseline"
        @run-recheck="handleRunRecheck"
        @platform-change="onPlatformFilterChange"
      />
      <el-alert
        v-if="isRunningRun"
        class="manual-required-alert"
        type="info"
        :closable="false"
        show-icon
      >
        <template #title>测评任务正在执行</template>
        <div class="manual-required-content">
          <span>
            {{ latestRunStatus?.current_platform_name || latestRunStatus?.current_platform || platformName(selectedPlatformFilter || '') }}
            已完成 {{ latestRunStatus?.current_progress || 0 }}/{{ latestRunStatus?.total_planned || 0 }}，可以随时暂停并保留进度。
          </span>
          <el-button size="small" :loading="pauseRunLoading" @click="handlePauseRun">
            暂停任务
          </el-button>
          <el-button size="small" :loading="cancelRunLoading" @click="handleCancelRun">
            取消任务
          </el-button>
        </div>
      </el-alert>
      <el-alert
        v-if="isManualRequiredRun"
        class="manual-required-alert"
        type="warning"
        :closable="false"
        show-icon
      >
        <template #title>
          检测到平台人工验证
        </template>
        <div class="manual-required-content">
          <span>
            {{ latestRunStatus?.current_platform_name || latestRunStatus?.current_platform || 'AI 平台' }}
            要求登录或人工验证。请在已经打开的可见浏览器窗口中完成操作；客户端在线期间系统会持续等待，不会自动超时。
          </span>
          <span v-if="latestRunStatus?.error_message" class="manual-required-message">
            {{ latestRunStatus.error_message }}
          </span>
          <el-button type="primary" size="small" @click="handleManualRecheck">
            我已完成验证，重新检测
          </el-button>
          <el-button size="small" :loading="pauseRunLoading" @click="handlePauseRun">
            暂停任务
          </el-button>
          <el-button size="small" :loading="cancelRunLoading" @click="handleCancelRun">
            取消任务
          </el-button>
        </div>
      </el-alert>
      <el-alert
        v-if="isInterruptedRun"
        class="manual-required-alert"
        type="error"
        :closable="false"
        show-icon
      >
        <template #title>
          {{ isAccountRestrictedRun ? '平台遇到账号风控，执行服务已关闭' : '测评任务已中断，可从当前进度继续' }}
        </template>
        <div class="manual-required-content">
          <span>{{ latestRunStatus?.error_message || '本地客户端执行中断' }}</span>
          <el-button
            type="primary"
            size="small"
            :loading="resumeLoading"
            @click="handleResumeRun"
          >
            继续执行
          </el-button>
          <el-button
            size="small"
            :loading="cancelRunLoading"
            @click="handleCancelRun"
          >
            取消任务
          </el-button>
        </div>
      </el-alert>
      <GeoFiveMetrics
        :baseline="selectedMetricBaseline"
        :current="selectedMetricCurrent"
        :delta="selectedMetricDelta"
        :error-message="geoDiagnosisError"
      />
      <GeoMetricComparisonChart
        :baseline="selectedMetricBaseline"
        :current="selectedMetricCurrent"
        :delta="selectedMetricDelta"
      />

      <GeoCompetitorAnalysis
        :client-id="selectedClientId"
        :platform="selectedPlatformFilter"
      />

      <GeoEvidenceTable
        ref="evidenceRef"
        :client-id="selectedClientId"
        :platform="selectedPlatformFilter"
        @view-answer="handleViewAnswer"
        @records-deleted="handleEvidenceRecordsDeleted"
        @records-retry-started="handleEvidenceRecordsRetryStarted"
      />
      </template>
    </div>

    <el-dialog v-model="promptPreviewVisible" title="测评问题池" width="920px">
      <div class="prompt-preview-head">
        <div>
          <strong>{{ companyName }}</strong>
          <span class="muted">共 {{ prompts.length }} 个问题</span>
        </div>
        <el-button size="small" :loading="promptsLoading" @click="loadPrompts">刷新</el-button>
      </div>
      <el-table :data="prompts" v-loading="promptsLoading" max-height="520" empty-text="暂无问题">
        <el-table-column prop="sort_order" label="#" width="56">
          <template #default="{ $index }">{{ $index + 1 }}</template>
        </el-table-column>
        <el-table-column prop="related_project_name" label="项目" width="150" show-overflow-tooltip />
        <el-table-column prop="question_type" label="类型" width="110">
          <template #default="{ row }">{{ questionTypeLabel(row.question_type) }}</template>
        </el-table-column>
        <el-table-column prop="question" label="问题" min-width="390" show-overflow-tooltip />
        <el-table-column label="当前平台状态" width="130">
          <template #default="{ row }">
            <el-tag :type="promptStatusType(row)" size="small" effect="plain">
              {{ promptStatusLabel(row) }}
            </el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <el-dialog v-model="answerVisible" title="AI 回答原文" width="720px">
      <div v-if="answerRecord" class="answer-content">
        <div class="answer-meta">
          <div><strong>问题：</strong>{{ answerRecord.question }}</div>
          <div><strong>平台：</strong>{{ platformName(answerRecord.platform) }}</div>
          <div><strong>阶段：</strong>{{ answerRecord.phase === 'baseline' ? '使用前基线' : '使用后复测' }}</div>
          <div><strong>时间：</strong>{{ formatDate(answerRecord.asked_at || answerRecord.created_at) }}</div>
        </div>
        <div class="answer-tags">
          <el-tag :type="answerRecord.brand_mentioned ? 'success' : 'danger'" size="small">
            {{ answerRecord.brand_mentioned ? '品牌已提及' : '品牌未提及' }}
          </el-tag>
          <el-tag v-if="answerRecord.matched_names?.length" type="warning" size="small">
            命中词：{{ answerRecord.matched_names.join('、') }}
          </el-tag>
          <el-tag v-if="answerRecord.sentiment" size="small">
            {{ sentimentLabel(answerRecord.sentiment) }}
          </el-tag>
        </div>
        <div v-if="answerCitation && answerCitation.kind !== 'none'" class="answer-citations">
          <div class="answer-citations-head">
            <strong>引用来源：</strong>
            <el-tag :type="citationTagType(answerCitation.kind)" size="small" effect="plain">
              {{ answerCitation.label }}
            </el-tag>
          </div>
          <ul v-if="answerCitation.links.length" class="citation-list">
            <li v-for="(link, i) in answerCitation.links" :key="i">
              <a :href="link.url" target="_blank" rel="noopener noreferrer">{{ link.url }}</a>
              <span v-if="link.domain" class="citation-domain">{{ link.domain }}</span>
            </li>
          </ul>
          <div v-else-if="answerCitation.tooltip" class="citation-note">{{ answerCitation.tooltip }}</div>
          <div v-if="answerCitation.captureMethod" class="citation-note">采集方式：{{ answerCitation.captureMethod }}</div>
        </div>
        <div class="answer-body-box">
          <strong>AI 回答：</strong>
          <div class="answer-text">{{ answerRecord.answer || '（无回答内容）' }}</div>
        </div>
      </div>
    </el-dialog>

    <RemoteAuthDialog
      v-model="remoteAuthVisible"
      :platform-name="remoteAuthPlatformName"
      :status="remoteAuthStatus"
      :show-frame="false"
    />

  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { accountApi, clientApi, del, geoEvaluationApi, get, post } from '@/services/api'
import { useUserStore } from '@/stores/modules/user'
import GeoEvaluationStatus from '@/components/business/geo/GeoEvaluationStatus.vue'
import GeoEvidenceTable from '@/components/business/geo/GeoEvidenceTable.vue'
import { describeCitationState, citationTagType } from '@/components/business/geo/citationState'
import GeoCompetitorAnalysis from '@/components/business/geo/GeoCompetitorAnalysis.vue'
import GeoFiveMetrics from '@/components/business/geo/GeoFiveMetrics.vue'
import GeoMetricComparisonChart from '@/components/business/geo/GeoMetricComparisonChart.vue'
import RemoteAuthDialog from '@/components/common/RemoteAuthDialog.vue'

interface Client {
  id: number
  name: string
  company_name: string
  industry?: string
}

interface Platform {
  id: string
  name: string
  url: string
  color: string
  status?: string
}

interface PromptSetInfo {
  id?: number
  question_count: number
  status?: string
  frozen_at?: string | null
  version?: number
}

interface PlatformBaselineStatus {
  platform: string
  has_baseline: boolean
  baseline_count: number
  baseline_at: string | null
  attempted_count?: number
  failed_count?: number
  unmeasured_count?: number
  recheck_eligible_count?: number
}

interface EvaluationConfig {
  active_prompt_set: PromptSetInfo | null
  baseline_status: {
    status: 'none' | 'partial' | 'complete'
    platforms: PlatformBaselineStatus[]
  }
}

interface AggBlock {
  coverage_rate: number
  ranking_score: number
  sentiment_score: number
  visibility_score: number
  valid_count?: number
  answer_count?: number
  window_days?: number
}

interface DeltaBlock {
  coverage_pp: number | null
  ranking_score_delta: number | null
  sentiment_score_delta: number | null
  visibility_score_before: number | null
  visibility_score_after: number | null
  visibility_score_delta: number | null
  verdict: string
}

interface GeoDiagnosisData {
  baseline: AggBlock
  current: AggBlock
  delta: DeltaBlock | null
  prompt_set: PromptSetInfo | null
  comparable_platforms: string[]
  missing_baseline_platforms: string[]
  by_platform?: Array<{
    platform: string
    platform_name: string
    baseline: AggBlock
    current: AggBlock
    baseline_count: number
    current_count: number
  }>
}

interface RunStatus {
  id?: number
  phase?: string
  platforms?: string[]
  status: string
  total_planned: number
  total_completed: number
  total_failed?: number
  current_platform?: string
  current_platform_name?: string
  current_round?: number
  current_progress?: number
  error_message?: string | null
  interruption_reason?: string | null
  heartbeat_at?: string | null
}

const userStore = useUserStore()

const initialized = ref(false)
const selectedClientId = ref<number | null>(null)
const clients = ref<Client[]>([])
const showAuthPanel = ref(false)

const emptyConfig = (): EvaluationConfig => ({
  active_prompt_set: null,
  baseline_status: {
    status: 'none',
    platforms: [
      { platform: 'doubao', has_baseline: false, baseline_count: 0, baseline_at: null },
      { platform: 'qianwen', has_baseline: false, baseline_count: 0, baseline_at: null },
      { platform: 'deepseek', has_baseline: false, baseline_count: 0, baseline_at: null },
    ],
  },
})

const emptyAgg = (windowDays?: number): AggBlock => ({
  visibility_score: 0,
  coverage_rate: 0,
  ranking_score: 0,
  sentiment_score: 0,
  answer_count: 0,
  valid_count: 0,
  ...(windowDays ? { window_days: windowDays } : {}),
})

const emptyDiagnosis = (): GeoDiagnosisData => ({
  baseline: emptyAgg(),
  current: emptyAgg(7),
  delta: {
    visibility_score_before: null,
    visibility_score_after: null,
    visibility_score_delta: null,
    verdict: '数据不足',
    coverage_pp: null,
    ranking_score_delta: null,
    sentiment_score_delta: null,
  },
  prompt_set: null,
  comparable_platforms: [],
  missing_baseline_platforms: [],
})

const evaluationConfig = ref<EvaluationConfig>(emptyConfig())
const geoDiagnosis = ref<GeoDiagnosisData>(emptyDiagnosis())
const geoDiagnosisError = ref('')
const latestRunStatus = ref<RunStatus | null>(null)
const activeRunId = ref<number | null>(null)
let runPollTimer: number | null = null
// 当前项目的中断任务需先“继续”或“取消”；它只限制当前项目按钮，
// 后端已经释放平台名额，因此不会阻塞其他项目启动同平台任务。
const activeRunStatuses = ['pending', 'running', 'manual_required', 'interrupted']
const terminalRunStatuses = ['completed', 'failed', 'cancelled']
const isManualRequiredRun = computed(() => latestRunStatus.value?.status === 'manual_required')
const isInterruptedRun = computed(() => latestRunStatus.value?.status === 'interrupted')
const isRunningRun = computed(() => ['pending', 'running'].includes(latestRunStatus.value?.status || ''))
const isAccountRestrictedRun = computed(() => latestRunStatus.value?.interruption_reason === 'account_restricted')
const isSelectedPlatformRunActive = computed(() =>
  activeRunStatuses.includes(latestRunStatus.value?.status || ''),
)

const baselineLoading = ref(false)
const recheckLoading = ref(false)
const generatingPrompts = ref(false)
const resumeLoading = ref(false)
const pauseRunLoading = ref(false)
const cancelRunLoading = ref(false)
const evaluationAccountOptions = ref<Array<{ id: number; name: string }>>([])
const selectedEvaluationAccountId = ref<number | undefined>()

const promptPreviewVisible = ref(false)
const promptsLoading = ref(false)
const prompts = ref<any[]>([])

const platformStatuses = ref<Platform[]>([])
const authenticatingPlatform = ref<string | null>(null)
const remoteAuthVisible = ref(false)
const remoteAuthPlatformId = ref<string | null>(null)
const remoteAuthStatus = ref<'idle' | 'authenticating' | 'checking' | 'success' | 'failed'>('idle')
const availablePlatforms = ref<Platform[]>([
  { id: 'doubao', name: '豆包', url: 'https://www.doubao.com', color: '#ff6a00' },
  { id: 'qianwen', name: '通义千问', url: 'https://qianwen.com', color: '#1677ff' },
  { id: 'deepseek', name: 'DeepSeek', url: 'https://chat.deepseek.com', color: '#5b67ff' },
])

const answerVisible = ref(false)
const answerRecord = ref<any>(null)
const answerCitation = computed(() => (answerRecord.value ? describeCitationState(answerRecord.value) : null))
const evidenceRef = ref<InstanceType<typeof GeoEvidenceTable> | null>(null)
const selectedPlatformFilter = ref('')

// 收录监控平台选择

const companyName = computed(() => {
  if (!selectedClientId.value) return '未选择公司'
  const client = clients.value.find(item => item.id === selectedClientId.value)
  return client?.company_name || client?.name || ''
})

const authorizedPlatformIds = computed(() =>
  platformStatuses.value.filter(platform => isAuthorized(platform.status)).map(platform => platform.id),
)

const selectedRunPlatforms = computed(() =>
  selectedPlatformFilter.value ? [selectedPlatformFilter.value] : undefined,
)

type RiskAwareAction = 'baseline' | 'complete-baseline' | 'recheck' | 'rebuild-baseline'

interface RiskAckPayload {
  requires_risk_ack?: boolean
  blocked_platforms?: Array<{
    platform: string
    category?: string
    reason?: string
  }>
  message?: string
}

const selectedPlatformDiagnosis = computed(() => {
  if (!selectedPlatformFilter.value) return null
  return geoDiagnosis.value.by_platform?.find(item => item.platform === selectedPlatformFilter.value) || null
})

// 顶部平台选择：决定问题询问、基线建立、复测和证据筛选的目标 AI 平台
const platformFilterOptions = computed(() => platformStatuses.value.length ? platformStatuses.value : availablePlatforms.value)

async function onPlatformFilterChange() {
  // 切换平台筛选时，重新加载诊断数据；证据明细会跟随 platform prop 自动刷新。
  latestRunStatus.value = null
  activeRunId.value = null
  stopRunPolling()
  await Promise.all([loadDiagnosis(), loadLatestRunStatus(), loadEvaluationAccounts()])
}

async function loadEvaluationAccounts() {
  const platform = selectedPlatformFilter.value
  if (!platform) {
    evaluationAccountOptions.value = []
    selectedEvaluationAccountId.value = undefined
    return
  }
  try {
    const data: any = await accountApi.getList({ platform, status: 1, limit: 100 })
    const items = Array.isArray(data?.items) ? data.items : []
    evaluationAccountOptions.value = items
      .filter((account: any) => account.storage_state !== null || account.last_auth_time)
      .map((account: any) => ({
        id: Number(account.id),
        name: account.account_name || account.username || `${platform}账号`,
      }))
    selectedEvaluationAccountId.value = evaluationAccountOptions.value.length === 1
      ? evaluationAccountOptions.value[0].id
      : undefined
  } catch (error) {
    evaluationAccountOptions.value = []
    selectedEvaluationAccountId.value = undefined
    console.error('加载测评授权账户失败:', error)
  }
}

watch(authorizedPlatformIds, platformIds => {
  if (!platformIds.length) {
    selectedPlatformFilter.value = ''
    return
  }
  if (!selectedPlatformFilter.value || !platformIds.includes(selectedPlatformFilter.value)) {
    selectedPlatformFilter.value = platformIds[0]
    if (selectedClientId.value) {
      void onPlatformFilterChange()
    }
  }
})

const selectedMetricBaseline = computed(() =>
  selectedPlatformDiagnosis.value?.baseline || geoDiagnosis.value.baseline,
)

const selectedMetricCurrent = computed(() =>
  selectedPlatformDiagnosis.value?.current || geoDiagnosis.value.current,
)

const selectedMetricDelta = computed<DeltaBlock | null>(() => {
  const platformDiagnosis = selectedPlatformDiagnosis.value
  if (!platformDiagnosis) return geoDiagnosis.value.delta

  const baseline = platformDiagnosis.baseline
  const current = platformDiagnosis.current
  const hasBaseline = !!(baseline?.valid_count || baseline?.answer_count)
  const hasCurrent = !!(current?.valid_count || current?.answer_count)
  if (!hasBaseline || !hasCurrent) {
    return {
      visibility_score_before: hasBaseline ? baseline.visibility_score : null,
      visibility_score_after: hasCurrent ? current.visibility_score : null,
      visibility_score_delta: null,
      coverage_pp: null,
      ranking_score_delta: null,
      sentiment_score_delta: null,
      verdict: hasBaseline ? '样本不足' : '数据不足',
    }
  }

  return {
    visibility_score_before: baseline.visibility_score,
    visibility_score_after: current.visibility_score,
    visibility_score_delta: Number((current.visibility_score - baseline.visibility_score).toFixed(2)),
    coverage_pp: Number((current.coverage_rate - baseline.coverage_rate).toFixed(2)),
    ranking_score_delta: Number((current.ranking_score - baseline.ranking_score).toFixed(2)),
    sentiment_score_delta: Number((current.sentiment_score - baseline.sentiment_score).toFixed(2)),
    verdict: '单平台对比',
  }
})

const remoteAuthPlatformName = computed(() =>
  availablePlatforms.value.find(platform => platform.id === remoteAuthPlatformId.value)?.name || '',
)

function isAuthorized(status?: string) {
  return status === 'valid' || status === 'expiring'
}

function platformName(platform: string) {
  const labels: Record<string, string> = { doubao: '豆包', qianwen: '通义千问', deepseek: 'DeepSeek' }
  return labels[platform] || platform
}

function questionTypeLabel(type: string) {
  const labels: Record<string, string> = {
    recommendation: '供应商推荐',
    scenario: '场景找供应商',
    comparison: '采购选型',
    business_understanding: '业务理解',
    brand_awareness: '品牌认知',
    reputation: '口碑评价',
  }
  return labels[type] || type
}

function promptPlatformStatus(row: any) {
  const platform = selectedPlatformFilter.value || ''
  return row?.platform_statuses?.[platform] || {}
}

function promptStatusLabel(row: any) {
  const status = promptPlatformStatus(row)
  if (status.ongoing_success) return '已完成使用后测试'
  if (status.baseline_success) return '基线已完成'
  if (status.baseline_attempted) return '基线失败'
  return '未测评'
}

function promptStatusType(row: any) {
  const status = promptPlatformStatus(row)
  if (status.ongoing_success) return 'success'
  if (status.baseline_success) return 'primary'
  if (status.baseline_attempted) return 'danger'
  return 'info'
}

function sentimentLabel(sentiment: string) {
  const labels: Record<string, string> = {
    strongly_positive: '强正面',
    positive: '正面',
    neutral: '中性',
    negative: '负面',
    strongly_negative: '强负面',
  }
  return labels[sentiment] || sentiment
}

function formatDate(value: string | null | undefined) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

async function loadClients() {
  try {
    const res = await clientApi.getList({ limit: 100 })
    const data = (res as any)?.data || res || {}
    clients.value = data.items || data || []
  } catch (error) {
    console.error('加载公司列表失败:', error)
    ElMessage.error('公司列表加载失败')
  }
}

async function loadPlatformStatuses() {
  const userId = userStore.user?.id
  if (!userId) {
    platformStatuses.value = availablePlatforms.value.map(platform => ({ ...platform, status: 'invalid' }))
    return
  }

  if (!platformStatuses.value.length) {
    platformStatuses.value = availablePlatforms.value.map(platform => ({ ...platform, status: 'invalid' }))
  }

  const results = await Promise.all(
    availablePlatforms.value.map(platform =>
      get('/auth/session/status', { user_id: userId, platform: platform.id, fast: true })
        .catch(() => ({ success: false, data: { status: 'invalid' } })),
    ),
  )

  platformStatuses.value = availablePlatforms.value.map((platform, index) => ({
    ...platform,
    status: (results[index] as any)?.success && (results[index] as any)?.data?.status
      ? (results[index] as any).data.status
      : 'invalid',
  }))
}

async function loadEvaluationConfig() {
  const clientId = selectedClientId.value
  if (!clientId) {
    evaluationConfig.value = emptyConfig()
    return
  }

  try {
    const res = await geoEvaluationApi.getClientConfig(clientId, { silent: true })
    evaluationConfig.value = (res as any)?.data || emptyConfig()
  } catch (error: any) {
    evaluationConfig.value = emptyConfig()
    if (error?.response?.status === 503) {
      geoDiagnosisError.value = 'GEO 测评数据库尚未初始化，请先执行数据库迁移'
    } else {
      geoDiagnosisError.value = error?.response?.data?.detail || error?.message || '测评配置加载失败'
    }
  }
}

async function loadDiagnosis() {
  const clientId = selectedClientId.value
  if (!clientId) {
    geoDiagnosis.value = emptyDiagnosis()
    return
  }

  geoDiagnosisError.value = ''
  try {
    const res = await geoEvaluationApi.getClientDiagnosis(clientId, { days: 7 }, { silent: true })
    geoDiagnosis.value = (res as any)?.data || emptyDiagnosis()
  } catch (error: any) {
    geoDiagnosis.value = emptyDiagnosis()
    if (error?.response?.status === 503) {
      geoDiagnosisError.value = 'GEO 测评数据库尚未初始化，请先执行数据库迁移'
    } else {
      geoDiagnosisError.value = error?.response?.data?.detail || error?.message || '四指标诊断加载失败'
    }
  }
}

async function loadLatestRunStatus() {
  const clientId = selectedClientId.value
  const platform = selectedPlatformFilter.value
  const promptSetId = evaluationConfig.value.active_prompt_set?.id
  if (!clientId || !platform || !promptSetId) {
    latestRunStatus.value = null
    return
  }

  try {
    const res = await geoEvaluationApi.getClientLatestRun(
      clientId,
      { platform, prompt_set_id: promptSetId },
      { silent: true },
    )
    const data = (res as any)?.data || null
    latestRunStatus.value = data
    activeRunId.value = data?.id || null
    if (data?.id && activeRunStatuses.includes(data.status || '') && !runPollTimer) {
      runPollTimer = window.setInterval(pollRunStatus, 5000)
    }
  } catch (error) {
    latestRunStatus.value = null
    console.error('加载当前平台最近任务失败:', error)
  }
}

async function refreshProjectData() {
  await loadEvaluationConfig()
  await Promise.all([loadDiagnosis(), loadLatestRunStatus(), loadEvaluationAccounts()])
  if (selectedClientId.value) {
    evidenceRef.value?.loadPage(1)
  }
}

async function onClientSelect() {
  prompts.value = []
  latestRunStatus.value = null
  stopRunPolling()
  await refreshProjectData()
}

async function handleGeneratePrompts() {
  const clientId = selectedClientId.value
  if (!clientId) return

  const hasPromptSet = !!evaluationConfig.value.active_prompt_set
  if (hasPromptSet) {
    try {
      await ElMessageBox.confirm(
        '重新生成会覆盖当前测评问题集。若当前问题集已有基线数据，后续需要重新建立使用前基线。确定继续吗？',
        '确认重新生成',
        { confirmButtonText: '确定重新生成', cancelButtonText: '取消', type: 'warning' },
      )
    } catch {
      return
    }
  }

  generatingPrompts.value = true
  try {
    const res = await geoEvaluationApi.generateClientPromptSet(
      clientId,
      { question_count: 100, overwrite: true },
      { silent: true },
    )
    const data = (res as any)?.data || res
    if (data?.success === false || (res as any)?.success === false) {
      ElMessage.error(data?.message || (res as any)?.message || '问题集生成失败')
      return
    }
    ElMessage.success(data?.message || (hasPromptSet ? '测评问题集已重新生成' : '测评问题集已生成'))
    await refreshProjectData()
    await handlePreviewPrompts()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '问题集生成失败')
  } finally {
    generatingPrompts.value = false
  }
}

async function loadPrompts() {
  const clientId = selectedClientId.value
  if (!clientId) return

  promptsLoading.value = true
  try {
    const res = await geoEvaluationApi.getClientPrompts(clientId, undefined, { silent: true })
    const data = (res as any)?.data || res || {}
    prompts.value = data.prompts || []
  } catch (error: any) {
    prompts.value = []
    ElMessage.error(error?.response?.data?.detail || error?.message || '问题预览加载失败')
  } finally {
    promptsLoading.value = false
  }
}

async function handlePreviewPrompts() {
  promptPreviewVisible.value = true
  await loadPrompts()
}

async function handleCreateBaseline() {
  if (!requireClient('生成基线')) return
  await startCreateBaseline(false)
}

/** 网页端检查：需要客户端才能执行浏览器操作 */
function requireClient(action: string): boolean {
  if (!window.electronAPI?.geoEvaluationEngine?.start) {
    showClientRequiredPrompt(action)
    return false
  }
  return true
}

async function ensureLocalClientEngineStarted() {
  const engine = window.electronAPI?.geoEvaluationEngine
  if (!engine?.start) {
    showClientRequiredPrompt('GEO 测评基线/复测')
    throw new Error('当前环境没有可用的 Electron GEO 测评引擎，请在客户端中操作')
  }
  const token = localStorage.getItem('autogeo_token')
  if (!token) {
    throw new Error('本地客户端执行需要先登录')
  }
  const result = await engine.start(token, getElectronServerBaseUrl())
  if (!result?.success) {
    throw new Error(result?.error || '本地客户端GEO测评引擎启动失败')
  }
}

async function startCreateBaseline(riskAcknowledged = false) {
  const clientId = selectedClientId.value
  if (!clientId) return

  baselineLoading.value = true
  try {
    const res = await geoEvaluationApi.createClientBaseline(
      clientId,
      {
        rounds: 1,
        platforms: selectedRunPlatforms.value,
        risk_acknowledged: riskAcknowledged,
        account_id: selectedEvaluationAccountId.value,
      },
      { silent: true },
    )
    const data = (res as any)?.data || res
    if (data?.success === false || (res as any)?.success === false) {
      if (await handleRiskAckIfNeeded(data, 'baseline')) return
      ElMessage.error(data?.message || (res as any)?.message || '基线任务创建失败')
      return
    }
    ElMessage.success(data?.message || '基线任务已创建')
    await ensureLocalClientEngineStarted()
    beginRunPolling(data?.run_id)
    await refreshProjectData()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '基线任务创建失败')
  } finally {
    baselineLoading.value = false
  }
}

async function handleCompleteBaseline() {
  if (!requireClient('补齐基线')) return
  await startCompleteBaseline(false)
}

async function startCompleteBaseline(riskAcknowledged = false) {
  const clientId = selectedClientId.value
  if (!clientId) return

  const platforms = selectedRunPlatforms.value || evaluationConfig.value.baseline_status.platforms
    .filter(platform => !platform.has_baseline)
    .map(platform => platform.platform)

  if (!platforms.length) {
    ElMessage.info('当前没有需要补齐基线的平台')
    return
  }

  baselineLoading.value = true
  try {
    const res = await geoEvaluationApi.completeClientBaseline(
      clientId,
      {
        platforms,
        risk_acknowledged: riskAcknowledged,
        account_id: selectedEvaluationAccountId.value,
      },
      { silent: true },
    )
    const data = (res as any)?.data || res
    if (data?.success === false || (res as any)?.success === false) {
      if (await handleRiskAckIfNeeded(data, 'complete-baseline')) return
      ElMessage.error(data?.message || (res as any)?.message || '补齐基线失败')
      return
    }
    ElMessage.success(data?.message || '补齐基线任务已创建')
    await ensureLocalClientEngineStarted()
    beginRunPolling(data?.run_id)
    await refreshProjectData()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '补齐基线失败')
  } finally {
    baselineLoading.value = false
  }
}

async function handleRunRecheck() {
  if (!requireClient('使用后测试')) return
  await startRunRecheck(false)
}

async function startRunRecheck(riskAcknowledged = false) {
  const clientId = selectedClientId.value
  if (!clientId) return

  recheckLoading.value = true
  try {
    const res = await geoEvaluationApi.runClientRecheck(
      clientId,
      {
        rounds: 1,
        platforms: selectedRunPlatforms.value,
        risk_acknowledged: riskAcknowledged,
        account_id: selectedEvaluationAccountId.value,
      },
      { silent: true },
    )
    const data = (res as any)?.data || res
    if (data?.success === false || (res as any)?.success === false) {
      if (await handleRiskAckIfNeeded(data, 'recheck')) return
      ElMessage.error(data?.message || (res as any)?.message || '使用后测试创建失败')
      return
    }
    ElMessage.success(data?.message || '使用后测试任务已创建')
    await ensureLocalClientEngineStarted()
    beginRunPolling(data?.run_id)
    await refreshProjectData()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '使用后测试创建失败')
  } finally {
    recheckLoading.value = false
  }
}

async function handleRebuildBaseline() {
  if (!requireClient('重新生成基线')) return
  const clientId = selectedClientId.value
  if (!clientId) return

  try {
    await ElMessageBox.confirm(
      '重新生成基线会清除当前平台已有的基线记录并重新询问全部问题，确定继续吗？',
      '重新生成基线',
      { confirmButtonText: '确定重建', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }

  await startRebuildBaseline(false)
}

async function startRebuildBaseline(riskAcknowledged = false) {
  const clientId = selectedClientId.value
  if (!clientId) return

  baselineLoading.value = true
  try {
    const res = await geoEvaluationApi.createClientBaseline(
      clientId,
      {
        rounds: 1,
        rebuild: true,
        platforms: selectedRunPlatforms.value,
        risk_acknowledged: riskAcknowledged,
        account_id: selectedEvaluationAccountId.value,
      },
      { silent: true },
    )
    const data = (res as any)?.data || res
    if (data?.success === false || (res as any)?.success === false) {
      if (await handleRiskAckIfNeeded(data, 'rebuild-baseline')) return
      ElMessage.error(data?.message || (res as any)?.message || '重新生成基线失败')
      return
    }
    ElMessage.success(data?.message || '重新生成基线任务已创建')
    await ensureLocalClientEngineStarted()
    beginRunPolling(data?.run_id)
    await refreshProjectData()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '重新生成基线失败')
  } finally {
    baselineLoading.value = false
  }
}

async function handleRiskAckIfNeeded(data: RiskAckPayload, action: RiskAwareAction) {
  if (!data?.requires_risk_ack) return false

  const platformNames = (data.blocked_platforms || [])
    .map(item => platformName(item.platform))
    .filter(Boolean)
  const title = platformNames.length ? `${platformNames.join('、')} 风控提示` : '平台风控提示'
  const detail = data.message || '平台可能要求人工验证。确认后将继续执行，并在需要时提示你处理。'

  try {
    await ElMessageBox.confirm(
      detail,
      title,
      {
        type: 'warning',
        confirmButtonText: '了解风险并继续',
        cancelButtonText: '暂不执行',
        distinguishCancelAndClose: true,
      },
    )
  } catch {
    return true
  }

  if (action === 'baseline') {
    await startCreateBaseline(true)
  } else if (action === 'complete-baseline') {
    await startCompleteBaseline(true)
  } else if (action === 'recheck') {
    await startRunRecheck(true)
  } else if (action === 'rebuild-baseline') {
    await startRebuildBaseline(true)
  }
  return true
}

function beginRunPolling(runId?: number) {
  if (!runId) return
  activeRunId.value = runId
  stopRunPolling()
  pollRunStatus()
  runPollTimer = window.setInterval(pollRunStatus, 5000)
}

function stopRunPolling() {
  if (runPollTimer) {
    window.clearInterval(runPollTimer)
    runPollTimer = null
  }
}

async function pollRunStatus() {
  if (!activeRunId.value) return

  try {
    const res = await geoEvaluationApi.getRunStatus(activeRunId.value, { silent: true })
    const data = (res as any)?.data || null
    if (selectedPlatformFilter.value && data?.platforms?.length && !data.platforms.includes(selectedPlatformFilter.value)) {
      return
    }
    latestRunStatus.value = data
    if (terminalRunStatuses.includes(latestRunStatus.value?.status || '')) {
      stopRunPolling()
      await refreshProjectData()
    }
  } catch (error) {
    console.error('轮询测评任务失败:', error)
  }
}

async function handleResumeRun() {
  if (!requireClient('继续执行测评')) return
  if (!activeRunId.value) return
  resumeLoading.value = true
  try {
    await geoEvaluationApi.resumeRun(activeRunId.value, { silent: true })
    await ensureLocalClientEngineStarted()
    beginRunPolling(activeRunId.value)
    ElMessage.success('任务已恢复，等待本地客户端继续执行')
    await pollRunStatus()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '恢复任务失败')
  } finally {
    resumeLoading.value = false
  }
}

async function handleManualRecheck() {
  if (!activeRunId.value) return
  const result = await window.electronAPI?.geoEvaluationEngine?.recheckManual(activeRunId.value)
  if (result?.success) {
    ElMessage.success('已通知本地执行器重新检测登录和验证状态')
    return
  }

  // Electron/后端重启后，数据库可能仍保留 manual_required，
  // 但原 Python 子进程已经退出。此时重新领取同一任务并启动新执行器。
  try {
    await geoEvaluationApi.resumeRun(activeRunId.value, { silent: true })
    await ensureLocalClientEngineStarted()
    beginRunPolling(activeRunId.value)
    ElMessage.success('原人工验证进程已退出，现已重新启动任务并检测登录状态')
  } catch (error: any) {
    ElMessage.error(
      error?.response?.data?.detail
      || error?.message
      || result?.error
      || '重新启动人工验证进程失败',
    )
  }
}

async function handlePauseRun() {
  if (!activeRunId.value) return
  pauseRunLoading.value = true
  try {
    await geoEvaluationApi.pauseRun(activeRunId.value, { silent: true })
    ElMessage.success('任务已暂停，当前进度已保留，平台执行名额已经释放')
    await pollRunStatus()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '暂停任务失败')
  } finally {
    pauseRunLoading.value = false
  }
}

async function handleCancelRun() {
  if (!activeRunId.value) return
  try {
    await ElMessageBox.confirm(
      '取消后将停止继续提问，已经保存的回答会保留，但该未完成任务不会生成最终指标。',
      '确认取消测评任务',
      { type: 'warning', confirmButtonText: '取消任务', cancelButtonText: '返回' },
    )
  } catch {
    return
  }
  cancelRunLoading.value = true
  try {
    await geoEvaluationApi.cancelRun(activeRunId.value, { silent: true })
    stopRunPolling()
    ElMessage.success('任务已取消，平台执行名额已经释放')
    await refreshProjectData()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '取消任务失败')
  } finally {
    cancelRunLoading.value = false
  }
}

function handleViewAnswer(record: any) {
  answerRecord.value = record
  answerVisible.value = true
}

async function handleEvidenceRecordsDeleted() {
  answerVisible.value = false
  answerRecord.value = null
  await loadEvaluationConfig()
  await loadDiagnosis()
}

async function handleEvidenceRecordsRetryStarted(runId?: number) {
  if (runId) beginRunPolling(runId)
  await loadLatestRunStatus()
  evidenceRef.value?.refresh()
}

function getElectronServerBaseUrl() {
  const configured = import.meta.env.VITE_API_BASE_URL || ''
  if (!configured || configured.startsWith('/')) return undefined
  return configured.replace(/\/api\/?$/, '').replace(/\/+$/, '')
}

async function startAuth(platformId: string) {
  // 网页端（非 Electron 客户端）无法直接拉取浏览器，提示用户使用客户端
  if (!window.electronAPI?.localAuth?.startAuth) {
    const platform = availablePlatforms.value.find(item => item.id === platformId)
    showClientRequiredPrompt(`${platform?.name || platformId} 平台授权`)
    return
  }

  const userId = userStore.user?.id
  if (!userId) {
    ElMessage.error('未登录，请重新登录')
    return
  }
  if (authenticatingPlatform.value) {
    ElMessage.warning('已有平台正在授权中')
    return
  }

  const platform = availablePlatforms.value.find(item => item.id === platformId)
  const token = localStorage.getItem('autogeo_token') || ''

  authenticatingPlatform.value = platformId
  remoteAuthPlatformId.value = platformId
  remoteAuthStatus.value = 'authenticating'
  remoteAuthVisible.value = true
  try {
    const result = await window.electronAPI.localAuth.startAuth(platformId, token, getElectronServerBaseUrl())
    if (!result?.success) {
      remoteAuthStatus.value = 'failed'
      ElMessage.error(result?.error || `${platform?.name || platformId} 授权失败`)
      return
    }
    remoteAuthStatus.value = 'success'
    ElMessage.success(`${platform?.name || platformId} 本机浏览器授权成功`)
    await loadPlatformStatuses()
  } catch (error: any) {
    remoteAuthStatus.value = 'failed'
    ElMessage.error(error?.message || `${platform?.name || platformId} 本机浏览器授权失败`)
  } finally {
    authenticatingPlatform.value = null
    window.setTimeout(() => {
      if (remoteAuthStatus.value === 'success') remoteAuthVisible.value = false
    }, 1200)
  }
}

/** 网页端提示用户使用客户端 */
function showClientRequiredPrompt(action: string) {
  ElMessageBox.alert(
    `${action}需要启动本地浏览器，请在 AutoGEO 客户端中操作。\n\n` +
    '网页版无法直接控制浏览器，请下载安装客户端后使用该功能。',
    '需要桌面客户端',
    {
      type: 'info',
      confirmButtonText: '知道了',
    },
  )
}

async function startGeoLocalAuth(platformId: string) {
  const userId = userStore.user?.id
  if (!userId) {
    ElMessage.error('未登录，请重新登录')
    return
  }
  if (authenticatingPlatform.value) {
    ElMessage.warning('已有平台正在授权中')
    return
  }

  const platform = availablePlatforms.value.find(item => item.id === platformId)

  // 网页端（非 Electron 客户端）无法直接拉取浏览器，提示用户使用客户端
  if (!window.electronAPI?.localAuth?.startAuth) {
    showClientRequiredPrompt(`${platform?.name || platformId} 平台授权`)
    return
  }

  const token = localStorage.getItem('autogeo_token') || ''
  authenticatingPlatform.value = platformId
  remoteAuthPlatformId.value = platformId
  remoteAuthStatus.value = 'authenticating'
  remoteAuthVisible.value = true

  try {
    const result = await window.electronAPI.localAuth.startAuth(platformId, token, getElectronServerBaseUrl())

    if (!result?.success) {
      remoteAuthStatus.value = 'failed'
      ElMessage.error(result?.error || `${platform?.name || platformId} 授权失败`)
      return
    }

    remoteAuthStatus.value = 'success'
    ElMessage.success(`${platform?.name || platformId} 本机浏览器授权成功`)
    await loadPlatformStatuses()
  } catch (error: any) {
    remoteAuthStatus.value = 'failed'
    ElMessage.error(error?.message || `${platform?.name || platformId} 本机浏览器授权失败`)
  } finally {
    authenticatingPlatform.value = null
    window.setTimeout(() => {
      if (remoteAuthStatus.value === 'success') remoteAuthVisible.value = false
    }, 1200)
  }
}

async function pollAuthStatus(platformId: string) {
  const userId = userStore.user?.id
  if (!userId) {
    authenticatingPlatform.value = null
    return
  }

  for (let i = 0; i < 45; i += 1) {
    await new Promise(resolve => window.setTimeout(resolve, 4000))
    try {
      const res = await get('/auth/session/status', { user_id: userId, platform: platformId, fast: true })
      if ((res as any)?.success && (res as any)?.data?.status === 'valid') {
        await loadPlatformStatuses()
        remoteAuthStatus.value = 'success'
        remoteAuthVisible.value = false
        authenticatingPlatform.value = null
        ElMessage.success(`${platformName(platformId)} 授权成功`)
        return
      }
    } catch {
      // Keep polling.
    }
  }

  remoteAuthStatus.value = 'failed'
  authenticatingPlatform.value = null
  ElMessage.info('授权检测超时，如已完成登录请手动刷新授权状态')
}

async function deletePlatformSession(platformId: string) {
  const platform = availablePlatforms.value.find(item => item.id === platformId)
  try {
    await ElMessageBox.confirm(`确定要取消 ${platform?.name || platformId} 的授权吗？`, '确认取消', { type: 'warning' })
    await del('/auth/session', { user_id: userStore.user?.id, platform: platformId })
    ElMessage.success('已取消授权')
    await loadPlatformStatuses()
  } catch {
    // cancelled
  }
}

onMounted(async () => {
  await Promise.all([loadClients(), loadPlatformStatuses()])
  initialized.value = true
})

onUnmounted(() => {
  stopRunPolling()
})
</script>

<style scoped>
.monitor-page {
  min-height: 100vh;
  padding: 24px 28px;
  color: var(--text-body);
}

.top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px;
  margin-bottom: 20px;
  background: var(--surface-raised);
  border: 1px solid var(--border-thin);
  border-radius: var(--radius-lg);
}

.selector-label {
  margin-right: 8px;
  font-size: 13px;
  color: var(--text-muted, #8a7d68);
}

.auth-summary {
  display: flex;
  align-items: center;
  gap: 8px;
}

.auth-dot {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 13px;
  font-weight: 700;
}

.auth-dot.valid { background: var(--success, #5ea878); }
.auth-dot.invalid { background: var(--danger, #b4453c); }

.auth-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px 20px;
  margin-bottom: 20px;
  background: var(--surface-raised);
  border: 1px solid var(--border-thin);
  border-radius: var(--radius-lg);
}

.auth-item {
  display: flex;
  align-items: center;
  gap: 14px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border-thin);
}

.auth-item:last-child {
  padding-bottom: 0;
  border-bottom: 0;
}

.auth-item-icon {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.auth-item-icon span {
  font-size: 16px;
  font-weight: 700;
}

.auth-item-info {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 12px;
}

.diagnosis-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.no-project-state {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.empty-hero {
  min-height: 210px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 150px;
  gap: 28px;
  align-items: center;
  padding: 32px 36px;
  overflow: hidden;
  background:
    linear-gradient(135deg, rgba(255, 255, 255, 0.94), rgba(248, 244, 236, 0.92)),
    radial-gradient(circle at 88% 18%, rgba(219, 76, 61, 0.16), transparent 30%),
    radial-gradient(circle at 72% 86%, rgba(58, 128, 92, 0.14), transparent 34%);
  border: 1px solid var(--border-thin);
  border-radius: var(--radius-lg);
  box-shadow: 0 18px 44px rgba(72, 57, 36, 0.08);
}

.empty-copy {
  max-width: 760px;
}

.empty-kicker {
  width: fit-content;
  padding: 5px 10px;
  margin-bottom: 14px;
  color: #9f342d;
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
  background: rgba(219, 76, 61, 0.1);
  border: 1px solid rgba(219, 76, 61, 0.18);
  border-radius: 999px;
}

.empty-copy h2 {
  max-width: 680px;
  margin: 0;
  color: var(--text-head);
  font-size: 26px;
  font-weight: 800;
  line-height: 1.28;
}

.empty-copy p {
  max-width: 720px;
  margin: 12px 0 0;
  color: var(--text-muted);
  font-size: 14px;
  line-height: 1.8;
}

.empty-summary {
  width: 132px;
  height: 132px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  justify-self: end;
  background: rgba(255, 255, 255, 0.82);
  border: 1px solid rgba(120, 98, 64, 0.14);
  border-radius: var(--radius-lg);
  box-shadow: 0 16px 32px rgba(72, 57, 36, 0.08);
}

.summary-number {
  color: var(--text-head);
  font-size: 38px;
  font-weight: 800;
  line-height: 1;
}

.summary-label {
  margin-top: 8px;
  color: var(--text-muted);
  font-size: 12px;
}

.empty-metrics-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.empty-metric-card {
  min-height: 132px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 18px 16px;
  background: var(--surface-raised);
  border: 1px solid var(--border-thin);
  border-radius: var(--radius-lg);
  box-shadow: 0 10px 24px rgba(72, 57, 36, 0.05);
}

.empty-metric-card.primary {
  border-left: 4px solid #db4c3d;
}

.metric-label {
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 700;
}

.empty-metric-card strong {
  color: var(--text-head);
  font-size: 34px;
  font-weight: 800;
  line-height: 1;
}

.empty-metric-card.primary strong {
  color: #db4c3d;
}

.metric-desc {
  margin-top: auto;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.55;
}

.empty-workflow {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.workflow-step {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  min-height: 92px;
  padding: 16px;
  background: var(--surface-raised);
  border: 1px solid var(--border-thin);
  border-radius: var(--radius-lg);
}

.step-index {
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: #fff;
  font-size: 12px;
  font-weight: 800;
  background: #2f6b4f;
  border-radius: 50%;
  box-shadow: 0 8px 18px rgba(47, 107, 79, 0.22);
}

.workflow-step strong {
  display: block;
  margin-bottom: 5px;
  color: var(--text-head);
  font-size: 14px;
}

.workflow-step span:last-child {
  display: block;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.65;
}

.empty-platforms {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 14px 18px;
  background: rgba(255, 255, 255, 0.58);
  border: 1px solid var(--border-thin);
  border-radius: var(--radius-lg);
}

.platforms-title {
  margin-right: 4px;
  color: var(--text-head);
  font-size: 13px;
  font-weight: 700;
}

.empty-platform-pill {
  padding: 5px 10px;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1;
  background: var(--surface-raised);
  border: 1px solid var(--border-thin);
  border-radius: 999px;
}

.empty-platform-pill.valid {
  color: #2f6b4f;
  background: rgba(47, 107, 79, 0.1);
  border-color: rgba(47, 107, 79, 0.22);
}

.empty-platform-pill.invalid {
  color: #9f342d;
  background: rgba(219, 76, 61, 0.08);
  border-color: rgba(219, 76, 61, 0.18);
}

.prompt-preview-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.muted {
  margin-left: 10px;
  color: var(--text-muted);
  font-size: 13px;
}

.answer-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.answer-meta {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 12px 16px;
  background: var(--surface-field, #faf7f0);
  border: 1px solid var(--border-thin);
  border-radius: var(--radius-sm);
  font-size: 13px;
}

.answer-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.answer-citations {
  padding: 12px 16px;
  background: var(--surface-field, #faf7f0);
  border: 1px solid var(--border-thin);
  border-radius: var(--radius-sm);
  font-size: 13px;
}

.answer-citations-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.citation-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 160px;
  overflow-y: auto;
}

.citation-list li {
  word-break: break-all;
}

.citation-list a {
  color: var(--text-link, #3a6b8c);
  text-decoration: none;
}

.citation-list a:hover {
  text-decoration: underline;
}

.citation-domain {
  margin-left: 8px;
  color: var(--text-disabled, #c0c4cc);
  font-size: 12px;
}

.citation-note {
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.6;
}

.answer-body-box strong {
  display: block;
  margin-bottom: 8px;
  color: var(--text-head);
}

.answer-text {
  max-height: 420px;
  overflow-y: auto;
  padding: 16px;
  line-height: 1.8;
  white-space: pre-wrap;
  word-break: break-word;
  background: var(--surface-field, #faf7f0);
  border: 1px solid var(--border-thin);
  border-radius: var(--radius-sm);
}

.manual-required-alert {
  margin: -8px 0 20px;
  border-radius: var(--radius-sm);
}

.manual-required-content {
  display: flex;
  flex-direction: column;
  gap: 4px;
  line-height: 1.6;
}

.manual-required-message {
  color: var(--warning, #b7791f);
  word-break: break-word;
}

@media (max-width: 1024px) {
  .empty-metrics-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 768px) {
  .monitor-page {
    padding: 14px;
  }

  .top-bar {
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
  }

  .project-selector,
  .auth-summary {
    width: 100%;
  }

  .project-selector {
    display: flex;
    align-items: center;
  }

  .project-selector :deep(.el-select) {
    flex: 1;
    width: auto !important;
  }

  .auth-summary {
    flex-wrap: wrap;
  }

  .auth-item {
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .empty-hero {
    grid-template-columns: 1fr;
    padding: 24px;
  }

  .empty-summary {
    width: 100%;
    height: auto;
    min-height: 96px;
    justify-self: stretch;
  }

  .empty-metrics-grid,
  .empty-workflow {
    grid-template-columns: 1fr;
  }
}
</style>
