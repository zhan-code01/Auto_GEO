<template>
  <div class="platform-icon" :class="`platform-${platform}`" :style="customStyle">
    <slot>{{ code }}</slot>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { PLATFORMS } from '@/core/config/platform'
import type { PlatformId } from '@/types'

interface Props {
  platform: PlatformId | string
  size?: number
  showName?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  size: 32,
  showName: false,
})

const config = computed(() => PLATFORMS[props.platform as PlatformId])
const code = computed(() => config.value?.code || '?')
const name = computed(() => config.value?.name || props.platform)

const customStyle = computed(() => {
  const color = config.value?.color || '#666'
  return {
    width: `${props.size}px`,
    height: `${props.size}px`,
    fontSize: `${props.size * 0.4}px`,
    background: color,
  }
})
</script>

<style scoped lang="scss">
.platform-icon {
  border-radius: 8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  color: white;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.2);
  transition: transform 0.2s;

  &:hover {
    transform: scale(1.05);
  }
}
</style>
