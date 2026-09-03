/**
 * 平台相关 Hook
 * 我用这个来简化平台操作！
 */

import { computed } from 'vue'
import { usePlatformStore } from '@/stores'
import { PLATFORMS, getPlatformConfig } from '@/core/config/platform'

export function usePlatform() {
  const platformStore = usePlatformStore()

  // 启用的平台列表
  const enabledPlatforms = computed(() => platformStore.enabledPlatforms)

  // 获取平台配置
  const getPlatform = (id: string) => {
    return getPlatformConfig(id)
  }

  // 获取平台图标
  const getPlatformIcon = (id: string) => {
    return `/src/assets/images/platforms/${id}.svg`
  }

  // 获取平台颜色
  const getPlatformColor = (id: string) => {
    return PLATFORMS[id]?.color || '#666'
  }

  // 获取平台名称
  const getPlatformName = (id: string) => {
    return PLATFORMS[id]?.name || id
  }

  // 检查平台是否启用
  const isPlatformEnabled = (id: string) => {
    return platformStore.isPlatformEnabled(id)
  }

  // 切换平台状态
  const togglePlatform = (id: string) => {
    platformStore.togglePlatform(id)
  }

  // 启用平台
  const enablePlatform = (id: string) => {
    platformStore.enablePlatform(id)
  }

  // 禁用平台
  const disablePlatform = (id: string) => {
    platformStore.disablePlatform(id)
  }

  return {
    // 状态
    activePlatformIds: platformStore.activePlatformIds,
    enabledPlatforms,
    platformStates: platformStore.platformStates,

    // 工具方法
    getPlatform,
    getPlatformIcon,
    getPlatformColor,
    getPlatformName,
    isPlatformEnabled,

    // 操作
    togglePlatform,
    enablePlatform,
    disablePlatform,
  }
}
