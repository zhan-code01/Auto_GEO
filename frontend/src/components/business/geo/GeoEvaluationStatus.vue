<template>
  <div class="geo-eval-status">
    <div class="status-info">
      <div class="info-section">
        <span class="status-icon" :class="promptSetStatus">
          {{ promptSetStatus === 'frozen' ? '✓' : promptSetStatus === 'active' ? '•' : '!' }}
        </span>
        <div class="info-content">
          <div class="info-title">测评问题集</div>
          <div class="info-detail">
            <template v-if="promptSet">
              <el-tag size="small" :type="promptSetStatus === 'frozen' ? 'success' : 'warning'" effect="plain">
                {{ promptSetStatus === 'frozen' ? '已有基线' : '待建立基线' }}
              </el-tag>
              <span class="info-sub">{{ promptSet.question_count }} 个问题</span>
            </template>
            <template v-else>
              <el-tag size="small" type="info" effect="plain">暂无问题</el-tag>
              <span class="info-sub">请先在智能文章生成模块创建问题</span>
            </template>
          </div>
        </div>
        <div v-if="promptSet" class="prompt-action-column">
          <el-button
            class="prompt-preview-button"
            size="small"
            :disabled="disabled"
            @click="$emit('preview-prompts')"
          >
            预览问题
          </el-button>
        </div>
      </div>

      <span class="status-divider">|</span>

      <div class="info-section">
        <span class="status-icon platform">
          平
        </span>
        <div class="info-content">
          <div class="info-title">测评平台</div>
          <el-select
            v-model="selectedPlatformModel"
            class="status-platform-select"
            placeholder="选择平台"
            size="small"
            :disabled="!platformOptions.length"
            @change="$emit('platform-change')"
          >
            <el-option
              v-for="platform in platformOptions"
              :key="platform.id"
              :label="platform.name"
              :value="platform.id"
              :disabled="!isAuthorizedPlatform(platform.status)"
            />
          </el-select>
          <el-select
            v-if="accountOptions && accountOptions.length > 1"
            v-model="selectedAccountModel"
            class="status-platform-select"
            placeholder="选择授权账户"
            size="small"
          >
            <el-option
              v-for="account in accountOptions"
              :key="account.id"
              :label="account.name"
              :value="account.id"
            />
          </el-select>
        </div>
      </div>

    </div>

    <div class="status-actions">
      <el-button v-if="!promptSet" disabled>暂无可测评问题</el-button>

      <template v-else-if="effectiveBaselineStatus === 'none'">
        <el-button
          type="primary"
          :loading="baselineLoading"
          :disabled="disabled || runActive || unmeasuredCount === 0"
          @click="$emit('create-baseline')"
        >
          生成基线（{{ unmeasuredCount }}）
        </el-button>
        <span v-if="unmeasuredCount === 0" class="action-hint">没有未测评问题，请重试失败记录</span>
      </template>

      <template v-else>
        <el-button
          v-if="(selectedPlatformStatus?.unmeasured_count || 0) > 0"
          type="primary"
          :loading="baselineLoading"
          :disabled="disabled || runActive"
          @click="$emit('create-baseline')"
        >
          继续测评（{{ selectedPlatformStatus?.unmeasured_count }} 个新问题）
        </el-button>
        <el-button
          :type="(selectedPlatformStatus?.unmeasured_count || 0) > 0 ? 'default' : 'primary'"
          :loading="recheckLoading"
          :disabled="disabled || runActive"
          @click="$emit('run-recheck')"
        >
          执行使用后测试（{{ selectedPlatformStatus?.recheck_eligible_count || 0 }}）
        </el-button>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface PromptSetInfo {
  id?: number
  question_count: number
  status?: string
  frozen_at?: string | null
}

interface PlatformStatus {
  platform: string
  has_baseline: boolean
  baseline_count: number
  baseline_at: string | null
  attempted_count?: number
  failed_count?: number
  unmeasured_count?: number
  recheck_eligible_count?: number
}

interface PlatformOption {
  id: string
  name: string
  status?: string
}

interface AccountOption {
  id: number
  name: string
}

const props = defineProps<{
  promptSet: PromptSetInfo | null
  baselineStatus: 'none' | 'partial' | 'complete' | string
  platformStatuses: PlatformStatus[]
  selectedPlatform?: string
  platformOptions?: PlatformOption[]
  authorizedPlatforms?: string[]
  baselineLoading: boolean
  recheckLoading: boolean
  generatingPrompts?: boolean
  disabled?: boolean
  runActive?: boolean
  selectedAccount?: number
  accountOptions?: AccountOption[]
}>()

