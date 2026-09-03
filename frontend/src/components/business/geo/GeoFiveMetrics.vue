<template>
  <div class="geo-metrics">
    <div v-if="isEmpty" class="empty-state">
      <div class="empty-title">{{ t.emptyTitle }}</div>
      <div class="empty-desc">{{ errorMessage || t.emptyDesc }}</div>
    </div>

    <template v-else>
      <div class="metrics-grid">
        <div class="metric-card hero-card">
          <div class="card-inner">
            <div class="card-label">{{ t.visibility }}</div>
            <div class="hero-value">
              {{ fmtScore(displayCurrent.visibility_score) }}
              <span class="hero-unit">{{ t.point }}</span>
            </div>
            <div class="card-delta" v-if="delta">
              <span class="delta-before">{{ t.baseline }} {{ fmtScore(baseline?.visibility_score ?? delta.visibility_score_before) }}</span>
              <span class="delta-arrow">→</span>
              <span class="delta-after">{{ fmtScore(delta.visibility_score_after) }}</span>
              <span class="delta-chip" :class="deltaClass(delta.visibility_score_delta)">
                {{ fmtDelta(delta.visibility_score_delta) }}
              </span>
            </div>
            <div class="card-verdict" v-if="delta?.verdict">
              <el-tag :type="verdictType(delta.verdict)" size="small" effect="dark">
                {{ delta.verdict }}
              </el-tag>
            </div>
          </div>
        </div>

        <div class="metric-card">
          <div class="card-inner">
            <div class="card-label">{{ t.coverage }}</div>
            <div class="card-value">{{ fmtPct(displayCurrent.coverage_rate) }}</div>
            <div class="card-baseline">{{ t.baseline }} {{ fmtPct(baseline?.coverage_rate) }}</div>
            <div class="card-delta" v-if="delta">
              <span class="chip" :class="deltaClass(delta.coverage_pp)">
                {{ fmtDelta(delta.coverage_pp) }}pp
              </span>
            </div>
            <div class="card-sub">{{ t.coverageSub }}</div>
          </div>
        </div>

        <div class="metric-card">
          <div class="card-inner">
            <div class="card-label">{{ t.ranking }}</div>
            <div class="card-value">{{ fmtScore(displayCurrent.ranking_score) }}</div>
            <div class="card-baseline">{{ t.baseline }} {{ fmtScore(baseline?.ranking_score) }}</div>
            <div class="card-delta" v-if="delta">
              <span class="chip" :class="deltaClass(delta.ranking_score_delta)">
                {{ fmtDelta(delta.ranking_score_delta) }}{{ t.point }}
              </span>
            </div>
            <div class="card-sub">{{ t.rankingSub }}</div>
          </div>
        </div>

        <div class="metric-card">
          <div class="card-inner">
            <div class="card-label">{{ t.sentiment }}</div>
            <div class="card-value">{{ fmtScore(displayCurrent.sentiment_score) }}</div>
            <div class="card-baseline">{{ t.baseline }} {{ fmtScore(baseline?.sentiment_score) }}</div>
            <div class="card-delta" v-if="delta">
              <span class="chip" :class="deltaClass(delta.sentiment_score_delta)">
                {{ fmtDelta(delta.sentiment_score_delta) }}{{ t.point }}
              </span>
            </div>
            <div class="card-sub">{{ t.sentimentSub }}</div>
          </div>
        </div>
      </div>

      <div class="metrics-footer">
        <span class="footer-item">
          <strong>{{ hasCurrentData ? t.currentSample : t.beforeSample }}</strong>
          {{ displayCurrent.valid_count ?? displayCurrent.answer_count ?? 0 }} {{ t.answers }}
        </span>
        <span class="footer-divider">|</span>
        <span class="footer-item">
          <strong>{{ t.baselineSample }}</strong>{{ baseline?.valid_count ?? baseline?.answer_count ?? 0 }} {{ t.answers }}
        </span>
        <span class="footer-divider">|</span>
        <span class="footer-item">
          <strong>{{ t.window }}</strong>{{ t.recent }} {{ current?.window_days ?? 7 }} {{ t.days }}
        </span>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

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

const props = defineProps<{
  baseline: AggBlock | null
  current: AggBlock
  delta: DeltaBlock | null
  errorMessage?: string
}>()

const t = {
  emptyTitle: '\u6682\u65e0\u6d4b\u8bc4\u6570\u636e',
  emptyDesc: '\u8bf7\u5148\u751f\u6210\u95ee\u9898\u96c6\u5e76\u5efa\u7acb\u57fa\u7ebf\uff0c\u7cfb\u7edf\u5c06\u5728\u8fd9\u91cc\u5c55\u793a GEO \u6d4b\u8bc4\u6548\u679c\u3002',
  visibility: 'AI \u53ef\u89c1\u5ea6',
  coverage: '\u51fa\u73b0\u8986\u76d6\u7387',
  ranking: '\u63a8\u8350\u6392\u540d',
  sentiment: '\u60c5\u611f\u5206',
  baseline: '\u57fa\u7ebf',
  point: '\u5206',
  coverageSub: '\u54c1\u724c\u88ab\u63d0\u53ca\u7684\u56de\u7b54\u6bd4\u4f8b',
  rankingSub: 'AI \u63a8\u8350\u4f4d\u6b21\u7efc\u5408\u5f97\u5206',
  sentimentSub: '\u54c1\u724c\u88ab\u63d0\u53ca\u65f6\u7684\u60c5\u611f\u503e\u5411',
  currentSample: '\u5f53\u524d\u6837\u672c\uff1a',
  beforeSample: '\u4f7f\u7528\u524d\u6837\u672c\uff1a',
  baselineSample: '\u57fa\u7ebf\u6837\u672c\uff1a',
  answers: '\u6761\u56de\u7b54',
  window: '\u7edf\u8ba1\u7a97\u53e3\uff1a',
  recent: '\u6700\u8fd1',
  days: '\u5929',
}

