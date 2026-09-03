<template>
  <div class="core-metrics">
    <!-- 无基线时：空态 -->
    <div v-if="!hasBaseline" class="empty-state">
      <div class="empty-icon">📋</div>
      <div class="empty-title">尚未建立基线快照</div>
      <div class="empty-desc">请先点击上方「生成使用前基线」，记录使用 GEO 前的收录情况</div>
    </div>

    <!-- 有基线但无复测：展示基线 + 提示 -->
    <div v-else-if="hasBaseline && !currentSufficient" class="partial-state">
      <div class="comparison-row">
        <!-- 基线卡 -->
        <div class="compare-card baseline-card">
          <div class="card-header">
            <span class="card-badge baseline-badge">使用前 · 基线</span>
          </div>
          <div class="card-body">
            <div class="metric-row">
              <span class="metric-label">关键词命中率</span>
              <span class="metric-value muted">{{ baseline.keyword_hit_rate ?? 0 }}%</span>
            </div>
            <div class="metric-row">
              <span class="metric-label">公司名提及率</span>
              <span class="metric-value muted">{{ baseline.company_hit_rate ?? 0 }}%</span>
            </div>
            <div class="metric-row">
              <span class="metric-label">平均置信度</span>
              <span class="metric-value muted">{{ formatConfidence(baseline.avg_confidence) }}</span>
            </div>
            <div class="metric-row">
              <span class="metric-label">覆盖平台</span>
              <span class="metric-value muted">{{ baseline.platform_count ?? 0 }} 个</span>
            </div>
            <div class="metric-row">
              <span class="metric-label">检测样本</span>
              <span class="metric-value muted">{{ baseline.check_count ?? 0 }} 条</span>
            </div>
          </div>
        </div>

        <!-- 中间箭头 -->
        <div class="arrow-col">
          <div class="arrow-icon">▶</div>
        </div>

        <!-- 待复测卡 -->
        <div class="compare-card pending-card">
          <div class="card-header">
            <span class="card-badge pending-badge">使用后 · 当前</span>
          </div>
          <div class="card-body pending-body">
            <div class="pending-icon">⏳</div>
            <div class="pending-text">暂无复测数据</div>
            <div class="pending-hint">请点击上方「执行使用后复测」<br />或等待系统自动复测</div>
          </div>
        </div>
      </div>

      <!-- 可见度条 -->
      <div class="visibility-bar">
        <span class="vis-label">AI 可见度指数</span>
        <span class="vis-before">{{ baseline.visibility_score ?? '—' }}</span>
        <span class="vis-arrow">→</span>
        <span class="vis-after muted">待复测</span>
      </div>
    </div>

    <!-- 完整对比：基线 vs 当前 -->
    <div v-else class="full-state">
      <div class="comparison-row">
        <!-- 基线卡 -->
        <div class="compare-card baseline-card">
          <div class="card-header">
            <span class="card-badge baseline-badge">使用前 · 基线</span>
          </div>
          <div class="card-body">
            <div class="metric-row">
              <span class="metric-label">关键词命中率</span>
              <span class="metric-value muted">{{ baseline.keyword_hit_rate ?? 0 }}%</span>
            </div>
            <div class="metric-row">
              <span class="metric-label">公司名提及率</span>
              <span class="metric-value muted">{{ baseline.company_hit_rate ?? 0 }}%</span>
            </div>
            <div class="metric-row">
              <span class="metric-label">平均置信度</span>
              <span class="metric-value muted">{{ formatConfidence(baseline.avg_confidence) }}</span>
            </div>
            <div class="metric-row">
              <span class="metric-label">覆盖平台</span>
              <span class="metric-value muted">{{ baseline.platform_count ?? 0 }} 个</span>
            </div>
            <div class="metric-row">
              <span class="metric-label">检测样本</span>
              <span class="metric-value muted">{{ baseline.check_count ?? 0 }} 条</span>
            </div>
          </div>
        </div>

        <!-- 中间变化列（只对齐两个核心指标） -->
        <div class="delta-col">
          <div class="delta-spacer"></div>
          <div class="delta-row" :class="deltaClass(delta.keyword_pp)">
            {{ ppSigned(delta.keyword_pp) }}
          </div>
          <div class="delta-row" :class="deltaClass(delta.company_pp)">
            {{ ppSigned(delta.company_pp) }}
          </div>
        </div>

        <!-- 当前卡 -->
        <div class="compare-card current-card">
          <div class="card-header">
            <span class="card-badge current-badge">使用后 · 当前</span>
          </div>
          <div class="card-body">
            <div class="metric-row">
              <span class="metric-label">关键词命中率</span>
              <span class="metric-value success">{{ current.keyword_hit_rate ?? 0 }}%</span>
            </div>
            <div class="metric-row">
              <span class="metric-label">公司名提及率</span>
              <span class="metric-value success">{{ current.company_hit_rate ?? 0 }}%</span>
            </div>
            <div class="metric-row">
              <span class="metric-label">平均置信度</span>
              <span class="metric-value success">{{ formatConfidence(current.avg_confidence) }}</span>
            </div>
            <div class="metric-row">
              <span class="metric-label">覆盖平台</span>
              <span class="metric-value success">{{ current.platform_count ?? 0 }} 个</span>
            </div>
            <div class="metric-row">
              <span class="metric-label">检测样本</span>
              <span class="metric-value success">{{ current.check_count ?? 0 }} 条</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 可见度总结条 -->
      <div class="visibility-bar">
        <span class="vis-label">AI 可见度指数</span>
        <span class="vis-before">{{ delta.visibility_score_before ?? baseline.visibility_score ?? '—' }}</span>
        <span class="vis-arrow">→</span>
        <span class="vis-after">{{ delta.visibility_score_after ?? current.visibility_score ?? '—' }}</span>
        <span class="vis-delta" :class="deltaClass(delta.visibility_score_delta)">
          {{ deltaSigned }}
        </span>
        <el-tag
          v-if="verdictTag"
          :type="verdictTag.type"
          size="default"
          effect="dark"
          class="vis-verdict"
        >
          {{ verdictTag.text }}
        </el-tag>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface AggregateBlock {
  check_count: number
  question_count: number
  platform_count: number
  platform_names?: string[]
  keyword_hit_rate: number
  company_hit_rate: number
  visibility_score: number | null
  avg_confidence: number
  keyword_avg_count: number
  company_avg_count: number
}

