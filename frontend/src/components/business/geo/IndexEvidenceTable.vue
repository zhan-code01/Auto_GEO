<template>
  <div class="evidence-section">
    <div class="section-header">
      <h3 class="section-title">证据明细</h3>
      <div class="header-actions">
        <el-select v-model="phaseFilter" placeholder="检测阶段" clearable size="small" style="width: 140px" @change="loadPage(1)">
          <el-option label="全部" value="" />
          <el-option label="使用前基线" value="baseline" />
          <el-option label="使用后复测" value="ongoing" />
        </el-select>
        <el-button size="small" @click="loadPage(pagination.currentPage)">
          <el-icon><Refresh /></el-icon> 刷新
        </el-button>
      </div>
    </div>

    <el-table
      v-loading="loading"
      :data="records"
      stripe
      size="small"
      style="width: 100%"
      max-height="500"
    >
      <el-table-column label="检测阶段" width="110">
        <template #default="{ row }">
          <el-tag :type="row.check_phase === 'baseline' ? 'warning' : 'primary'" size="small" effect="plain">
            {{ row.check_phase === 'baseline' ? '使用前基线' : '使用后复测' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="question" label="问题" min-width="220" show-overflow-tooltip />
      <el-table-column label="问题类型" width="110">
        <template #default="{ row }">{{ classifyQuestion(row.question) }}</template>
      </el-table-column>
      <el-table-column label="平台" width="100">
        <template #default="{ row }">{{ platformName(row.platform) }}</template>
      </el-table-column>
      <el-table-column label="关键词命中" width="100" align="center">
        <template #default="{ row }">
          <el-tag :type="row.keyword_found ? 'success' : 'danger'" size="small">
            {{ row.keyword_found ? '命中' : '未命中' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="公司名提及" width="100" align="center">
        <template #default="{ row }">
          <el-tag :type="row.company_found ? 'success' : 'danger'" size="small">
            {{ row.company_found ? '命中' : '未命中' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="company_matched" label="命中公司词" width="130" show-overflow-tooltip />
      <el-table-column label="提及次数" width="100" align="center">
        <template #default="{ row }">
          <span v-if="row.keyword_count !== null || row.company_count !== null">
            {{ row.keyword_count ?? '-' }} / {{ row.company_count ?? '-' }}
          </span>
          <span v-else>—</span>
        </template>
      </el-table-column>
      <el-table-column label="置信度" width="90" align="center">
        <template #default="{ row }">
          {{ row.confidence !== null && row.confidence !== undefined ? (row.confidence * 100).toFixed(0) + '%' : '—' }}
        </template>
      </el-table-column>
      <el-table-column label="检测时间" width="155">
        <template #default="{ row }">{{ formatDate(row.check_time) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="80" fixed="right" align="center">
        <template #default="{ row }">
          <el-button type="primary" size="small" link @click="emit('view-answer', row)">
            查看回答
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="pagination-container">
      <el-pagination
        v-model:current-page="pagination.currentPage"
        v-model:page-size="pagination.pageSize"
        :page-sizes="[15, 30, 50]"
        layout="total, sizes, prev, pager, next"
        :total="pagination.total"
        @size-change="loadPage(1)"
        @current-change="loadPage"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, watch } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { indexCheckApi } from '@/services/api'

interface EvidenceRecord {
  id: number; keyword_id: number; platform: string; question: string; answer?: string
  keyword_found?: boolean; company_found?: boolean
  check_phase?: string; keyword_count?: number | null
  company_count?: number | null; company_matched?: string | null
  confidence?: number | null; check_time: string
}

const props = defineProps<{ projectId: number | null; visible: boolean }>()
const emit = defineEmits<{ 'view-answer': [record: EvidenceRecord] }>()

const loading = ref(false)
const records = ref<EvidenceRecord[]>([])
const phaseFilter = ref('')
const pagination = reactive({ currentPage: 1, pageSize: 15, total: 0 })

const platformName = (p: string) => ({ doubao: '豆包', qianwen: '通义千问', deepseek: 'DeepSeek' } as any)[p] || p

const classifyQuestion = (q: string) => {
  if (!q) return '—'
  if (q.includes('推荐') || q.includes('哪家') || q.includes('哪个')) return '推荐型'
  if (q.includes('排名') || q.includes('排行') || q.includes('靠前')) return '排名型'
  if (q.includes('对比') || q.includes('和') && q.includes('相比')) return '对比型'
  if (q.includes('口碑') || q.includes('评价') || q.includes('怎么样')) return '口碑型'
  if (q.includes('怎么') || q.includes('如何') || q.includes('方案')) return '场景型'
  return '推荐型'
}

const formatDate = (s: string) => {
  if (!s) return ''
  const d = new Date(s)
  if (isNaN(d.getTime())) return s
  return d.toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
}

const loadPage = async (page: number) => {
  if (!props.projectId) return
  loading.value = true
  pagination.currentPage = page
  try {
    const result = await indexCheckApi.getRecords({
      project_id: props.projectId,
      limit: pagination.pageSize,
      skip: (page - 1) * pagination.pageSize,
      check_phase: phaseFilter.value || undefined
    } as any)
    if (result && (result as any).items) {
      records.value = (result as any).items
      pagination.total = (result as any).total
    } else {
      records.value = []
      pagination.total = 0
    }
  } catch (e) {
    console.error('加载证据明细失败:', e)
    records.value = []
  } finally { loading.value = false }
}

watch(() => [props.projectId, props.visible], ([pid, vis]) => {
  if (pid && vis) loadPage(1)
})

defineExpose({ loadPage })
</script>

<style scoped>
.evidence-section {
  background: var(--surface-raised); border: 1px solid var(--border-thin);
  border-radius: var(--radius-lg); padding: 20px 24px; margin-bottom: 20px;
}
.section-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.section-title { font-size: 16px; font-weight: 600; margin: 0; color: var(--text-head); font-family: var(--font-display); }
.header-actions { display: flex; gap: 10px; }
.pagination-container { display: flex; justify-content: flex-end; margin-top: 16px; }
</style>
