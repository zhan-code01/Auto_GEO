<template>
  <div class="geo-competitor-analysis">
    <div class="gca-header">
      <div>
        <h3 class="gca-title">竞品与来源分析</h3>
        <p class="gca-subtitle">基于测评判卷提取的品牌提及与引用来源数据聚合</p>
      </div>
      <div class="gca-controls">
        <el-select v-model="phaseFilter" size="small" style="width: 110px" @change="load">
          <el-option label="全部阶段" value="" />
          <el-option label="使用前" value="baseline" />
          <el-option label="使用后" value="ongoing" />
        </el-select>
        <el-button size="small" :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>

    <div v-if="error" class="gca-empty">
      <div class="empty-icon">!</div>
      <div class="empty-title">{{ error }}</div>
    </div>

    <template v-else>
      <div v-if="!data" v-loading="loading" class="gca-empty" style="min-height: 120px" />

      <template v-else-if="data.total_records > 0">
        <div class="gca-summary">
          <div class="summary-item">
            <div class="summary-value">{{ data.total_records }}</div>
            <div class="summary-label">有效测评回答</div>
          </div>
          <div class="summary-item">
            <div class="summary-value highlight">{{ data.own_source_rate }}%</div>
            <div class="summary-label">自有来源引用率</div>
          </div>
          <div class="summary-item">
            <div class="summary-value">{{ data.own_source_cited_count }}</div>
            <div class="summary-label">引用我方来源次数</div>
          </div>
          <div class="summary-item" v-if="data.own_domain">
            <div class="summary-value small">{{ data.own_domain }}</div>
            <div class="summary-label">我方域名</div>
          </div>
        </div>

        <div class="gca-sections">
          <div class="gca-section">
            <div class="section-title">品牌提及份额</div>
            <el-table :data="data.brand_shares" size="small" max-height="320" empty-text="暂无品牌提及记录">
              <el-table-column label="品牌" min-width="140">
                <template #default="{ row }">
                  <span :class="{ 'own-name': row.is_own, 'comp-name': row.is_competitor }">
                    {{ row.name }}
                  </span>
                  <el-tag v-if="row.is_own" size="small" type="success" effect="plain" class="mini-tag">我方</el-tag>
                  <el-tag v-else-if="row.is_competitor" size="small" type="warning" effect="plain" class="mini-tag">竞品</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="mentions" label="提及次数" width="90" />
              <el-table-column label="提及份额" width="160">
                <template #default="{ row }">
                  <div class="bar-wrap">
                    <div class="bar" :style="{ width: barWidth(row.share), background: row.is_own ? '#67c23a' : '#a0cfff' }" />
                    <span class="bar-text">{{ row.share }}%</span>
                  </div>
                </template>
              </el-table-column>
            </el-table>
            <div v-if="data.competitor_watchlist.length" class="watchlist">
              观察名单：{{ data.competitor_watchlist.join('、') }}
            </div>
          </div>

          <div class="gca-section">
            <div class="section-title">AI 引用域名榜</div>
            <el-table :data="data.top_domains" size="small" max-height="320" empty-text="回答中未提取到引用来源">
              <el-table-column label="域名" min-width="170">
                <template #default="{ row }">
                  <span :class="{ 'own-name': row.is_own }">{{ row.domain }}</span>
                  <el-tag v-if="row.is_own" size="small" type="success" effect="plain" class="mini-tag">我方</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="citations" label="被引次数" width="90" />
              <el-table-column label="出现率" width="160">
                <template #default="{ row }">
                  <div class="bar-wrap">
                    <div class="bar" :style="{ width: barWidth(row.share), background: row.is_own ? '#67c23a' : '#a0cfff' }" />
                    <span class="bar-text">{{ row.share }}%</span>
                  </div>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </div>

        <div v-if="data.by_platform.length" class="gca-platforms">
          <div class="section-title">分平台概览</div>
          <div class="platform-cards">
            <div v-for="p in data.by_platform" :key="p.platform" class="platform-card">
              <div class="platform-head">
                <strong>{{ p.platform_name }}</strong>
                <span class="muted">{{ p.total }} 条</span>
              </div>
              <div class="platform-metric">
                自有来源引用率 <b>{{ p.own_source_rate }}%</b>
              </div>
              <div class="platform-line" v-if="p.top_names.length">
                高频品牌：{{ p.top_names.slice(0, 3).map(n => n.name).join('、') }}
              </div>
              <div class="platform-line" v-if="p.top_domains.length">
                高频域名：{{ p.top_domains.slice(0, 3).map(d => d.domain).join('、') }}
              </div>
            </div>
          </div>
        </div>
      </template>

      <div v-else class="gca-empty">
        <div class="empty-icon">□</div>
        <div class="empty-title">暂无测评数据</div>
        <div class="empty-desc">建立基线或执行复测后，这里会展示竞品提及份额与引用来源分析。</div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { geoEvaluationApi } from '@/services/api'