interface DeltaBlock {
  keyword_pp: number | null
  company_pp: number | null
  visibility_score_before: number | null
  visibility_score_after: number | null
  visibility_score_delta: number | null
  verdict: string
}

const props = defineProps<{
  hasBaseline: boolean
  currentSufficient: boolean
  baseline: AggregateBlock
  current: AggregateBlock & { window_days?: number }
  delta: DeltaBlock
}>()

const formatConfidence = (v: number | null | undefined) => {
  if (v == null) return '—'
  return (v * 100).toFixed(0) + '%'
}

const ppSigned = (v: number | null): string => {
  if (v === null || v === undefined) return '—'
  return v >= 0 ? `+${v}pp` : `${v}pp`
}

const deltaClass = (v: number | null): string => {
  if (v === null || v === undefined) return 'muted'
  if (v >= 3) return 'up'
  if (v >= -3) return 'flat'
  return 'down'
}

const deltaSigned = computed(() => {
  const v = props.delta.visibility_score_delta
  if (v === null || v === undefined) return '—'
  return v >= 0 ? `+${v} 分` : `${v} 分`
})

const verdictTag = computed(() => {
  const v = props.delta.verdict
  if (v === '显著提升') return { type: 'success' as const, text: '显著提升' }
  if (v === '轻微提升') return { type: 'primary' as const, text: '轻微提升' }
  if (v === '基本持平') return { type: 'info' as const, text: '基本持平' }
  if (v === '下降') return { type: 'danger' as const, text: '下降' }
  if (v === '样本不足') return { type: 'warning' as const, text: '样本不足' }
  return null
})
</script>

<style scoped>
.core-metrics {
  --metric-header-height: 47px;
  --metric-body-top: 16px;
  --metric-row-height: 48px;
  --metric-row-gap: 14px;
  margin-bottom: 20px;
}

/* ---- Empty State ---- */
.empty-state {
  background: var(--surface-raised);
  border: 1px solid var(--border-thin);
  border-radius: var(--radius-lg);
  padding: 60px 32px;
  text-align: center;
}
.empty-icon { font-size: 40px; margin-bottom: 12px; opacity: 0.6; }
.empty-title { font-size: 16px; font-weight: 600; color: var(--text-head); margin-bottom: 8px; }
.empty-desc { font-size: 13px; color: var(--text-muted); line-height: 1.6; }

/* ---- Comparison Row (3-col: baseline | delta | current) ---- */
.comparison-row {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  gap: 0;
  align-items: stretch;
  margin-bottom: 16px;
}

/* ---- Compare Cards ---- */
.compare-card {
  background: var(--surface-raised);
  border: 1px solid var(--border-thin);
  border-radius: var(--radius-lg);
  overflow: hidden;
  box-shadow: var(--shadow-sm);
  transition: border-color var(--duration-fast) var(--ease-out),
              box-shadow var(--duration-fast) var(--ease-out);
}
.compare-card:hover {
  border-color: var(--border-soft);
  box-shadow: var(--shadow-md);
}

