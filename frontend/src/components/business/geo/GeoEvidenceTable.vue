<template>
  <!-- GEO 五指标证据明细：展示每条测评记录的原始问答与评估结果 -->
  <div class="geo-evidence">
    <div class="evidence-header">
      <h3 class="evidence-title">证据明细</h3>
      <div class="evidence-filters">
        <el-select v-model="filterPhase" size="small" placeholder="阶段" clearable style="width: 120px" @change="loadPage(1)">
          <el-option label="使用前" value="baseline" />
          <el-option label="使用后" value="ongoing" />
        </el-select>
        <el-select v-model="filterSentiment" size="small" placeholder="情感" clearable style="width: 120px" @change="loadPage(1)">
          <el-option label="正面" value="positive" />
          <el-option label="强正面" value="strongly_positive" />
          <el-option label="中性" value="neutral" />
          <el-option label="负面" value="negative" />
          <el-option label="强负面" value="strongly_negative" />
        </el-select>
        <el-select v-model="filterBrandMentioned" size="small" placeholder="品牌出现" clearable style="width: 120px" @change="loadPage(1)">
          <el-option label="已提及" :value="true" />
          <el-option label="未提及" :value="false" />
        </el-select>
        <el-select v-model="filterSuccess" size="small" placeholder="状态" clearable style="width: 110px" @change="loadPage(1)">
          <el-option label="成功" :value="true" />
          <el-option label="失败" :value="false" />
        </el-select>
        <el-button
          size="small"
          :disabled="!selectedFailedRecordIds.length || loading || retrying"
          :loading="retrying"
          @click="handleRetrySelected"
        >
          重试失败
        </el-button>
        <el-button
          size="small"
          type="danger"
          :disabled="!selectedRecordIds.length || loading || deleting"
          :loading="deleting"
          @click="handleBatchDelete"
        >
          删除选中
        </el-button>
      </div>
    </div>

    <div class="evidence-table-wrap">
      <el-table
        :data="tableData"
        v-loading="loading"
        stripe
        class="evidence-table"
        max-height="580"
        :empty-text="errorMessage || '暂无证据明细'"
        :row-style="{ height: '56px' }"
        row-key="id"
      >
      <el-table-column width="46" fixed="left" align="center">
        <template #header>
          <el-checkbox
            :model-value="isCurrentPageAllSelected"
            :indeterminate="isCurrentPageIndeterminate"
            :disabled="tableData.length === 0"
            @change="toggleSelectAllCurrentPage"
          />
        </template>
        <template #default="{ row }">
          <el-checkbox
            :model-value="isRecordSelected(row)"
            @change="(checked) => toggleRecordSelected(row, checked)"
            @click.stop
          />
        </template>
      </el-table-column>
      <el-table-column prop="platform" label="平台" width="110">
        <template #default="{ row }">
          <span>{{ platformLabel(row.platform) }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="phase" label="阶段" width="96">
        <template #default="{ row }">
          <el-tag :type="row.phase === 'baseline' ? 'info' : 'success'" size="small" effect="plain">
            {{ row.phase === 'baseline' ? '使用前' : '使用后' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="success" label="状态" width="78" align="center">
        <template #default="{ row }">
          <el-tag
            :type="row.success ? 'success' : 'danger'"
            size="small"
            effect="plain"
            :title="row.success ? '' : row.error_message"
          >
            {{ row.success ? '成功' : '失败' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="question" label="问题" min-width="360" show-overflow-tooltip>
        <template #default="{ row }">
          <span class="question-cell" @click="$emit('view-answer', row)">
            {{ row.question }}
          </span>
        </template>
      </el-table-column>
      <el-table-column prop="brand_mentioned" label="品牌" width="76" align="center">
        <template #default="{ row }">
          <span :class="row.brand_mentioned ? 'dot-green' : 'dot-red'">
            {{ row.brand_mentioned ? '●' : '○' }}
          </span>
        </template>
      </el-table-column>
      <el-table-column prop="ranking_score" label="排名" width="72" align="center">
        <template #default="{ row }">
          <span v-if="row.ranking_score !== null && row.ranking_score !== undefined">
            {{ row.ranking_score }}
          </span>
          <span v-else class="na">-</span>
        </template>
      </el-table-column>
      <el-table-column prop="sentiment_score" label="情感" width="72" align="center">
        <template #default="{ row }">
          <span v-if="row.sentiment_score !== null && row.sentiment_score !== undefined" :class="sentimentClass(row.sentiment_score)">
            {{ row.sentiment_score }}
          </span>
          <span v-else class="na">-</span>
        </template>
      </el-table-column>
      <el-table-column label="引用" width="128" align="center">
        <template #default="{ row }">
          <el-tooltip v-if="row.__citation?.tooltip" :content="row.__citation.tooltip" placement="top">
            <el-tag :type="citationTagType(row.__citation.kind)" size="small" effect="plain">
              {{ row.__citation.label }}
            </el-tag>
          </el-tooltip>
          <span v-else class="na">—</span>
        </template>
      </el-table-column>
      <el-table-column prop="asked_at" label="时间" width="116">
        <template #default="{ row }">
          <span class="time-cell">{{ fmtTime(row.asked_at || row.created_at) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="120" fixed="right" align="center">
        <template #default="{ row }">
          <el-button
            v-if="row.success === false"
            class="detail-button"
            size="small"
            text
            type="warning"
            :disabled="retrying"
            @click="handleRetryRow(row)"
          >
            重试
          </el-button>
          <el-button class="detail-button" size="small" text type="primary" @click="$emit('view-answer', row)">
            详情
          </el-button>
        </template>
      </el-table-column>
      </el-table>
    </div>

    <div class="evidence-pagination">
      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :page-sizes="[10, 20, 50]"
        :total="total"
        layout="total, sizes, prev, pager, next"
        @size-change="loadPage(1)"
        @current-change="loadPage"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox, type CheckboxValueType } from 'element-plus'
import { geoEvaluationApi } from '@/services/api'
import { describeCitationState, citationTagType } from './citationState'

const props = defineProps<{
  projectId?: number | null
  clientId?: number | null
  platform?: string
}>()

const emit = defineEmits<{
  'view-answer': [record: any]
  'records-deleted': []
  'records-retry-started': [runId?: number]
}>()

const tableData = ref<any[]>([])
const loading = ref(false)
const total = ref(0)
const errorMessage = ref('')
const currentPage = ref(1)
const pageSize = ref(20)
const filterPhase = ref('')
const filterSentiment = ref('')
const filterBrandMentioned = ref<boolean | ''>('')
const filterSuccess = ref<boolean | ''>('')
const selectedRows = ref<any[]>([])
const deleting = ref(false)
const retrying = ref(false)
const selectedRecordIds = computed(() => selectedRows.value.map(row => row.id).filter(Boolean))
const selectedFailedRecordIds = computed(() =>
  selectedRows.value.filter(row => row && row.success === false).map(row => row.id).filter(Boolean),
)
const currentPageRecordIds = computed(() => tableData.value.map(row => row?.id).filter(Boolean))
const isCurrentPageAllSelected = computed(() => {
  const ids = currentPageRecordIds.value
  return ids.length > 0 && ids.every(id => selectedRows.value.some(row => row.id === id))
})
const isCurrentPageIndeterminate = computed(() => {
  const ids = currentPageRecordIds.value
  const selectedCount = ids.filter(id => selectedRows.value.some(row => row.id === id)).length
  return selectedCount > 0 && selectedCount < ids.length
})

function isRecordSelected(row: any): boolean {
  return selectedRows.value.some(item => item.id === row.id)
}

function toggleRecordSelected(row: any, checked: CheckboxValueType) {
  const shouldSelect = checked === true
  if (shouldSelect) {
    if (!selectedRows.value.some(item => item.id === row.id)) {
      selectedRows.value = [...selectedRows.value, row]
    }
  } else {
    selectedRows.value = selectedRows.value.filter(item => item.id !== row.id)
  }
}

function toggleSelectAllCurrentPage(checked: CheckboxValueType) {
  const currentIds = new Set(currentPageRecordIds.value)
  if (checked === true) {
    const existingIds = new Set(selectedRows.value.map(row => row.id))
    const addedRows = tableData.value.filter(row => !existingIds.has(row.id))
    if (addedRows.length) {
      selectedRows.value = [...selectedRows.value, ...addedRows]
    }
  } else {
    selectedRows.value = selectedRows.value.filter(row => !currentIds.has(row.id))
  }
}

const platformLabel = (p: string) => {
  const m: Record<string, string> = { doubao: '豆包', qianwen: '通义千问', deepseek: 'DeepSeek' }
  return m[p] || p
}

const fmtTime = (s: string | null) => {
  if (!s) return ''
  const d = new Date(s)
  if (isNaN(d.getTime())) return s
  return d.toLocaleString('zh-CN', {
    month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
    hour12: false,
  })
}

const sentimentClass = (score: number) => {
  if (score >= 80) return 'sent-positive'
  if (score >= 50) return 'sent-neutral'
  return 'sent-negative'
}

const loadPage = async (page?: number) => {
  if (!props.clientId) return
  if (page) currentPage.value = page

  loading.value = true
  errorMessage.value = ''
  try {
    const params: any = {
      limit: pageSize.value,
      skip: (currentPage.value - 1) * pageSize.value,
    }
    if (filterPhase.value) params.phase = filterPhase.value
    if (props.platform) params.platform = props.platform
    if (filterSentiment.value) params.sentiment = filterSentiment.value
    if (filterBrandMentioned.value !== '') params.brand_mentioned = filterBrandMentioned.value
    if (filterSuccess.value !== '') params.success = filterSuccess.value

    const res = await geoEvaluationApi.getClientRecords(props.clientId, params, { silent: true })
    const data = (res as any)?.data || res || {}
    tableData.value = (data.items || []).map((item: any) => ({ ...item, __citation: describeCitationState(item) }))
    total.value = data.total || 0
  } catch (e: any) {
    console.error('加载证据明细失败:', e)
    tableData.value = []
    total.value = 0
    if (e?.response?.status === 404) {
      errorMessage.value = '证据明细接口暂未启用'
    } else if (e?.response?.status === 503) {
      errorMessage.value = 'GEO 测评数据库尚未初始化，请先执行数据库迁移'
    } else {
      errorMessage.value = e?.response?.data?.detail || e?.message || '证据明细加载失败'
    }
  } finally {
    loading.value = false
  }
}

const handleBatchDelete = async () => {
  if (!props.clientId || !selectedRecordIds.value.length) return

  try {
    await ElMessageBox.confirm(
      `确定要删除选中的 ${selectedRecordIds.value.length} 条证据明细吗？`,
      '批量删除证据',
      { confirmButtonText: '删除选中', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }

  deleting.value = true
  try {
    const deletedRequested = selectedRecordIds.value.length
    const res = await geoEvaluationApi.batchDeleteClientRecords(props.clientId, selectedRecordIds.value, { silent: true })
    const data = (res as any)?.data || res || {}
    ElMessage.success(data?.message || (res as any)?.message || '已删除选中证据')
    selectedRows.value = []
    const maxPage = Math.max(1, Math.ceil(Math.max(0, total.value - deletedRequested) / pageSize.value))
    await loadPage(Math.min(currentPage.value, maxPage))
    emit('records-deleted')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '批量删除失败')
  } finally {
    deleting.value = false
  }
}

const handleRetrySelected = async () => {
  if (!props.clientId || !selectedFailedRecordIds.value.length) return

  try {
    await ElMessageBox.confirm(
      `确定要重试选中的 ${selectedFailedRecordIds.value.length} 条失败记录吗？`,
      '重试失败记录',
      { confirmButtonText: '开始重试', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }

  retrying.value = true
  try {
    const res = await geoEvaluationApi.retryClientRecords(props.clientId, selectedFailedRecordIds.value, { silent: true })
    const data = (res as any)?.data || res || {}
    if (data?.success === false || (res as any)?.success === false) {
      ElMessage.error(data?.message || (res as any)?.message || '重试任务启动失败')
      return
    }
    ElMessage.success(data?.message || '失败记录重试任务已启动')
    selectedRows.value = []
    emit('records-retry-started', data?.run_id)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '重试任务启动失败')
  } finally {
    retrying.value = false
  }
}

const handleRetryRow = async (row: any) => {
  if (!props.clientId || !row?.id || row.success !== false) return
  retrying.value = true
  try {
    const res = await geoEvaluationApi.retryClientRecords(props.clientId, [row.id], { silent: true })
    const data = (res as any)?.data || res || {}
    if (data?.success === false || (res as any)?.success === false) {
      ElMessage.error(data?.message || (res as any)?.message || '重试任务启动失败')
      return
    }
    ElMessage.success(data?.message || '失败记录重试任务已启动')
    emit('records-retry-started', data?.run_id)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || e?.message || '重试任务启动失败')
  } finally {
    retrying.value = false
  }
}

// 允许外部触发刷新
const refresh = () => {
  loadPage(1)
}

watch(() => [props.clientId, props.platform], () => {
  if (props.clientId) loadPage(1)
}, { immediate: true })

defineExpose({ loadPage, refresh })
</script>

<style scoped>
.geo-evidence {
  margin-top: 20px;
  padding: 18px 20px;
  background: var(--surface-raised);
  border: 1px solid var(--border-thin);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}

.evidence-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  flex-wrap: wrap;
  gap: 10px;
}

.evidence-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-head);
  margin: 0;
}

.evidence-filters {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.evidence-table-wrap {
  width: 100%;
  overflow: hidden;
  border: 1px solid var(--border-thin);
  border-radius: var(--radius-sm);
}

.evidence-table {
  width: 100%;
}

.evidence-table :deep(.el-table__header th) {
  height: 44px;
  background: var(--surface-field) !important;
  color: var(--text-head);
  font-weight: 600;
}

.evidence-table :deep(.el-table__cell) {
  padding: 9px 0;
}

.evidence-table :deep(.el-table__fixed-right) {
  box-shadow: -8px 0 16px rgba(74, 53, 24, 0.06);
}

.detail-button {
  min-width: 48px;
  padding: 0 6px;
  white-space: nowrap;
}

.question-cell {
  display: inline-block;
  max-width: 100%;
  cursor: pointer;
  color: var(--text-link, #3a6b8c);
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: middle;
  white-space: nowrap;
}
.question-cell:hover {
  text-decoration: underline;
}

.sub-text {
  font-size: 11px;
  color: var(--text-disabled, #c0c4cc);
  line-height: 1.2;
}

.dot-green { color: var(--success); font-size: 14px; }
.dot-red { color: var(--text-disabled); font-size: 14px; }

.na { color: var(--text-disabled); font-size: 12px; }

.time-cell { font-size: 12px; color: var(--text-muted); }

.sent-positive { color: var(--success); font-weight: 600; }
.sent-neutral { color: var(--text-muted); }
.sent-negative { color: var(--danger); font-weight: 600; }

.evidence-pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

@media (max-width: 900px) {
  .geo-evidence {
    padding: 14px;
  }

  .evidence-header {
    align-items: stretch;
  }

  .evidence-filters {
    justify-content: flex-start;
  }

  .evidence-pagination {
    justify-content: flex-start;
    overflow-x: auto;
  }
}
</style>