interface BrandShare {
  name: string
  mentions: number
  share: number
  is_own: boolean
  is_competitor: boolean
}

interface DomainRow {
  domain: string
  citations: number
  share: number
  is_own: boolean
}

interface PlatformBlock {
  platform: string
  platform_name: string
  total: number
  own_source_cited: number
  own_source_rate: number
  top_names: BrandShare[]
  top_domains: { domain: string; citations: number }[]
}

interface CompetitorAnalysis {
  client_id: number
  company_name: string
  own_domain: string | null
  competitor_watchlist: string[]
  total_records: number
  own_source_cited_count: number
  own_source_rate: number
  brand_shares: BrandShare[]
  top_domains: DomainRow[]
  by_platform: PlatformBlock[]
}

const props = defineProps<{
  clientId: number | null
  platform?: string
}>()

const loading = ref(false)
const error = ref('')
const data = ref<CompetitorAnalysis | null>(null)
const phaseFilter = ref('')

const load = async () => {
  if (!props.clientId) {
    data.value = null
    error.value = ''
    return
  }
  loading.value = true
  error.value = ''
  try {
    const params: Record<string, any> = {}
    if (phaseFilter.value) params.phase = phaseFilter.value
    if (props.platform) params.platform = props.platform
    const res = await geoEvaluationApi.getClientCompetitorAnalysis(props.clientId, params)
    const payload = res?.data?.data ?? res?.data
    if (payload && payload.error) {
      error.value = payload.error
      data.value = null
    } else {
      data.value = payload
    }
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '加载失败'
    data.value = null
  } finally {
    loading.value = false
  }
}

const barWidth = (share: number) => `${Math.min(100, Math.max(2, share))}%`

watch(() => props.clientId, load, { immediate: true })
watch(() => props.platform, () => load())
</script>

<style scoped>
.geo-competitor-analysis {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 16px 20px;
  margin-top: 16px;
}
.gca-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 14px;
}
.gca-title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
}
.gca-subtitle {
  margin: 4px 0 0;
  font-size: 12px;
  color: #909399;
}
.gca-controls {
  display: flex;
  gap: 8px;
  align-items: center;
}
.gca-summary {
  display: flex;
  gap: 32px;
  padding: 12px 16px;
  background: #f7f9fc;
  border-radius: 6px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.summary-value {
  font-size: 24px;
  font-weight: 700;
  color: #303133;
}
.summary-value.highlight {
  color: #67c23a;
}
.summary-value.small {
  font-size: 15px;
  line-height: 24px;
}
.summary-label {
  font-size: 12px;
  color: #909399;
  margin-top: 2px;
}
.gca-sections {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}
@media (max-width: 1100px) {
  .gca-sections {
    grid-template-columns: 1fr;
  }
}
.section-title {
  font-size: 13px;
  font-weight: 600;
  color: #606266;
  margin-bottom: 8px;
}
.bar-wrap {
  position: relative;
  height: 14px;
  background: #f0f2f5;
  border-radius: 7px;
  overflow: hidden;
}
.bar {
  height: 100%;
  border-radius: 7px;
  transition: width 0.4s;
}
.bar-text {
  position: absolute;
  left: 8px;
  top: 0;
  font-size: 11px;
  line-height: 14px;
  color: #303133;
}
.own-name {
  color: #67c23a;
  font-weight: 600;
}
.comp-name {
  color: #e6a23c;
}
.mini-tag {
  margin-left: 6px;
}
.watchlist {
  margin-top: 8px;
  font-size: 12px;
  color: #909399;
}
.gca-platforms {
  margin-top: 16px;
}
.platform-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
}
.platform-card {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 10px 14px;
  font-size: 12px;
}
.platform-head {
  display: flex;
  justify-content: space-between;
  margin-bottom: 6px;
  font-size: 13px;
}
.platform-metric {
  color: #606266;
  margin-bottom: 6px;
}
.platform-metric b {
  color: #67c23a;
}
.platform-line {
  color: #909399;
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.muted {
  color: #909399;
  font-weight: 400;
  font-size: 12px;
}
.gca-empty {
  text-align: center;
  padding: 32px 0;
  color: #909399;
}
.empty-icon {
  font-size: 28px;
  margin-bottom: 8px;
  color: #c0c4cc;
}
.empty-title {
  font-size: 14px;
  color: #606266;
}
.empty-desc {
  font-size: 12px;
  margin-top: 4px;
}
</style>
