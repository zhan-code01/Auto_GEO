<template>
  <div class="breakdown-section">
    <div class="section-header-row">
      <h3 class="section-title">效果拆解</h3>
    </div>
    <el-tabs v-model="activeTab" type="border-card" class="breakdown-tabs">
      <!-- 按平台 -->
      <el-tab-pane label="按平台" name="platform">
        <el-table :data="byPlatform" stripe size="small" style="width: 100%">
          <el-table-column prop="platform_name" label="平台" width="130" fixed />
          <el-table-column label="使用前" align="center">
            <el-table-column label="关键词命中率" width="120" align="center">
              <template #default="{ row }">{{ row.baseline_rate ?? 0 }}%</template>
            </el-table-column>
            <el-table-column label="公司名提及率" width="120" align="center">
              <template #default="{ row }">{{ row.baseline_company_rate ?? 0 }}%</template>
            </el-table-column>
          </el-table-column>
          <el-table-column label="使用后" align="center">
            <el-table-column label="关键词命中率" width="120" align="center">
              <template #default="{ row }">
                <span v-if="row.current_count > 0">{{ row.current_rate ?? 0 }}%</span>
                <span v-else class="td-muted">—</span>
              </template>
            </el-table-column>
            <el-table-column label="公司名提及率" width="120" align="center">
              <template #default="{ row }">
                <span v-if="row.current_count > 0">{{ row.current_company_rate ?? 0 }}%</span>
                <span v-else class="td-muted">—</span>
              </template>
            </el-table-column>
          </el-table-column>
          <el-table-column label="变化" width="100" align="center">
            <template #default="{ row }">
              <span v-if="row.delta !== null && row.delta !== undefined"
                :class="row.delta >= 0 ? 'delta-up' : 'delta-down'">
                {{ row.delta >= 0 ? '+' : '' }}{{ row.delta }}pp
              </span>
              <span v-else class="td-muted">—</span>
            </template>
          </el-table-column>
          <el-table-column label="样本" width="110" align="center">
            <template #default="{ row }">
              <span class="td-muted">{{ row.baseline_count }} / {{ row.current_count }}</span>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 按问题类型 -->
      <el-tab-pane label="按问题类型" name="question_type">
        <el-table :data="byQuestionType" stripe size="small" style="width: 100%">
          <el-table-column prop="label" label="问题类型" width="130" fixed />
          <el-table-column label="使用前" align="center">
            <el-table-column label="关键词命中率" width="120" align="center">
              <template #default="{ row }">{{ row.baseline_rate ?? 0 }}%</template>
            </el-table-column>
            <el-table-column label="公司名提及率" width="120" align="center">
              <template #default="{ row }">{{ row.baseline_company_rate ?? 0 }}%</template>
            </el-table-column>
          </el-table-column>
          <el-table-column label="使用后" align="center">
            <el-table-column label="关键词命中率" width="120" align="center">
              <template #default="{ row }">
                <span v-if="row.current_count > 0">{{ row.current_rate ?? 0 }}%</span>
                <span v-else class="td-muted">—</span>
              </template>
            </el-table-column>
            <el-table-column label="公司名提及率" width="120" align="center">
              <template #default="{ row }">
                <span v-if="row.current_count > 0">{{ row.current_company_rate ?? 0 }}%</span>
                <span v-else class="td-muted">—</span>
              </template>
            </el-table-column>
          </el-table-column>
          <el-table-column label="样本" width="110" align="center">
            <template #default="{ row }">
              <span class="td-muted">{{ row.baseline_count }} / {{ row.current_count }}</span>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 按关键词 -->
      <el-tab-pane label="按关键词" name="keyword">
        <el-table :data="byKeyword" stripe size="small" style="width: 100%" max-height="420">
          <el-table-column prop="keyword" label="关键词" min-width="200" show-overflow-tooltip fixed />
          <el-table-column label="使用前" align="center">
            <el-table-column label="关键词命中率" width="110" align="center">
              <template #default="{ row }">{{ row.baseline_rate ?? 0 }}%</template>
            </el-table-column>
            <el-table-column label="公司名提及率" width="110" align="center">
              <template #default="{ row }">{{ row.baseline_company_rate ?? 0 }}%</template>
            </el-table-column>
          </el-table-column>
          <el-table-column label="使用后" align="center">
            <el-table-column label="关键词命中率" width="110" align="center">
              <template #default="{ row }">
                <span v-if="row.current_count > 0">{{ row.current_rate ?? 0 }}%</span>
                <span v-else class="td-muted">—</span>
              </template>
            </el-table-column>
            <el-table-column label="公司名提及率" width="110" align="center">
              <template #default="{ row }">
                <span v-if="row.current_count > 0">{{ row.current_company_rate ?? 0 }}%</span>
                <span v-else class="td-muted">—</span>
              </template>
            </el-table-column>
          </el-table-column>
          <el-table-column label="样本" width="100" align="center">
            <template #default="{ row }">
              <span class="td-muted">{{ row.baseline_count }} / {{ row.current_count }}</span>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 趋势 -->
      <el-tab-pane label="趋势" name="trend">
        <div ref="trendChartRef" class="trend-chart-container" v-show="props.trend && props.trend.length > 0" />
        <div v-if="!props.trend || props.trend.length === 0" class="empty-hint">
          暂无趋势数据，请先执行使用后复测。
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 优化建议 -->
    <div v-if="recommendations && recommendations.length > 0" class="recommendations">
      <h4 class="rec-title">优化建议</h4>
      <ul class="rec-list">
        <li v-for="(rec, idx) in recommendations" :key="idx" class="rec-item">
          <span class="rec-bullet">💡</span>
          <span class="rec-text">{{ rec }}</span>
        </li>
      </ul>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick, onMounted, onUnmounted } from 'vue'