.baseline-card { border-left: 4px solid var(--text-muted); }
.current-card  { border-left: 4px solid var(--success); }
.pending-card  { border-left: 4px solid var(--warning); }

.card-header {
  padding: 16px 20px 0;
  height: var(--metric-header-height);
  box-sizing: border-box;
}
.card-badge {
  display: inline-block;
  padding: 4px 14px;
  border-radius: 20px;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.02em;
}
.baseline-badge {
  background: rgba(138, 125, 104, 0.10);
  color: var(--text-muted);
}
.current-badge {
  background: var(--success-soft);
  color: var(--success);
}
.pending-badge {
  background: var(--warning-soft);
  color: var(--warning);
}

.card-body {
  padding: 16px 20px 20px;
  display: flex;
  flex-direction: column;
  gap: var(--metric-row-gap);
}
.metric-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  min-height: var(--metric-row-height);
  padding-bottom: 0;
  border-bottom: 1px solid var(--border-thin);
}
.metric-row:last-child {
  border-bottom: none;
  padding-bottom: 0;
}
.metric-label {
  font-size: 13px;
  color: var(--text-muted);
}
.metric-value {
  font-family: var(--font-display);
  font-size: 20px;
  font-weight: 700;
}
.metric-value.muted  { color: var(--text-body); }
.metric-value.success { color: var(--success); }

/* ---- Delta Column (center arrows) ---- */
.delta-col {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-start;
  padding: 0 16px;
  min-width: 80px;
}
.delta-spacer {
  height: calc(var(--metric-header-height) + var(--metric-body-top));
}
.delta-row {
  display: flex;
  align-items: center;
  justify-content: center;
  height: var(--metric-row-height);
  margin-bottom: var(--metric-row-gap);
  font-size: 15px;
  font-weight: 700;
  white-space: nowrap;
  padding: 0 10px;
  border-radius: var(--radius-sm);
  box-sizing: border-box;
}
.delta-row:last-child { margin-bottom: 0; }
.delta-row.up   { color: var(--success); background: var(--success-soft); }
.delta-row.flat { color: var(--text-muted); background: rgba(138, 125, 104, 0.06); }
.delta-row.down { color: var(--danger); background: var(--danger-soft); }
.delta-row.muted { color: var(--text-disabled); }

/* ---- Arrow Column (simplified for partial state) ---- */
.arrow-col {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 20px;
}
.arrow-icon {
  font-size: 24px;
  color: var(--text-disabled);
  background: var(--surface-field);
  width: 48px;
  height: 48px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* ---- Pending Body ---- */
.pending-body {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 200px;
  text-align: center;
  gap: 8px;
}
.pending-icon { font-size: 32px; opacity: 0.5; }
.pending-text { font-size: 15px; font-weight: 600; color: var(--text-body); }
.pending-hint { font-size: 12px; color: var(--text-muted); line-height: 1.6; }

/* ---- Visibility Summary Bar ---- */
.visibility-bar {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 18px 24px;
  background: linear-gradient(135deg, var(--surface-field), rgba(255, 253, 247, 0.8));
  border: 1px solid var(--border-thin);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  flex-wrap: wrap;
}
.vis-label {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-head);
  font-family: var(--font-display);
}
.vis-before {
  font-family: var(--font-display);
  font-size: 28px;
  font-weight: 700;
  color: var(--text-muted);
}
.vis-arrow {
  font-size: 20px;
  color: var(--text-disabled);
}
.vis-after {
  font-family: var(--font-display);
  font-size: 32px;
  font-weight: 800;
  color: var(--success);
}
.vis-after.muted {
  font-size: 16px;
  font-weight: 500;
  color: var(--text-muted);
}
.vis-delta {
  font-size: 15px;
  font-weight: 700;
  padding: 3px 12px;
  border-radius: var(--radius-sm);
}
.vis-delta.up   { color: var(--success); background: var(--success-soft); }
.vis-delta.flat { color: var(--text-muted); background: rgba(138, 125, 104, 0.06); }
.vis-delta.down { color: var(--danger); background: var(--danger-soft); }
.vis-delta.muted { color: var(--text-disabled); }
.vis-verdict {
  margin-left: 4px;
}

/* ---- Responsive ---- */
@media (max-width: 768px) {
  .comparison-row {
    grid-template-columns: 1fr;
    gap: 12px;
  }
  .delta-col {
    flex-direction: row;
    gap: 12px;
    padding: 8px 0;
    min-width: unset;
  }
  .delta-spacer { display: none; }
  .delta-row { margin-bottom: 0; }
  .arrow-col { padding: 12px 0; }
  .arrow-icon { transform: rotate(90deg); }
  .vis-before { font-size: 22px; }
  .vis-after  { font-size: 26px; }
}
</style>
