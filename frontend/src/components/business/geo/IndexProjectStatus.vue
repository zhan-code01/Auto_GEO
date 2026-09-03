<template>
  <div class="project-status-bar">
    <div class="status-left">
      <div class="project-info">
        <span class="project-label">项目：</span>
        <span class="project-name">{{ projectName }}</span>
        <span class="divider">|</span>
        <span class="project-label">公司名：</span>
        <span class="company-name">{{ companyName }}</span>
      </div>
      <div class="timeline-info">
        <template v-if="hasBaseline">
          <span class="info-item">
            <span class="info-label">基线：</span>
            <el-tag type="success" size="small" effect="plain">已建立</el-tag>
            <span class="info-value">{{ baselineAt }}</span>
          </span>
        </template>
        <template v-else>
          <span class="info-item">
            <span class="info-label">基线：</span>
            <el-tag type="warning" size="small" effect="plain">未建立</el-tag>
          </span>
        </template>
        <template v-if="latestCheckAt">
          <span class="divider">|</span>
          <span class="info-item">
            <span class="info-label">最近复测：</span>
            <span class="info-value">{{ latestCheckAt }}</span>
          </span>
        </template>
        <template v-if="authorizedCount !== null">
          <span class="divider">|</span>
          <span class="info-item">
            <span class="info-label">授权平台：</span>
            <span class="info-value">{{ authorizedCount }}/{{ totalPlatforms }}</span>
          </span>
        </template>
      </div>
    </div>
    <div class="status-actions">
      <el-button
        v-if="!hasBaseline"
        type="primary"
        :loading="baselineLoading"
        :disabled="disabled"
        @click="$emit('create-baseline')"
      >
        生成使用前基线
      </el-button>
      <el-button
        v-else
        type="primary"
        :loading="recheckLoading"
        :disabled="disabled"
        @click="$emit('run-recheck')"
      >
        执行使用后复测
      </el-button>
      <el-button
        v-if="hasBaseline"
        :loading="baselineLoading"
        :disabled="disabled"
        @click="$emit('rebuild-baseline')"
      >
        重新生成基线
      </el-button>
      <el-button :disabled="disabled" @click="$emit('view-evidence')">
        查看证据明细
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  projectName: string
  companyName: string
  hasBaseline: boolean
  baselineAt: string | null
  latestCheckAt: string | null
  authorizedCount: number | null
  totalPlatforms: number
  baselineLoading: boolean
  recheckLoading: boolean
  disabled?: boolean
}>()

defineEmits<{
  'create-baseline': []
  'run-recheck': []
  'rebuild-baseline': []
  'view-evidence': []
}>()
</script>

<style scoped>
.project-status-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
  background: var(--surface-raised);
  border: 1px solid var(--border-thin);
  border-radius: var(--radius-lg);
  margin-bottom: 20px;
  flex-wrap: wrap;
  gap: 12px;
}

.status-left {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.project-info {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

.project-label {
  color: var(--text-muted, #8a7d68);
  font-size: 13px;
}

.project-name, .company-name {
  font-weight: 600;
  color: var(--text-head);
  font-size: 14px;
}

.timeline-info {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

.info-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.info-label {
  color: var(--text-muted, #8a7d68);
  font-size: 12px;
}

.info-value {
  color: var(--text-body);
  font-size: 12px;
}

.divider {
  color: var(--border-soft, #c4b9a3);
  margin: 0 6px;
}

.status-actions {
  display: flex;
  gap: 10px;
  flex-shrink: 0;
}
</style>