import * as echarts from 'echarts'

interface PlatformItem {
  platform: string; platform_name: string
  baseline_rate: number; current_rate: number
  baseline_company_rate: number; current_company_rate: number
  delta: number | null; baseline_count: number; current_count: number
}

interface QuestionTypeItem {
  question_type: string; label: string
  baseline_rate: number; current_rate: number
  baseline_company_rate: number; current_company_rate: number
  baseline_count: number; current_count: number
}

interface KeywordItem {
  keyword_id: number; keyword: string
  baseline_rate: number; current_rate: number
  baseline_company_rate: number; current_company_rate: number
  baseline_count: number; current_count: number
}

interface TrendPoint {
  date: string; check_count: number
  keyword_hit_rate: number; company_hit_rate: number
  visibility_score: number
}

const props = defineProps<{
  byPlatform: PlatformItem[]
  byQuestionType: QuestionTypeItem[]
  byKeyword: KeywordItem[]
  trend: TrendPoint[]
  recommendations: string[]
}>()

const activeTab = ref('platform')
const trendChartRef = ref<HTMLElement | null>(null)
let chartInstance: echarts.ECharts | null = null

const renderTrendChart = () => {
  if (!trendChartRef.value || !props.trend || props.trend.length === 0) return
  if (chartInstance) chartInstance.dispose()
  chartInstance = echarts.init(trendChartRef.value)

  const dates = props.trend.map(d => d.date)
  const kwRates = props.trend.map(d => d.keyword_hit_rate)
  const coRates = props.trend.map(d => d.company_hit_rate)
  const vsScores = props.trend.map(d => d.visibility_score)

  chartInstance.setOption({
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(255,253,247,0.96)',
      borderColor: '#c4b9a3',
      textStyle: { color: '#43392a' }
    },
    legend: {
      data: ['AI可见度指数', '关键词命中率', '公司名提及率'],
      textStyle: { color: '#8a7d68', fontSize: 12 }
    },
    grid: { left: '3%', right: '4%', bottom: '3%', top: 40, containLabel: true },
    xAxis: {
      type: 'category', boundaryGap: false, data: dates,
      axisLabel: { color: '#8a7d68', fontSize: 11 },
      axisLine: { lineStyle: { color: 'rgba(74,53,24,0.14)' } }
    },
    yAxis: {
      type: 'value', name: '%', max: 100,
      axisLabel: { color: '#8a7d68', formatter: '{value}' },
      splitLine: { lineStyle: { type: 'dashed', color: 'rgba(74,53,24,0.09)' } }
    },
    series: [
      {
        name: 'AI可见度指数', type: 'line', data: vsScores,
        smooth: true, lineStyle: { width: 3, color: '#c4741c' },
        itemStyle: { color: '#c4741c' }, symbol: 'circle', symbolSize: 6
      },
      {
        name: '关键词命中率', type: 'line', data: kwRates,
        smooth: true, lineStyle: { width: 2, color: '#3f8a52' },
        itemStyle: { color: '#3f8a52' }, symbol: 'diamond', symbolSize: 5
      },
      {
        name: '公司名提及率', type: 'line', data: coRates,
        smooth: true, lineStyle: { width: 2, color: '#1f7a92' },
        itemStyle: { color: '#1f7a92' }, symbol: 'triangle', symbolSize: 6
      }
    ]
  })
}

watch(activeTab, async (tab) => {
  if (tab === 'trend') {
    await nextTick()
    setTimeout(renderTrendChart, 100)
  }
})

const handleResize = () => { if (chartInstance) chartInstance.resize() }

onMounted(() => window.addEventListener('resize', handleResize))
onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  if (chartInstance) chartInstance.dispose()
})
</script>

<style scoped>
.breakdown-section {
  background: var(--surface-raised);
  border: 1px solid var(--border-thin);
  border-radius: var(--radius-lg);
  padding: 20px 24px;
  margin-bottom: 20px;
  box-shadow: var(--shadow-sm);
  transition: border-color var(--duration-fast) var(--ease-out);
}
.breakdown-section:hover {
  border-color: var(--border-soft);
}

.section-header-row {
  margin-bottom: 16px;
}
.section-title {
  font-family: var(--font-display);
  font-size: 16px;
  font-weight: 600;
  margin: 0;
  color: var(--text-head);
}

/* Table styling — inherit from global index.scss */
.td-muted { color: var(--text-muted); font-size: 12px; }
.delta-up { color: var(--success); font-weight: 600; }
.delta-down { color: var(--danger); font-weight: 600; }

/* Sub-header for grouped columns */
:deep(.el-table__header) .el-table__cell {
  font-size: 11px !important;
}

.trend-chart-container { width: 100%; height: 350px; }
.empty-hint { padding: 40px 0; text-align: center; color: var(--text-muted); font-size: 14px; }

/* Recommendations */
.recommendations {
  margin-top: 20px;
  padding: 16px 20px;
  background: rgba(196, 116, 28, 0.05);
  border: 1px solid rgba(196, 116, 28, 0.12);
  border-radius: var(--radius-md);
}
.rec-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-head);
  margin-bottom: 10px;
}
.rec-list { list-style: none; padding: 0; margin: 0; }
.rec-item {
  padding: 6px 0;
  font-size: 13px;
  color: var(--text-body);
  display: flex;
  align-items: flex-start;
  gap: 8px;
  line-height: 1.6;
}
.rec-bullet { flex-shrink: 0; font-size: 14px; margin-top: 1px; }
.rec-text { flex: 1; }

@media (max-width: 768px) {
  .breakdown-section { padding: 14px 12px; }
  .trend-chart-container { height: 260px; }
}
</style>
