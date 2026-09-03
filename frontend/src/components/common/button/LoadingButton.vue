<template>
  <el-button
    :type="type"
    :size="size"
    :loading="loading"
    :disabled="disabled || loading"
    @click="handleClick"
  >
    <template #loading>
      <span class="loading-text">{{ loadingText }}</span>
    </template>
    <slot />
  </el-button>
</template>

<script setup lang="ts">
import { ref } from 'vue'

interface Props {
  loading?: boolean
  loadingText?: string
  type?: 'primary' | 'success' | 'warning' | 'danger' | 'info'
  size?: 'large' | 'default' | 'small'
  disabled?: boolean
  click?: () => Promise<void> | void
}

const props = withDefaults(defineProps<Props>(), {
  loadingText: '加载中...',
})

const emit = defineEmits<{
  (e: 'click'): void
}>()

const internalLoading = ref(false)

const handleClick = async () => {
  if (props.click) {
    internalLoading.value = true
    try {
      await props.click()
    } finally {
      internalLoading.value = false
    }
  }
  emit('click')
}
</script>

<style scoped lang="scss">
.loading-text {
  margin-right: 4px;
}
</style>
