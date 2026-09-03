/**
 * 账号相关 Hook
 * 我用这个来简化账号操作！
 */

import { computed } from 'vue'
import { useAccountStore } from '@/stores'
import { accountApi } from '@/services/api'

export function useAccount() {
  const accountStore = useAccountStore()

  // 加载账号列表
  const loadAccounts = async (platform?: string) => {
    return await accountStore.loadAccounts(platform ? { platform } : undefined)
  }

  // 创建账号
  const createAccount = async (data: any) => {
    const result = await accountApi.create(data)
    if (result.success !== false) {
      await accountStore.loadAccounts()
    }
    return result
  }

  // 更新账号
  const updateAccount = async (id: number, data: any) => {
    const result = await accountApi.update(id, data)
    if (result.success !== false) {
      await accountStore.loadAccounts()
    }
    return result
  }

  // 删除账号
  const deleteAccount = async (id: number) => {
    const result = await accountApi.delete(id)
    if (result.success !== false) {
      await accountStore.loadAccounts()
    }
    return result
  }

  // 开始授权
  const startAuth = async (platform: string, accountId?: number) => {
    return await accountStore.startAuth(platform, accountId)
  }

  // 检查授权状态
  const checkAuthStatus = async (taskId: string) => {
    return await accountStore.checkAuthStatus(taskId)
  }

  // 保存授权结果
  const saveAuth = async (taskId: string, accountId: number) => {
    return await accountStore.saveAuth(taskId, accountId)
  }

  // 按平台分组账号
  const accountsByPlatform = computed(() => accountStore.accountsByPlatform)

  // 已授权账号
  const authorizedAccounts = computed(() => accountStore.authorizedAccounts)

  // 账号总数
  const totalCount = computed(() => accountStore.totalCount)

  // 已授权账号数
  const authorizedCount = computed(() => accountStore.authorizedCount)

  return {
    // 状态
    accounts: accountStore.accounts,
    selectedAccountIds: accountStore.selectedAccountIds,
    loading: accountStore.loading,
    error: accountStore.error,
    accountsByPlatform,
    authorizedAccounts,
    totalCount,
    authorizedCount,

    // 操作
    loadAccounts,
    createAccount,
    updateAccount,
    deleteAccount,
    startAuth,
    checkAuthStatus,
    saveAuth,
    toggleAccountSelection: accountStore.toggleAccountSelection,
    toggleSelectAll: accountStore.toggleSelectAll,
    clearSelection: accountStore.clearSelection,
  }
}
