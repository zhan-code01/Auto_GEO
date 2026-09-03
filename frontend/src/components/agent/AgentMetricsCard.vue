<template>
  <div class="metrics-card">
    <div class="metrics-header">
      <h3 class="metrics-title">{{ title }}</h3>
      <div v-if="subtitle" class="metrics-subtitle">{{ subtitle }}</div>
    </div>

    <div class="metrics-grid">
      <div
        v-for="metric in metrics"
        :key="metric.key"
        class="metric-item"
      >
        <div class="metric-label">{{ metric.label }}</div>
        <div class="metric-value" :class="metric.color">
          {{ formatValue(metric.value, metric.format) }}
        </div>
        <div v-if="metric.baseline !== undefined" class="metric-baseline">
          基线：{{ formatValue(metric.baseline, metric.format) }}
          <span v-if="metric.delta !== undefined" class="metric-delta" :class="getDeltaClass(metric.delta)">
            {{ formatDelta(metric.delta, metric.format) }}
          </span>
        </div>
      </div>
    </div>

    <div v-if="showFooter" class="metrics-footer">
      <slot name="footer">
        <div class="footer-text">{{ footerText }}</div>
      </slot>
    </div>
  </div>
</template>

<script setup lang="ts">
interface Metric {
  key: string
  label: string
  value: number
  baseline?: number
  delta?: number
  format?: 'percent' | 'number' | 'decimal'
  color?: 'success' | 'warning' | 'danger' | 'info'
}

const props = defineProps<{
  title: string
  subtitle?: string
  metrics: Metric[]
  showFooter?: boolean
  footerText?: string
}>()

function formatValue(value: number, format: string = 'number'): string {
  if (value === null || value === undefined) return '-'

  switch (format) {
    case 'percent':
      return `${(value * 100).toFixed(1)}%`
    case 'decimal':
      return value.toFixed(2)
    case 'number':
    default:
      return value.toString()
  }
}

function formatDelta(delta: number, format: string = 'number'): string {
  const sign = delta > 0 ? '+' : ''
  const formatted = formatValue(Math.abs(delta), format)
  return `${sign}${formatted}`
}

function getDeltaClass(delta: number): string {
  if (delta > 0) return 'delta-up'
  if (delta < 0) return 'delta-down'
  return 'delta-flat'
}
</script>

<style scoped lang="scss">
.metrics-card {
  background: var(--surface-raised);
  border: 1px solid var(--border-thin);
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}

.metrics-header {
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border-thin);
}

.metrics-title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.metrics-subtitle {
  margin-top: 4px;
  font-size: 13px;
  color: var(--text-muted);
}

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
}

.metric-item {
  padding: 12px;
  background: var(--surface-field);
  border-radius: 8px;
  border: 1px solid var(--border-thin);
}

.metric-label {
  font-size: 13px;
  color: var(--text-muted);
  margin-bottom: 8px;
}

.metric-value {
  font-size: 24px;
  font-weight: 700;
  font-family: var(--font-display);
  margin-bottom: 4px;

  &.success {
    color: var(--success);
  }

  &.warning {
    color: var(--warning);
  }

  &.danger {
    color: var(--danger);
  }

  &.info {
    color: var(--info);
  }
}

.metric-baseline {
  font-size: 12px;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  gap: 8px;
}

.metric-delta {
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 11px;

  &.delta-up {
    color: var(--success);
    background: var(--success-soft);
  }

  &.delta-down {
    color: var(--danger);
    background: var(--danger-soft);
  }

  &.delta-flat {
    color: var(--text-muted);
    background: var(--surface-field);
  }
}

.metrics-footer {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid var(--border-thin);
}

.footer-text {
  font-size: 13px;
  color: var(--text-muted);
  text-align: center;
}
</style>
