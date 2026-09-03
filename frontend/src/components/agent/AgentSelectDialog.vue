<template>
  <el-dialog
    v-model="visible"
    :title="title"
    width="500px"
    :close-on-click-modal="false"
    @close="handleClose"
  >
    <div class="select-list">
      <div
        v-for="item in items"
        :key="item.value"
        class="select-item"
        :class="{ active: selectedValue === item.value }"
        @click="handleSelect(item)"
      >
        <div class="item-icon">
          <el-icon v-if="item.icon">
            <component :is="item.icon" />
          </el-icon>
          <span v-else class="icon-placeholder">{{ item.label.charAt(0) }}</span>
        </div>
        <div class="item-content">
          <div class="item-label">{{ item.label }}</div>
          <div v-if="item.description" class="item-description">
            {{ item.description }}
          </div>
        </div>
        <div v-if="selectedValue === item.value" class="item-check">
          <el-icon><Check /></el-icon>
        </div>
      </div>
    </div>

    <template #footer>
      <el-button @click="handleClose">取消</el-button>
      <el-button type="primary" :disabled="!selectedValue" @click="handleConfirm">
        确认选择
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { Check } from '@element-plus/icons-vue'

interface SelectItem {
  value: any
  label: string
  description?: string
  icon?: any
}

const props = defineProps<{
  modelValue: boolean
  title: string
  items: SelectItem[]
  defaultValue?: any
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  'select': [item: SelectItem]
}>()

const visible = ref(props.modelValue)
const selectedValue = ref(props.defaultValue)

watch(() => props.modelValue, (val) => {
  visible.value = val
  if (val) {
    selectedValue.value = props.defaultValue
  }
})

watch(visible, (val) => {
  emit('update:modelValue', val)
})

function handleClose() {
  visible.value = false
}

function handleSelect(item: SelectItem) {
  selectedValue.value = item.value
}

function handleConfirm() {
  const item = props.items.find(i => i.value === selectedValue.value)
  if (item) {
    emit('select', item)
    visible.value = false
  }
}
</script>

<style scoped lang="scss">
.select-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: 400px;
  overflow-y: auto;
  padding: 8px 0;
}

.select-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  border: 1px solid var(--border-thin);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;

  &:hover {
    border-color: var(--primary-color);
    background: var(--surface-field);
  }

  &.active {
    border-color: var(--primary-color);
    background: var(--accent-soft);
  }
}

.item-icon {
  flex-shrink: 0;
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: var(--surface-field);
  color: var(--primary-color);
  font-size: 20px;

  .icon-placeholder {
    font-weight: 600;
  }
}

.item-content {
  flex: 1;
  min-width: 0;
}

.item-label {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
  margin-bottom: 4px;
}

.item-description {
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.4;
}

.item-check {
  flex-shrink: 0;
  color: var(--primary-color);
  font-size: 20px;
}
</style>