const hasCurrentData = computed(() => !!(props.current?.answer_count || props.current?.valid_count))
const hasBaselineData = computed(() => !!(props.baseline?.answer_count || props.baseline?.valid_count))

const displayCurrent = computed<AggBlock>(() => {
  if (hasCurrentData.value) return props.current
  if (props.baseline && hasBaselineData.value) {
    return { ...props.baseline, window_days: props.current?.window_days ?? 7 }
  }
  return props.current
})

const isEmpty = computed(() => !hasCurrentData.value && !hasBaselineData.value)

const fmtScore = (v: number | null | undefined): string => {
  if (v === null || v === undefined) return '-'
  return Number(v).toFixed(0)
}

const fmtPct = (v: number | null | undefined): string => {
  if (v === null || v === undefined) return '-'
  return `${Number(v).toFixed(1)}%`
}

const fmtDelta = (v: number | null | undefined): string => {
  if (v === null || v === undefined) return '-'
  return v >= 0 ? `+${Number(v).toFixed(1)}` : Number(v).toFixed(1)
}

const deltaClass = (v: number | null | undefined): string => {
  if (v === null || v === undefined) return 'muted'
  if (v >= 3) return 'up'
  if (v >= -3) return 'flat'
  return 'down'
}

type TagType = 'primary' | 'success' | 'warning' | 'info' | 'danger'

const verdictType = (v: string): TagType => {
  if (v === '\u663e\u8457\u63d0\u5347') return 'success'
  if (v === '\u8f7b\u5fae\u63d0\u5347') return 'primary'
  if (v === '\u57fa\u672c\u6301\u5e73') return 'info'
  if (v === '\u4e0b\u964d') return 'danger'
  return 'warning'
}
</script>

<style scoped>
.geo-metrics { margin-bottom: 20px; }
.empty-state {
  background: var(--surface-raised);
  border: 1px solid var(--border-thin);
  border-radius: var(--radius-lg);
  padding: 56px 32px;
  text-align: center;
}
.empty-title { font-size: 16px; font-weight: 600; color: var(--text-head); margin-bottom: 8px; }
.empty-desc { font-size: 13px; color: var(--text-muted); line-height: 1.6; }
.metrics-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 14px;
}
.metric-card {
  position: relative;
  background: var(--surface-raised);
  border: 1px solid var(--border-thin);
  border-radius: var(--radius-lg);
  overflow: hidden;
  transition: border-color var(--duration-fast) var(--ease-out),
              box-shadow var(--duration-fast) var(--ease-out),
              transform var(--duration-fast) var(--ease-out);
}
.metric-card:hover {
  border-color: var(--border-soft);
  box-shadow: var(--shadow-md);
  transform: translateY(-1px);
}
.hero-card {
  border-left: 4px solid var(--success);
  background: linear-gradient(135deg, var(--surface-raised), rgba(94, 168, 120, 0.04));
}
.card-inner {
  position: relative;
  min-height: 160px;
  padding: 18px 16px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.card-label { font-size: 12px; font-weight: 600; color: var(--text-muted); }
.hero-value {
  font-family: var(--font-display);
  font-size: 42px;
  font-weight: 800;
  color: var(--success);
  line-height: 1;
}
.hero-unit { font-size: 16px; font-weight: 600; color: var(--text-muted); margin-left: 2px; }
.card-value {
  font-family: var(--font-display);
  font-size: 28px;
  font-weight: 700;
  color: var(--text-head);
  line-height: 1.1;
}
.card-baseline { font-size: 12px; color: var(--text-muted); }
.card-delta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  flex-wrap: wrap;
}
.delta-before { color: var(--text-muted); }
.delta-arrow { color: var(--text-disabled); }
.delta-after { color: var(--text-body); font-weight: 600; }
.delta-chip,
.chip {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 12px;
  font-weight: 700;
}
.chip.up, .delta-chip.up { color: var(--success); background: var(--success-soft); }
.chip.flat, .delta-chip.flat { color: var(--text-muted); background: rgba(138, 125, 104, 0.06); }
.chip.down, .delta-chip.down { color: var(--danger); background: var(--danger-soft); }
.chip.muted, .delta-chip.muted { color: var(--text-disabled); }
.card-verdict { margin-top: 4px; }
.card-sub { font-size: 11px; color: var(--text-muted); margin-top: auto; }
.metrics-footer {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 12px 20px;
  background: var(--surface-field);
  border: 1px solid var(--border-thin);
  border-radius: var(--radius-sm);
  font-size: 13px;
  flex-wrap: wrap;
}
.footer-item { color: var(--text-body); }
.footer-item strong { color: var(--text-head); font-weight: 600; }
.footer-divider { color: var(--border-soft); }
@media (max-width: 1200px) {
  .metrics-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 640px) {
  .metrics-grid { grid-template-columns: 1fr; }
}
</style>