const emit = defineEmits<{
  'generate-prompts': []
  'preview-prompts': []
  'create-baseline': []
  'complete-baseline': []
  'rebuild-baseline': []
  'run-recheck': []
  'update:selectedPlatform': [value: string]
  'platform-change': []
  'update:selectedAccount': [value: number | undefined]
}>()

const selectedAccountModel = computed({
  get: () => props.selectedAccount,
  set: value => emit('update:selectedAccount', value),
})

const defaultPlatforms: PlatformStatus[] = [
  { platform: 'doubao', has_baseline: false, baseline_count: 0, baseline_at: null },
  { platform: 'qianwen', has_baseline: false, baseline_count: 0, baseline_at: null },
  { platform: 'deepseek', has_baseline: false, baseline_count: 0, baseline_at: null },
]

const mergedPlatforms = computed(() => {
  const map = new Map(defaultPlatforms.map(platform => [platform.platform, { ...platform }]))
  props.platformStatuses.forEach(platform => {
    map.set(platform.platform, { ...map.get(platform.platform), ...platform })
  })
  return Array.from(map.values())
})

const visiblePlatforms = computed(() => {
  if (!props.selectedPlatform) return mergedPlatforms.value
  return mergedPlatforms.value.filter(platform => platform.platform === props.selectedPlatform)
})

const baselineCovered = computed(() =>
  visiblePlatforms.value.filter(platform => platform.has_baseline).length,
)

const effectiveBaselineStatus = computed(() => {
  if (!props.selectedPlatform) return props.baselineStatus
  return baselineCovered.value > 0 ? 'complete' : 'none'
})

const selectedPlatformStatus = computed(() => {
  if (!props.selectedPlatform) return undefined
  return mergedPlatforms.value.find(platform => platform.platform === props.selectedPlatform)
})

const unmeasuredCount = computed(() =>
  selectedPlatformStatus.value?.unmeasured_count ?? props.promptSet?.question_count ?? 0,
)

const platformOptions = computed(() => props.platformOptions || [])

const selectedPlatformModel = computed({
  get: () => props.selectedPlatform || '',
  set: value => emit('update:selectedPlatform', value),
})

const promptSetStatus = computed(() => {
  if (!props.promptSet) return 'none'
  return props.promptSet.status === 'frozen' ? 'frozen' : 'active'
})

function isAuthorizedPlatform(status?: string) {
  return status === 'valid' || status === 'expiring'
}

</script>

<style scoped>
.geo-eval-status {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 14px;
  flex-wrap: wrap;
  padding: 16px 24px;
  margin-bottom: 20px;
  background: var(--surface-raised);
  border: 1px solid var(--border-thin);
  border-radius: var(--radius-lg);
}

.status-info {
  flex: 1;
  display: flex;
  align-items: flex-start;
  gap: 16px;
  flex-wrap: wrap;
}

.info-section {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.prompt-action-column {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
  margin-left: 12px;
}

.prompt-action-column :deep(.el-button) {
  justify-content: center;
  width: 72px;
  margin-left: 0;
}

.status-icon {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  font-size: 13px;
  font-weight: 800;
  color: #fff;
  background: var(--text-disabled);
}

.status-icon.frozen,
.status-icon.complete {
  background: var(--success);
}

.status-icon.active,
.status-icon.partial,
.status-icon.running {
  background: var(--warning, #c28b2c);
}

.status-icon.none {
  background: var(--danger);
}

.status-icon.platform {
  background: var(--success);
  font-size: 12px;
}

.info-content {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.info-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-muted);
}

.info-detail {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.info-sub {
  font-size: 12px;
  color: var(--text-body);
}

.status-platform-select {
  width: 140px;
}

.status-divider {
  color: var(--border-soft);
  margin-top: 4px;
}

.status-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  flex-shrink: 0;
}

.action-hint {
  align-self: center;
  font-size: 12px;
  color: var(--warning, #c28b2c);
}

@media (max-width: 768px) {
  .geo-eval-status {
    flex-direction: column;
  }

  .status-info {
    flex-direction: column;
    gap: 12px;
  }

  .status-divider {
    display: none;
  }

  .status-actions {
    width: 100%;
  }
}
</style>
