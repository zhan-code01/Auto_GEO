<template>
  <div class="geo-metric-chart">
    <div class="chart-header">
      <div>
        <h3 class="chart-title">{{ t.title }}</h3>
        <p class="chart-subtitle">{{ t.subtitle }}</p>
      </div>
      <el-tag v-if="verdict" :type="verdictType(verdict)" size="small" effect="plain">
        {{ verdict }}
      </el-tag>
    </div>

    <div v-if="hasData" ref="chartRef" class="chart-container" />
    <div v-else class="empty-chart">
      <div class="empty-icon">□</div>
      <div class="empty-title">{{ t.emptyTitle }}</div>
      <div class="empty-desc">{{ t.emptyDesc }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

interface AggBlock {
  coverage_rate?: number
  ranking_score?: number
  sentiment_score?: number
  visibility_score?: number
  valid_count?: number
  answer_count?: number
}

interface DeltaBlock {
  verdict?: string
}

const props = defineProps<{
  baseline: AggBlock | null
  current: AggBlock | null
  delta?: DeltaBlock | null
}>()

const t = {
  title: '\u6307\u6807\u4f7f\u7528\u524d\u540e\u5bf9\u6bd4',
  subtitle: '\u76f4\u89c2\u770b\u5230\u57fa\u7ebf\u4e0e\u5f53\u524d\u6d4b\u8bc4\u7ed3\u679c\u7684\u5dee\u5f02',
  emptyTitle: '\u6682\u65e0\u53ef\u5bf9\u6bd4\u6570\u636e',
  emptyDesc: '\u751f\u6210\u95ee\u9898\u96c6\u5e76\u5efa\u7acb\u57fa\u7ebf\u540e\uff0c\u7cfb\u7edf\u4f1a\u5728\u8fd9\u91cc\u5c55\u793a\u6307\u6807\u5dee\u5f02\u3002',
  before: '\u4f7f\u7528\u524d',
  after: '\u4f7f\u7528\u540e',
  change: '\u53d8\u5316',
  visibility: 'AI\u53ef\u89c1\u5ea6',
  coverage: '\u51fa\u73b0\u8986\u76d6\u7387',
  ranking: '\u63a8\u8350\u6392\u540d',
  sentiment: '\u60c5\u611f\u5206',
  point: '\u5206',
}

const chartRef = ref<HTMLElement | null>(null)
let chartInstance: echarts.ECharts | null = null

const hasCurrentData = computed(() => !!(props.current?.answer_count || props.current?.valid_count))

const valueOf = (v: number | null | undefined): number => {
  return v === null || v === undefined ? 0 : Number(v)
}

const currentValueOf = (v: number | null | undefined): number | null => {
  if (!hasCurrentData.value) return null
  return valueOf(v)
}

const metricRows = computed(() => [
  { label: t.visibility, baseline: valueOf(props.baseline?.visibility_score), current: currentValueOf(props.current?.visibility_score), unit: t.point },
  { label: t.coverage, baseline: valueOf(props.baseline?.coverage_rate), current: currentValueOf(props.current?.coverage_rate), unit: '%' },
  { label: t.ranking, baseline: valueOf(props.baseline?.ranking_score), current: currentValueOf(props.current?.ranking_score), unit: t.point },
  { label: t.sentiment, baseline: valueOf(props.baseline?.sentiment_score), current: currentValueOf(props.current?.sentiment_score), unit: t.point },
])

const hasData = computed(() =>
  metricRows.value.some(row =>
    (row.baseline !== null && row.baseline > 0) ||
    (row.current !== null && row.current > 0),
  ),
)

const verdict = computed(() => props.delta?.verdict || '')

function formatValue(v: number | null, unit: string): string {
  if (v === null || v === undefined) return 'N/A'
  return `${Number(v).toFixed(unit === '%' ? 1 : 0)}${unit}`
}

type TagType = 'primary' | 'success' | 'warning' | 'info' | 'danger'

function verdictType(v: string): TagType {
  if (v === '\u663e\u8457\u63d0\u5347') return 'success'
  if (v === '\u8f7b\u5fae\u63d0\u5347') return 'primary'
  if (v === '\u57fa\u672c\u6301\u5e73') return 'info'
  if (v === '\u4e0b\u964d') return 'danger'
  return 'warning'
}

function renderChart() {
  if (!chartRef.value || !hasData.value) return

  if (chartInstance) chartInstance.dispose()
  chartInstance = echarts.init(chartRef.value)

  const labels = metricRows.value.map(row => row.label)
  const baselineValues = metricRows.value.map(row => row.baseline)
  const currentValues = metricRows.value.map(row => row.current)

  chartInstance.setOption({
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: 'rgba(255,253,247,0.98)',
      borderColor: '#d8cfbe',
      textStyle: { color: '#43392a' },
      formatter: (params: any[]) => {
        const index = params[0]?.dataIndex ?? 0
        const row = metricRows.value[index]
        const before = formatValue(row.baseline, row.unit)
        const after = formatValue(row.current, row.unit)
        const diff = row.baseline === null || row.current === null ? 'N/A' : formatValue(row.current - row.baseline, row.unit)
        return `
          <div style="font-weight:600;margin-bottom:6px">${row.label}</div>
          <div>${t.before}: <b>${before}</b></div>
          <div>${t.after}: <b>${after}</b></div>
          <div>${t.change}: <b>${diff}</b></div>
        `
      },
    },
    legend: {
      data: [t.before, t.after],
      top: 0,
      right: 0,
      textStyle: { color: '#8a7d68', fontSize: 12 },
    },
    grid: {
      left: 42,
      right: 28,
      top: 42,
      bottom: 34,
      containLabel: true,
    },
    xAxis: {
      type: 'category',
      data: labels,
      axisTick: { show: false },
      axisLine: { lineStyle: { color: 'rgba(74,53,24,0.16)' } },
      axisLabel: { color: '#6f644f', fontSize: 12 },
    },
    yAxis: {
      type: 'value',
      max: 100,
      axisLabel: { color: '#8a7d68', formatter: '{value}' },
      splitLine: { lineStyle: { type: 'dashed', color: 'rgba(74,53,24,0.10)' } },
    },
    series: [
      {
        name: t.before,
        type: 'bar',
        barWidth: 22,
        data: baselineValues,
        itemStyle: { color: '#b8ad99', borderRadius: [4, 4, 0, 0] },
      },
      {
        name: t.after,
        type: 'bar',
        barWidth: 22,
        data: currentValues,
        itemStyle: { color: '#4f9c68', borderRadius: [4, 4, 0, 0] },
      },
    ],
  })
}

