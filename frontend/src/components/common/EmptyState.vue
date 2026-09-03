<template>
  <div class="empty-state">
    <div class="empty-icon">
      <el-icon v-if="icon">
        <component :is="icon" />
      </el-icon>
      <span v-else>{{ defaultIcon }}</span>
    </div>
    <h3 v-if="title">{{ title }}</h3>
    <p v-if="description">{{ description }}</p>
    <slot name="action">
      <el-button v-if="actionText" type="primary" @click="$emit('action')">
        {{ actionText }}
      </el-button>
    </slot>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { Component } from 'vue'

interface Props {
  icon?: string | Component
  title?: string
  description?: string
  actionText?: string
}

defineProps<Props>()
defineEmits<{
  (e: 'action'): void
}>()

const defaultIcon = computed(() => '📭')
</script>

<style scoped lang="scss">
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  text-align: center;

  .empty-icon {
    font-size: 64px;
    margin-bottom: 16px;
    opacity: 0.5;

    .el-icon {
      font-size: 64px;
    }
  }

  h3 {
    margin: 0 0 8px 0;
    font-size: 18px;
    color: var(--text-primary);
  }

  p {
    margin: 0 0 24px 0;
    font-size: 14px;
    color: var(--text-secondary);
  }
}
</style>
