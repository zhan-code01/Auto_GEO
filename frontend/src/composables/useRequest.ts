/**
 * 请求 Hook
 * 我用这个来简化异步请求处理！
 */

import { ref, shallowRef } from 'vue'
import type { Ref } from 'vue'

export interface RequestOptions<T> {
  immediate?: boolean
  onSuccess?: (data: T) => void
  onError?: (error: any) => void
}

export function useRequest<T = any>(
  fn: () => Promise<T>,
  options: RequestOptions<T> = {}
) {
  const { immediate = false, onSuccess, onError } = options

  const data = shallowRef<T | null>(null)
  const error = ref<any>(null)
  const loading = ref(false)

  const execute = async (): Promise<T> => {
    loading.value = true
    error.value = null

    try {
      const result = await fn()
      data.value = result
      onSuccess?.(result)
      return result
    } catch (e) {
      error.value = e
      onError?.(e)
      throw e
    } finally {
      loading.value = false
    }
  }

  const reset = () => {
    data.value = null
    error.value = null
    loading.value = false
  }

  // 立即执行
  if (immediate) {
    execute()
  }

  return {
    data,
    error,
    loading,
    execute,
    reset,
  }
}

/**
 * 多个并行请求 Hook
 */
export function useRequests<T extends any[]>(
  fns: (() => Promise<any>)[],
  options: RequestOptions<T> = {}
) {
  const { immediate = false, onSuccess, onError } = options

  const data = shallowRef<any[]>([])
  const errors = ref<any[]>([])
  const loading = ref(false)

  const execute = async (): Promise<T> => {
    loading.value = true
    errors.value = []

    try {
      const results = await Promise.allSettled(fns.map(fn => fn()))
      data.value = results.map(r => r.status === 'fulfilled' ? r.value : null)

      const failed = results.filter(r => r.status === 'rejected') as PromiseRejectedResult[]
      if (failed.length > 0) {
        errors.value = failed.map(f => f.reason)
        onError?.(errors.value)
      } else {
        onSuccess?.(data.value as T)
      }

      return data.value as T
    } catch (e) {
      onError?.(e)
      throw e
    } finally {
      loading.value = false
    }
  }

  return {
    data,
    errors,
    loading,
    execute,
  }
}

/**
 * 分页请求 Hook
 */
export function usePagedRequest<T = any>(
  fn: (page: number, pageSize: number) => Promise<{ total: number; items: T[] }>,
  options: RequestOptions<{ total: number; items: T[] }> = {}
) {
  const { immediate = true, onSuccess, onError } = options

  const data = ref<T[]>([])
  const total = ref(0)
  const loading = ref(false)
  const error = ref<any>(null)

  const currentPage = ref(1)
  const pageSize = ref(20)

  const execute = async (page?: number, size?: number) => {
    if (page !== undefined) currentPage.value = page
    if (size !== undefined) pageSize.value = size

    loading.value = true
    error.value = null

    try {
      const result = await fn(currentPage.value, pageSize.value)
      data.value = result.items
      total.value = result.total
      onSuccess?.(result as any)
      return result
    } catch (e) {
      error.value = e
      onError?.(e)
      throw e
    } finally {
      loading.value = false
    }
  }

  const loadMore = async () => {
    const nextPage = currentPage.value + 1
    const result = await fn(nextPage, pageSize.value)
    data.value = [...data.value, ...result.items] as typeof data.value
    total.value = result.total
    currentPage.value = nextPage
    return result
  }

  const refresh = () => {
    return execute(currentPage.value, pageSize.value)
  }

  if (immediate) {
    execute()
  }

  return {
    data,
    total,
    loading,
    error,
    currentPage,
    pageSize,
    execute,
    loadMore,
    refresh,
  }
}
