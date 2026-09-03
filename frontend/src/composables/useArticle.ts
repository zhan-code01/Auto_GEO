/**
 * 文章相关 Hook
 * 我用这个来简化文章操作！
 */

import { computed } from 'vue'
import { useArticleStore } from '@/stores'

export function useArticle() {
  const articleStore = useArticleStore()

  // 加载文章列表
  const loadArticles = async (params?: {
    page?: number
    pageSize?: number
    status?: number
    keyword?: string
  }) => {
    return await articleStore.loadArticles(params)
  }

  // 加载文章详情
  const loadArticleDetail = async (id: number) => {
    return await articleStore.loadArticleDetail(id)
  }

  // 创建文章
  const createArticle = async (data: {
    title: string
    content: string
    tags?: string
    category?: string
    cover_image?: string
  }) => {
    return await articleStore.createArticle(data as any)
  }

  // 更新文章
  const updateArticle = async (id: number, data: any) => {
    return await articleStore.updateArticle(id, data)
  }

  // 删除文章
  const deleteArticle = async (id: number) => {
    return await articleStore.deleteArticle(id)
  }

  // 草稿文章
  const draftArticles = computed(() => articleStore.draftArticles)

  // 已发布文章
  const publishedArticles = computed(() => articleStore.publishedArticles)

  // 文章总数
  const totalCount = computed(() => articleStore.totalCount)

  // 当前选中的文章
  const selectedArticles = computed(() => articleStore.selectedArticles)

  return {
    // 状态
    articles: articleStore.articles,
    selectedArticleIds: articleStore.selectedArticleIds,
    currentArticle: articleStore.currentArticle,
    loading: articleStore.loading,
    error: articleStore.error,
    pagination: articleStore.pagination,
    draftArticles,
    publishedArticles,
    totalCount,
    selectedArticles,

    // 操作
    loadArticles,
    loadArticleDetail,
    createArticle,
    updateArticle,
    deleteArticle,
    toggleArticleSelection: articleStore.toggleArticleSelection,
    toggleSelectAll: articleStore.toggleSelectAll,
    clearSelection: articleStore.clearSelection,
    setCurrentArticle: articleStore.setCurrentArticle,
    resetCurrentArticle: articleStore.resetCurrentArticle,
  }
}
