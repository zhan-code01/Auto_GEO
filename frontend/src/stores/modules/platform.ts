/**
 * 平台状态管理
 * 我用这个来管理平台状态！
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { IMPLEMENTED_PLATFORM_IDS, PLATFORMS } from '@/core/config/platform'

export const usePlatformStore = defineStore('platform', () => {
  // ==================== 状态 ====================

  /** 当前激活的平台ID列表，默认与已实现平台白名单保持一致 */
  const activePlatformIds = ref<string[]>([...IMPLEMENTED_PLATFORM_IDS])

  /** 平台状态映射 */
  const platformStates = ref<Record<string, {
    enabled: boolean
    available: boolean
    lastCheckTime: number
  }>>({})

  // ==================== 计算属性 ====================

  /** 获取启用的平台列表 */
  const enabledPlatforms = computed(() => {
    return activePlatformIds.value
      .map(id => PLATFORMS[id])
      .filter(Boolean)
  })

  /** 获取平台配置 */
  const getPlatformConfig = (id: string) => {
    return PLATFORMS[id]
  }

  /** 获取平台图标 */
  const getPlatformIcon = (id: string) => {
    return `/src/assets/images/platforms/${id}.svg`
  }

  /** 检查平台是否启用 */
  const isPlatformEnabled = (id: string) => {
    return activePlatformIds.value.includes(id)
  }

  // ==================== 操作 ====================

  /** 启用平台 */
  function enablePlatform(platformId: string) {
    if (!activePlatformIds.value.includes(platformId)) {
      activePlatformIds.value.push(platformId)
    }
  }

  /** 禁用平台 */
  function disablePlatform(platformId: string) {
    activePlatformIds.value = activePlatformIds.value.filter(id => id !== platformId)
  }

  /** 切换平台状态 */
  function togglePlatform(platformId: string) {
    if (activePlatformIds.value.includes(platformId)) {
      disablePlatform(platformId)
    } else {
      enablePlatform(platformId)
    }
  }

  /** 更新平台状态 */
  function updatePlatformState(platformId: string, state: Partial<{
    enabled: boolean
    available: boolean
    lastCheckTime: number
  }>) {
    if (!platformStates.value[platformId]) {
      platformStates.value[platformId] = {
        enabled: true,
        available: true,
        lastCheckTime: Date.now(),
      }
    }
    Object.assign(platformStates.value[platformId], state)
  }

  /** 检查平台可用性 */
  async function checkPlatformAvailable(platformId: string) {
    // 调用后端API检查平台服务状态
    try {
      const response = await fetch('/api/publish/platforms')
      const data = await response.json()
      const platforms = data.data?.platforms || []
      const platform = platforms.find((p: any) => p.id === platformId)
      updatePlatformState(platformId, {
        available: platform?.enabled || false,
        lastCheckTime: Date.now(),
      })
      return platform?.enabled || false
    } catch {
      updatePlatformState(platformId, { available: false })
      return false
    }
  }

  /** 初始化平台状态 */
  function initPlatformStates() {
    activePlatformIds.value.forEach(id => {
      platformStates.value[id] = {
        enabled: true,
        available: true,
        lastCheckTime: Date.now(),
      }
    })
  }

  return {
    // 状态
    activePlatformIds,
    platformStates,

    // 计算属性
    enabledPlatforms,
    getPlatformConfig,
    getPlatformIcon,
    isPlatformEnabled,

    // 操作
    enablePlatform,
    disablePlatform,
    togglePlatform,
    updatePlatformState,
    checkPlatformAvailable,
    initPlatformStates,
  }
})