function handleResize() {
  chartInstance?.resize()
}

watch(
  () => [props.baseline, props.current, props.delta],
  async () => {
    await nextTick()
    setTimeout(renderChart, 60)
  },
  { deep: true },
)

onMounted(() => {
  window.addEventListener('resize', handleResize)
  nextTick(() => setTimeout(renderChart, 80))
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  chartInstance?.dispose()
  chartInstance = null
})
</script>

<style scoped>
.geo-metric-chart {
  background: var(--surface-raised);
  border: 1px solid var(--border-thin);
  border-radius: var(--radius-lg);
  padding: 20px 22px;
  margin-bottom: 20px;
  box-shadow: var(--shadow-sm);
}
.chart-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 12px;
}
.chart-title { font-size: 16px; font-weight: 700; color: var(--text-head); margin: 0; }
.chart-subtitle { margin: 4px 0 0; color: var(--text-muted); font-size: 12px; }
.chart-container { width: 100%; height: 320px; }
.empty-chart {
  min-height: 240px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  color: var(--text-muted);
}
.empty-icon { font-size: 42px; line-height: 1; margin-bottom: 12px; }
.empty-title { color: var(--text-head); font-size: 16px; font-weight: 600; margin-bottom: 6px; }
.empty-desc { font-size: 13px; }
</style>
