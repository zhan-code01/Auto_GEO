<template>
  <div class="loading-state" :class="[`size-${size}`, `variant-${variant}`]">
    <div v-if="variant === 'spinner'" class="spinner">
      <div class="spinner-dot" v-for="i in 3" :key="i" :style="{ animationDelay: `${i * 0.15}s` }"></div>
    </div>
    <el-icon v-else-if="variant === 'circular'" class="circular is-loading">
      <Loading />
    </el-icon>
    <el-icon v-else-if="variant === 'dots'" class="dots">
      <Loading />
    </el-icon>
    <p v-if="text" class="loading-text">{{ text }}</p>
  </div>
</template>

<script setup lang="ts">
import { Loading } from '@element-plus/icons-vue'

interface Props {
  text?: string
  size?: 'small' | 'medium' | 'large'
  variant?: 'spinner' | 'circular' | 'dots'
}

withDefaults(defineProps<Props>(), {
  size: 'medium',
  variant: 'circular',
})
</script>

<style scoped lang="scss">
.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;

  &.size-small {
    .circular,
    .dots {
      font-size: 20px;
    }
  }

  &.size-medium {
    .circular,
    .dots {
      font-size: 32px;
    }
  }

  &.size-large {
    .circular,
    .dots {
      font-size: 48px;
    }
  }

  .loading-text {
    margin: 0;
    font-size: 14px;
    color: var(--text-secondary);
  }
}

// Spinner 动画
.spinner {
  display: flex;
  gap: 6px;

  .spinner-dot {
    width: 8px;
    height: 8px;
    background: var(--primary);
    border-radius: 50%;
    animation: bounce 1.4s ease-in-out infinite both;
  }
}

@keyframes bounce {
  0%, 80%, 100% {
    transform: scale(0);
  }
  40% {
    transform: scale(1);
  }
}

// 圆形加载
.circular {
  color: var(--primary);
}

// Dots 动画
.dots {
  color: var(--text-secondary);
  animation: pulse 1.5s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0.5;
  }
}
</style>
