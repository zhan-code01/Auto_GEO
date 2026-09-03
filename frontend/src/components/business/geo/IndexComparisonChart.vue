<template>
  <div class="comparison-chart-section">
    <div class="section-header">
      <h3 class="section-title">平台收录对比</h3>
      <span class="section-hint">使用前(基线) vs 使用后(当前) 命中率对比</span>
    </div>
    <div v-if="hasData" ref="chartRef" class="chart-container" />
    <div v-else class="empty-chart">
      <span class="empty-text">暂无平台对比数据，请先建立基线并完成复测</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick, onMounted, onUnmounted, computed } from 'vue'
import * as echarts from 'echarts'

interface PlatformItem {
  platform: string
  platform_name: string
  baseline_rate: number
  current_rate: number
  baseline_company_rate: number
  current_company_rate: number
  delta: number | null
  baseline_count: number
  current_count: number
}

const props = defineProps<{
  byPlatform: PlatformItem[]
}>()

const chartRef = ref<HTMLElement | null>(null)
let chartInstance: echarts.ECharts | null = null

const hasData = computed(() =>
  props.byPlatform && props.byPlatform.some(p => p.baseline_count > 0 || p.current_count > 0)
)

const renderChart = () => {
  if (!chartRef.value || !hasData.value) return

  if (chartInstance) chartInstance.dispose()
  chartInstance = echarts.init(chartRef.value)

  const platforms = props.byPlatform.map(p => p.platform_name)
  const baselineRates = props.byPlatform.map(p => p.baseline_rate ?? 0)
  const currentRates = props.byPlatform.map(p => p.current_count > 0 ? (p.current_rate ?? 0) : null)

  chartInstance.setOption({
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: 'rgba(255,253,247,0.96)',
      borderColor: 'var(--border-soft, #c4b9a3)',
      textStyle: { color: '#43392a' },
      formatter: (params: any) => {
        let html = `<div style="font-weight:600;margin-bottom:6px">${params[0].axisValue}</div>`
        params.forEach((p: any) => {
          if (p.value !== null && p.value !== undefined) {
            html += `<div style="display:flex;align-items:center;gap:6px;margin:3px 0">
              <span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:${p.color}"></span>
              ${p.seriesName}：<b>${p.value}%</b>
            </div>`
          }
        })
        return html
      }
    },
    legend: {
      data: ['使用前(基线)', '使用后(当前)'],
      top: 0,
      right: 0,
      textStyle: { color: '#8a7d68', fontSize: 12 }
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '3%',
      top: 40,
      containLabel: true
    },
    xAxis: {
      type: 'category',
      data: platforms,
      axisLabel: {
        color: '#8a7d68',
        fontSize: 13,
        fontWeight: 500
      },
      axisLine: { lineStyle: { color: 'rgba(74,53,24,0.14)' } },
      axisTick: { show: false }
    },
    yAxis: {
      type: 'value',
      name: '命中率',
      nameTextStyle: { color: '#8a7d68', fontSize: 11 },
      axisLabel: {
        color: '#8a7d68',
        formatter: '{value}%'
      },
      splitLine: {
        lineStyle: { type: 'dashed', color: 'rgba(74,53,24,0.09)' }
      },
      axisLine: { show: false },
      axisTick: { show: false }
    },
    series: [
      {
        name: '使用前(基线)',
        type: 'bar',
        barWidth: '28%',
        data: baselineRates,
        itemStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: '#b8ad99' },
            { offset: 1, color: '#d6cfbf' }
          ]),
          borderRadius: [4, 4, 0, 0]
        },
        emphasis: {
          itemStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: '#8a7d68' },
              { offset: 1, color: '#b8ad99' }
            ])
          }
        }
      },
      {
        name: '使用后(当前)',
        type: 'bar',
        barWidth: '28%',
        data: currentRates,
        itemStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: '#3f8a52' },
            { offset: 1, color: '#6bb87a' }
          ]),
          borderRadius: [4, 4, 0, 0]
        },
        emphasis: {
          itemStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: '#2d6a3e' },
              { offset: 1, color: '#3f8a52' }
            ])
          }
        }
      }
    ]
  })
}

const handleResize = () => { if (chartInstance) chartInstance.resize() }

watch(() => props.byPlatform, async () => {
  await nextTick()
  setTimeout(renderChart, 80)
}, { deep: true })

onMounted(() => {
  window.addEventListener('resize', handleResize)
  if (hasData.value) {
    nextTick(() => setTimeout(renderChart, 100))
  }
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  if (chartInstance) {
    chartInstance.dispose()
    chartInstance = null
  }
})
</script>

<style scoped>
.comparison-chart-section {
  background: var(--surface-raised);
  border: 1px solid var(--border-thin);
  border-radius: var(--radius-lg);
  padding: 22px 24px;
  margin-bottom: 20px;
  box-shadow: var(--shadow-sm);
  transition: border-color var(--duration-fast) var(--ease-out),
              box-shadow var(--duration-fast) var(--ease-out);
}
.comparison-chart-section:hover {
  border-color: var(--border-soft);
  box-shadow: var(--shadow-md);
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 16px;
}
.section-title {
  font-family: var(--font-display);
  font-size: 16px;
  font-weight: 600;
  color: var(--text-head);
  margin: 0;
}
.section-hint {
  font-size: 12px;
  color: var(--text-muted);
}

.chart-container {
  width: 100%;
  height: 300px;
}

.empty-chart {
  padding: 40px 0;
  text-align: center;
}
.empty-text {
  font-size: 14px;
  color: var(--text-muted);
}
</style>
