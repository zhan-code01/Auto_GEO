/**
 * 发布相关 Hook
 * 我用这个来简化发布操作！
 */

import { ref, computed } from 'vue'
import { publishApi } from '@/services/api'
import type { PublishTask } from '@/types'

export function usePublish() {
  const publishing = ref(false)
  const tasks = ref<PublishTask[]>([])
  const progress = ref({ completed: 0, total: 0, failed: 0 })

  // 创建发布任务
  const createTask = async (articleIds: number[], accountIds: number[]) => {
    const result = await publishApi.createTask({
      article_ids: articleIds,
      account_ids: accountIds,
    })
    return result
  }

  // 获取发布进度
  const getProgress = async (taskId: string) => {
    const result = await publishApi.getProgress(taskId)
    return result
  }

  // 获取发布记录
  const getRecords = async (params?: {
    article_id?: number
    account_id?: number
    limit?: number
  }) => {
    const result = await publishApi.getRecords(params)
    return result
  }

  // 重试发布
  const retry = async (recordId: number) => {
    const result = await publishApi.retry(recordId)
    return result
  }

  // 进度百分比
  const progressPercentage = computed(() => {
    if (progress.value.total === 0) return 0
    return Math.round((progress.value.completed / progress.value.total) * 100)
  })

  // 全部完成
  const isCompleted = computed(() => {
    return progress.value.completed === progress.value.total && progress.value.total > 0
  })

  // 全部失败
  const allFailed = computed(() => {
    return progress.value.completed === progress.value.total &&
           progress.value.failed === progress.value.total &&
           progress.value.total > 0
  })

  return {
    // 状态
    publishing,
    tasks,
    progress,
    progressPercentage,
    isCompleted,
    allFailed,

    // 操作
    createTask,
    getProgress,
    getRecords,
    retry,
  }
}
