<template>
  <teleport to="body">
    <transition name="fade">
      <div v-if="visible" class="error-boundary" @click="handleClick">
        <div class="error-card" @click.stop>
          <div class="error-icon">
            <el-icon><Warning /></el-icon>
          </div>
          <h3>{{ title }}</h3>
          <p>{{ message }}</p>
          <div class="error-actions">
            <el-button @click="handleRetry" v-if="onRetry">重试</el-button>
            <el-button type="primary" @click="handleClose">关闭</el-button>
          </div>
          <details v-if="details" class="error-details">
            <summary>错误详情</summary>
            <pre>{{ details }}</pre>
          </details>
        </div>
      </div>
    </transition>
  </teleport>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { Warning } from '@element-plus/icons-vue'

interface Props {
  visible?: boolean
  title?: string
  message?: string
  details?: string
  onRetry?: () => void
}

const props = withDefaults(defineProps<Props>(), {
  title: '出错了',
  message: '发生了一些错误，请稍后再试',
})

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'retry'): void
}>()

const internalVisible = ref(props.visible)

watch(() => props.visible, (val) => {
  internalVisible.value = val
})

const handleClick = () => {
  emit('close')
  internalVisible.value = false
}

const handleClose = () => {
  emit('close')
  internalVisible.value = false
}

const handleRetry = () => {
  emit('retry')
  internalVisible.value = false
}

// 暴露方法
defineExpose({
  show: () => {
    internalVisible.value = true
  },
  hide: () => {
    internalVisible.value = false
  },
})
</script>

<style scoped lang="scss">
.error-boundary {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(244, 239, 229, 0.85);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
  backdrop-filter: blur(4px);
}

.error-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 32px;
  max-width: 480px;
  text-align: center;

  .error-icon {
    font-size: 64px;
    color: var(--danger);
    margin-bottom: 16px;
  }

  h3 {
    margin: 0 0 12px 0;
    font-size: 20px;
    color: var(--text-primary);
  }

  p {
    margin: 0 0 24px 0;
    font-size: 14px;
    color: var(--text-secondary);
  }

  .error-actions {
    display: flex;
    justify-content: center;
    gap: 12px;
    margin-bottom: 16px;
  }

  .error-details {
    text-align: left;
    background: var(--bg-tertiary);
    border-radius: 8px;
    padding: 12px;

    summary {
      cursor: pointer;
      font-size: 12px;
      color: var(--text-secondary);
      margin-bottom: 8px;

      &:hover {
        color: var(--text-primary);
      }
    }

    pre {
      margin: 0;
      padding: 12px;
      background: var(--bg-primary);
      border-radius: 4px;
      font-size: 12px;
      color: var(--text-secondary);
      overflow-x: auto;
    }
  }
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
