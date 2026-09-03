<template>
  <div class="platform-selector">
    <div class="selector-header">
      <span class="selector-label">{{ label }}</span>
      <el-checkbox v-if="showSelectAll" :model-value="allSelected" @change="toggleAll">
        全选
      </el-checkbox>
    </div>

    <div class="platform-list">
      <div
        v-for="platform in platforms"
        :key="platform.id"
        class="platform-item"
        :class="{ disabled: disabled?.includes(platform.id) }"
      >
        <div class="platform-info">
          <el-checkbox
            :model-value="props.modelValue.includes(platform.id)"
            :disabled="disabled?.includes(platform.id)"
            @change="toggle(platform.id)"
          />
          <PlatformIcon :platform="platform.id" :size="32" />
          <span class="platform-name">{{ platform.name }}</span>
          <el-tag v-if="platform.count !== undefined" size="small">
            {{ platform.count }}
          </el-tag>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { CheckboxValueType } from 'element-plus'
import PlatformIcon from '@/components/business/account/PlatformIcon.vue'
import { PLATFORMS } from '@/core/config/platform'
import type { PlatformId } from '@/types'

interface PlatformItem {
  id: PlatformId
  name: string
  count?: number
}

interface Props {
  modelValue: PlatformId[]
  label?: string
  platforms?: PlatformItem[]
  disabled?: PlatformId[]
  showSelectAll?: boolean
}

interface Emits {
  (e: 'update:modelValue', value: PlatformId[]): void
}

const props = withDefaults(defineProps<Props>(), {
  label: '选择平台',
  platforms: () => Object.values(PLATFORMS).map(p => ({ id: p.id as PlatformId, name: p.name })),
  disabled: () => [],
  showSelectAll: false,
})

const emit = defineEmits<Emits>()

const allSelected = computed(() => {
  const available = props.platforms
    .filter(p => !props.disabled?.includes(p.id))
    .map(p => p.id)
  return available.length > 0 && available.every(id => props.modelValue.includes(id))
})

const toggle = (platformId: PlatformId) => {
  const index = props.modelValue.indexOf(platformId)
  if (index === -1) {
    emit('update:modelValue', [...props.modelValue, platformId])
  } else {
    emit('update:modelValue', props.modelValue.filter(id => id !== platformId))
  }
}

const toggleAll = (checked: CheckboxValueType) => {
  const available = props.platforms
    .filter(p => !props.disabled?.includes(p.id))
    .map(p => p.id)

  if (checked === true) {
    emit('update:modelValue', [...new Set([...props.modelValue, ...available])])
  } else {
    emit('update:modelValue', props.modelValue.filter(id => !available.includes(id)))
  }
}
</script>

<style scoped lang="scss">
.platform-selector {
  .selector-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 12px;

    .selector-label {
      font-size: 14px;
      font-weight: 500;
      color: var(--text-primary);
    }
  }

  .platform-list {
    display: flex;
    flex-direction: column;
    gap: 8px;

    .platform-item {
      display: flex;
      align-items: center;
      padding: 10px 12px;
      background: var(--bg-secondary);
      border-radius: 8px;
      transition: all 0.2s;

      &:hover:not(.disabled) {
        background: var(--bg-tertiary);
      }

      &.disabled {
        opacity: 0.5;
        cursor: not-allowed;
      }

      .platform-info {
        display: flex;
        align-items: center;
        gap: 12px;
        width: 100%;

        .platform-name {
          flex: 1;
          font-size: 14px;
        }
      }
    }
  }
}
</style>
