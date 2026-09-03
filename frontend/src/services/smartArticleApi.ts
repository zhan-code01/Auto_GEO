import { get, post, del } from '@/services/api'

export interface SmartArticleProject {
  id: number
  client_id: number
  name: string
  company_name?: string | null
  domain_keyword?: string | null
  industry?: string | null
}

export interface SmartArticleBatch {
  batch_id: number
  project_id: number
  mode: 'auto' | 'manual'
  status: string
  requested_count: number
  planned_count: number
  queued_count: number
  success_count: number
  failed_count: number
  processing_count: number
  note?: string | null
  jobs?: Array<{ id: number; question: string; status: string; article_id?: number; error_msg?: string | null }>
}

export interface SmartArticleQuestion {
  id: number
  project_id: number
  question: string
  source?: 'ai' | 'manual'
  intent_type?: string
  context_type?: string
  has_article: boolean
  article_id?: number | null
  article_generation_status?: 'idle' | 'generating' | 'failed' | 'generated'
  created_at?: string | null
}

export interface SmartArticleItem {
  id: number
  project_id?: number | null
  title?: string | null
  content?: string | null
  publish_status?: string
  publish_strategy?: string
  quality_score?: number | null
  source?: string
  error_msg?: string | null
  created_at?: string | null
}

export const smartArticleApi = {
  getProjects: (clientId?: number) => get<SmartArticleProject[]>(
    '/smart-articles/projects',
    clientId ? { client_id: clientId } : undefined,
  ),
  generateQuestions: (data: { project_id: number; question_count: number; custom_question?: string | null }) =>
    post<any>('/smart-articles/question-batches', data),
  getQuestionBatch: (batchId: number) => get<any>(`/smart-articles/question-batches/${batchId}`),
  getQuestions: (params: { project_id: number; has_article?: boolean; page?: number; limit?: number }) =>
    get<any>('/smart-articles/questions', params),
  deleteQuestions: (questionIds: number[]) => post<any>('/smart-articles/questions/batch-delete', { question_ids: questionIds }),
  generateSelectedArticles: (data: { project_id: number; question_ids: number[] }) =>
    post<any>('/smart-articles/article-batches', data),
  generate: (data: { project_id: number; article_count: number; question?: string | null }) =>
    post<any>('/smart-articles/generate', data),
  getBatch: (batchId: number) => get<any>(`/smart-articles/batches/${batchId}`),
  getArticles: (params?: { project_id?: number; publish_status?: string; page?: number; limit?: number }) =>
    get<any>('/smart-articles/articles', params),
  retryJob: (jobId: number) => post<any>(`/smart-articles/jobs/${jobId}/retry`),
  deleteArticle: (articleId: number) => del<any>(`/geo/articles/${articleId}`),
}
