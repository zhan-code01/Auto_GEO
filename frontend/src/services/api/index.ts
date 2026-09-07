/**
 * API 服务 - 完整加固版 v2.2
 * 修复记录：
 * 1. 补全 accountApi.delete (修复删除账号报错)
 * 2. 补全 accountApi.getAuthStatus (修复授权轮询报错)
 * 3. 补全 accountApi.update (修复编辑账号功能)
 * 4. 保持了 reportsApi 和 geoArticleApi 的正确命名
 */

import axios, { type AxiosInstance, type AxiosRequestConfig, type AxiosResponse } from 'axios'
import { ElMessage } from 'element-plus'

// 扩展 axios 请求配置：允许单次请求传 silent 抑制统一 toast
declare module 'axios' {
  interface AxiosRequestConfig {
    silent?: boolean
  }
}

// API 基础地址
const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL

// 判断是否在 Electron 打包环境中（Electron 应用不走 Vite 代理）
const isElectronApp = typeof window !== 'undefined' &&
  (window.navigator.userAgent.includes('Electron') ||
   window.__ELECTRON_ENV__ === 'production')

// 判断是否是有效的本机 HTTP 地址
const isLocalhostUrl = /^https?:\/\/(?:localhost|127\.0\.0\.1)(?::\d+)?\/api\/?$/i.test(configuredBaseUrl || '')

// 在 Electron 打包环境中，使用绝对地址；开发环境用相对路径走 Vite 代理
const BASE_URL = (isLocalhostUrl && isElectronApp)
  ? configuredBaseUrl
  : (isLocalhostUrl ? '/api' : (configuredBaseUrl || '/api'))

/**
 * 创建 axios 实例
 */
const instance: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  timeout: 300000, // 增加到5分钟超时，适应AI检测的长耗时
  // 不设默认 Content-Type，axios 会自动处理：
  // - JSON 对象 → application/json
  // - FormData → multipart/form-data (由浏览器设)
})

/**
 * 请求拦截器 — 自动注入 JWT Token
 */
instance.interceptors.request.use(
  (config) => {
    // 从 localStorage 读取 Token 并注入到请求头
    const token = localStorage.getItem('autogeo_token')
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

/**
 * 响应拦截器 — 统一处理错误
 * 401：静默清除 token（不硬跳转，由路由守卫处理）
 *
 * 单次请求可传 `{ silent: true }` 抑制 toast（用于 debounce 自动触发、
 * detail 为结构化对象需页面自管提示等场景）。仍会 reject，401 仍会静默清 token。
 */
instance.interceptors.response.use(
  (response: AxiosResponse) => {
    return response.data
  },
  (error) => {
    // 401 未授权 → 静默清除 token，不硬跳转（避免打断其他页面的正常使用）
    if (error.response?.status === 401) {
      localStorage.removeItem('autogeo_token')
      localStorage.removeItem('autogeo_user')
      // 不弹 ElMessage，不硬跳转，只静默清除
      return Promise.reject(error)
    }

    console.error('响应错误:', error)
    const message = error.response?.data?.detail || error.response?.data?.message || error.message || '请求失败'

    // 如果是 500 错误，在控制台详细打印以便调试
    if (error.response?.status === 500) {
        console.error("🚨 后端 500 错误详情:", error.response.data);
    }

    // silent: 由调用方自行处理提示（如智能建站 build/deploy）
    if (error.config?.silent) {
      return Promise.reject(error)
    }

    // 业务冲突类错误（用户名已存在、邮箱已被注册等）使用 warning 提示，而非 error 报错
    const isBusinessConflict = error.response?.status === 400 && /已存在|已被注册/.test(message)
    if (isBusinessConflict) {
        ElMessage.warning(message)
    } else {
        ElMessage.error(message)
    }
    return Promise.reject(error)
  }
)

// 通用请求方法封装
export const request = async <T = any>(config: AxiosRequestConfig): Promise<T> => {
  return instance.request(config) as Promise<T>
}

export const get = <T = any>(url: string, params?: any, config?: AxiosRequestConfig): Promise<T> => {
  return request<T>({ method: 'GET', url, params, ...config })
}

export const post = <T = any>(url: string, data?: any, config?: AxiosRequestConfig): Promise<T> => {
  return request<T>({ method: 'POST', url, data, ...config })
}

export const put = <T = any>(url: string, data?: any, config?: AxiosRequestConfig): Promise<T> => {
  return request<T>({ method: 'PUT', url, data, ...config })
}

export const patch = <T = any>(url: string, data?: any, config?: AxiosRequestConfig): Promise<T> => {
  return request<T>({ method: 'PATCH', url, data, ...config })
}

export const del = <T = any>(url: string, params?: any, config?: AxiosRequestConfig): Promise<T> => {
  return request<T>({ method: 'DELETE', url, params, ...config })
}

// ==================== 1. 账号管理 API — 全面增强版 ====================
export const accountApi = {
  // ---------- 基础 CRUD ----------
  // 获取列表（支持分页、平台/状态/分组/标签筛选）
  getList: (params?: any) => get('/accounts', params),

  // 获取详情
  getDetail: (id: number) => get(`/accounts/${id}`),

  // 创建账号
  create: (data: any) => post('/accounts', data),

  // 更新账号（名称/状态/备注/分组/标签）
  update: (id: number, data: any) => put(`/accounts/${id}`, data),

  // 删除账号（默认软删除）
  delete: (id: number, hard: boolean = false) => del(`/accounts/${id}`, { hard }),

  // 账号统计（total/authorized/disabled，已软删除的不计入）
  getStats: () => get('/accounts/stats'),

  // ---------- 贴吧目标吧 ----------
  // 读取贴吧账号已配置的目标吧列表（第一个为默认发布吧）
  getTiebaForums: (id: number) => get(`/accounts/${id}/tieba-forums`),

  // 设置贴吧账号的目标吧列表（第一个为默认；换吧只需调整顺序）
  setTiebaForums: (id: number, forums: string[]) => put(`/accounts/${id}/tieba-forums`, { forums }),

  // ---------- 授权流程 ----------
  // 发起授权 (启动浏览器)
  startAuth: (data: any) => post('/accounts/auth/start', data),

  // 授权运行环境诊断（部署排查）
  getAuthDiagnostics: () => get('/accounts/auth/diagnostics'),

  // 查询授权状态 (轮询)
  getAuthStatus: (taskId: string) => get(`/accounts/auth/status/${taskId}`),

  // 保存授权结果
  saveAuth: (taskId: string, accountId: number) => post(`/accounts/auth/save/${taskId}`, { account_id: accountId }),

  // 确认授权完成
  confirmAuth: (taskId: string) => post(`/accounts/auth/confirm/${taskId}`),

  // 取消授权任务
  cancelAuth: (taskId: string) => del(`/accounts/auth/task/${taskId}`),

  // ---------- 检测 ----------
  // 检测所有账号授权状态（服务端轻量检查，仅查 DB cookie 是否存在）
  checkAll: () => post('/accounts/check/all'),

  // 本地客户端「一键检测所有」回写检测结果（真相引擎）
  // authStatus: 'ok' | 'logged_out' | 'unknown'
  reportCheckResult: (accountId: number, authStatus: string) =>
    post(`/accounts/${accountId}/check-result`, { auth_status: authStatus }),

  // ---------- 分组管理 ----------
  // 获取分组列表
  getGroups: () => get('/accounts/groups/list'),

  // 创建分组
  createGroup: (data: { name: string; icon?: string; color?: string }) => post('/accounts/groups', data),

  // 更新分组
  updateGroup: (id: number, data: any) => put(`/accounts/groups/${id}`, data),

  // 删除分组
  deleteGroup: (id: number) => del(`/accounts/groups/${id}`),

  // ---------- 批量操作 ----------
  // 批量更新状态
  batchStatus: (accountIds: number[], status: number) =>
    post('/accounts/batch/status', { account_ids: accountIds, status }),

  // 批量删除
  batchDelete: (accountIds: number[]) =>
    post('/accounts/batch/delete', { account_ids: accountIds }),

  // 批量移动分组
  batchMoveGroup: (accountIds: number[], groupId: number | null) =>
    post('/accounts/batch/move-group', { account_ids: accountIds, group_id: groupId }),

  // 批量检测
  batchCheck: (accountIds: number[]) =>
    post('/accounts/batch/check', { account_ids: accountIds }),

  // 批量导入
  batchImport: (accounts: any[]) =>
    post('/accounts/import', { accounts }),

  // 导出 CSV
  exportCsv: () => get('/accounts/export'),

  // ---------- 过期预警 ----------
  // 获取即将过期的账号
  getExpiring: (days: number = 7) => get('/accounts/expiring/list', { days }),

  // ---------- 操作日志 ----------
  // 获取操作日志
  getLogs: (params?: { account_id?: number; page?: number; limit?: number }) =>
    get('/accounts/logs/list', params),
}

// ==================== 2. GEO 关键词 API ====================
export const geoKeywordApi = {
  getProjects: () => get('/keywords/projects'),
  getProject: (id: number) => get(`/keywords/projects/${id}`),
  getProjectKeywords: (projectId: number) => get(`/keywords/projects/${projectId}/keywords`),
  
  createProject: (data: any) => post('/keywords/projects', data),
  updateProject: (id: number, data: any) => put(`/keywords/projects/${id}`, data),
  deleteProject: (id: number) => del(`/keywords/projects/${id}`),
  createKeyword: (projectId: number, data: any) => post(`/keywords/projects/${projectId}/keywords`, data),
  
  distill: (data: any) => post('/keywords/distill', data),
  generateQuestions: (data: any) => post('/keywords/generate-questions', data),
  getKeywordQuestions: (keywordId: number) => get(`/keywords/${keywordId}/questions`),

  // 关键词删除
  deleteKeyword: (keywordId: number) => del(`/keywords/${keywordId}`),
  deleteAllKeywords: (projectId: number) => del(`/keywords/projects/${projectId}/keywords`),
}

// ==================== 3. GEO 文章 API ====================
export const geoArticleApi = {
  getList: (params?: { page?: number; limit?: number; keyword?: string; status?: number }) =>
    get('/articles', params),
  create: (data: any) => post('/articles', data),

  // 获取文章列表 (对应 Articles.vue)
  // 支持按 publish_status 和 project_id 过滤，用于批量发布时只获取待发布的文章
  getArticles: (params?: { limit?: number; publish_status?: string | string[]; project_id?: number }) => get('/geo/articles', params),

  // 生成文章 (5分钟超时) - 新增发布策略参数
  generate: (data: {
    keyword_id: number;
    company_name?: string;
    target_platforms?: string[];
    publish_strategy?: string;
    scheduled_at?: string;
  }) =>
    post('/geo/generate', data, { timeout: 300000 }),

  // 按项目批量生成：后端按搜索问题队列逐条执行
  generateProject: (data: {
    project_id: number;
    target_platforms?: string[];
    publish_strategy?: string;
    scheduled_at?: string;
  }) =>
    post('/geo/generate/project', data, { timeout: 300000 }),

  // 质检
  checkQuality: (id: number) => post(`/geo/articles/${id}/check-quality`),

  // 手动检测收录状态
  checkIndex: (id: number) => post(`/geo/articles/${id}/check-index`),

  getDetail: (id: number) => get(`/geo/articles/${id}`),

  // 编辑文章标题/正文
  update: (id: number, data: { title?: string; content?: string }) =>
    put(`/geo/articles/${id}`, data),

  delete: (id: number) => del(`/geo/articles/${id}`)
}

// ==================== 4. 收录检测 API (监控页) ====================
export const indexCheckApi = {
  // 执行收录检测
  checkKeyword: (data: { keyword_id: number; company_name: string; platforms?: string[] }) =>
    post<any>('/index-check/check', data),

  // 批量检测
  batchCheck: (data: { project_id?: number; keyword_ids?: number[]; company_name?: string; platforms?: string[] }) =>
    post<any>('/index-check/batch/check', data),

  // 获取检测记录
  getRecords: (params?: {
    keyword_id?: number
    platform?: string
    limit?: number
    skip?: number
    keyword_found?: boolean
    company_found?: boolean
    start_date?: string
    end_date?: string
    question?: string
    project_id?: number
    check_phase?: string
  }) => get<any>('/index-check/records', params),

  // 删除单条记录
  deleteRecord: (id: number) => del<any>(`/index-check/records/${id}`),

  // 批量删除记录
  batchDeleteRecords: (recordIds: number[]) => post<any>('/index-check/records/batch-delete', { record_ids: recordIds }),

  // 获取关键词趋势
  getKeywordTrend: (keywordId: number, days?: number) =>
    get<any>(`/index-check/keywords/${keywordId}/trend`, { days }),

  // 获取项目统计
  getProjectStats: (projectId: number) => get<any>(`/index-check/projects/${projectId}/analytics`),

  // 执行单关键词收录检测
  check: (data: { keyword_id: number; company_name: string; platforms?: string[] }) => 
    post('/index-check/check', data),
  
  getTrend: (keywordId: number, days = 7) => get(`/index-check/trend/${keywordId}`, { days }),
}

export const geoEvaluationApi = {
  // Get project evaluation config
  getConfig: (projectId: number, config?: AxiosRequestConfig) =>
    get<any>(`/geo-evaluation/projects/${projectId}/config`, undefined, config),

  // Generate prompt set
  generatePromptSet: (projectId: number, data?: any, config?: AxiosRequestConfig) =>
    post<any>(`/geo-evaluation/projects/${projectId}/prompt-set/generate`, data || {}, config),

  // Get prompts
  getPrompts: (projectId: number, params?: any, config?: AxiosRequestConfig) =>
    get<any>(`/geo-evaluation/projects/${projectId}/prompts`, params, config),

  // Create baseline
  createBaseline: (projectId: number, data?: any, config?: AxiosRequestConfig) =>
    post<any>(`/geo-evaluation/projects/${projectId}/baseline`, data || {}, config),

  // Complete baseline for new platforms
  completeBaseline: (projectId: number, data?: any, config?: AxiosRequestConfig) =>
    post<any>(`/geo-evaluation/projects/${projectId}/baseline/complete`, data || {}, config),

  // Run post-baseline recheck
  runRecheck: (projectId: number, data?: any, config?: AxiosRequestConfig) =>
    post<any>(`/geo-evaluation/projects/${projectId}/recheck`, data || {}, config),

  // Get GEO metric diagnosis
  getDiagnosis: (projectId: number, params?: any, config?: AxiosRequestConfig) =>
    get<any>(`/geo-evaluation/projects/${projectId}/diagnosis`, params, config),

  // Get evidence records
  getRecords: (projectId: number, params?: any, config?: AxiosRequestConfig) =>
    get<any>(`/geo-evaluation/projects/${projectId}/records`, params, config),

  // Clear all evidence records for a project
  clearRecords: (projectId: number, config?: AxiosRequestConfig) =>
    del<any>(`/geo-evaluation/projects/${projectId}/records`, undefined, config),

  // Delete selected evidence records for a project
  batchDeleteRecords: (projectId: number, recordIds: number[], config?: AxiosRequestConfig) =>
    post<any>(`/geo-evaluation/projects/${projectId}/records/batch-delete`, { record_ids: recordIds }, config),

  // Retry selected failed evidence records for a project
  retryRecords: (projectId: number, recordIds: number[], config?: AxiosRequestConfig) =>
    post<any>(`/geo-evaluation/projects/${projectId}/records/retry`, { record_ids: recordIds }, config),

  // Get evaluation run status
  getRunStatus: (runId: number, config?: AxiosRequestConfig) =>
    get<any>(`/geo-evaluation/runs/${runId}/status`, undefined, config),

  resumeRun: (runId: number, config?: AxiosRequestConfig) =>
    post<any>(`/geo-evaluation/runs/${runId}/resume`, {}, config),

  pauseRun: (runId: number, config?: AxiosRequestConfig) =>
    post<any>(`/geo-evaluation/runs/${runId}/pause`, {}, config),

  cancelRun: (runId: number, config?: AxiosRequestConfig) =>
    post<any>(`/geo-evaluation/runs/${runId}/cancel`, {}, config),

  // ==================== 公司级别接口 ====================

  // Get client evaluation config（主接口）
  getClientConfig: (clientId: number, config?: AxiosRequestConfig) =>
    get<any>(`/geo-evaluation/clients/${clientId}/config`, undefined, config),

  // Generate client prompt set（主接口）
  generateClientPromptSet: (clientId: number, data?: any, config?: AxiosRequestConfig) =>
    post<any>(`/geo-evaluation/clients/${clientId}/prompt-set/generate`, data || {}, config),

  // Get client prompts（主接口）
  getClientPrompts: (clientId: number, params?: any, config?: AxiosRequestConfig) =>
    get<any>(`/geo-evaluation/clients/${clientId}/prompts`, params, config),

  // Create client baseline（主接口）
  createClientBaseline: (clientId: number, data?: any, config?: AxiosRequestConfig) =>
    post<any>(`/geo-evaluation/clients/${clientId}/baseline`, data || {}, config),

  // Complete client baseline（主接口）
  completeClientBaseline: (clientId: number, data?: any, config?: AxiosRequestConfig) =>
    post<any>(`/geo-evaluation/clients/${clientId}/baseline/complete`, data || {}, config),

  // Run client recheck（主接口）
  runClientRecheck: (clientId: number, data?: any, config?: AxiosRequestConfig) =>
    post<any>(`/geo-evaluation/clients/${clientId}/recheck`, data || {}, config),

  // Get client GEO diagnosis（主接口）
  getClientLatestRun: (clientId: number, params?: any, config?: AxiosRequestConfig) =>
    get<any>(`/geo-evaluation/clients/${clientId}/runs/latest`, params, config),

  getClientDiagnosis: (clientId: number, params?: any, config?: AxiosRequestConfig) =>
    get<any>(`/geo-evaluation/clients/${clientId}/diagnosis`, params, config),

  // Get client competitor & source analysis（竞品与来源分析）
  getClientCompetitorAnalysis: (clientId: number, params?: any, config?: AxiosRequestConfig) =>
    get<any>(`/geo-evaluation/clients/${clientId}/competitor-analysis`, params, config),

  // Get client evidence records（主接口）
  getClientRecords: (clientId: number, params?: any, config?: AxiosRequestConfig) =>
    get<any>(`/geo-evaluation/clients/${clientId}/records`, params, config),

  // Clear all client evidence records
  clearClientRecords: (clientId: number, config?: AxiosRequestConfig) =>
    del<any>(`/geo-evaluation/clients/${clientId}/records`, undefined, config),

  // Batch delete client evidence records
  batchDeleteClientRecords: (clientId: number, recordIds: number[], config?: AxiosRequestConfig) =>
    post<any>(`/geo-evaluation/clients/${clientId}/records/batch-delete`, { record_ids: recordIds }, config),

  // Retry selected failed client evidence records
  retryClientRecords: (clientId: number, recordIds: number[], config?: AxiosRequestConfig) =>
    post<any>(`/geo-evaluation/clients/${clientId}/records/retry`, { record_ids: recordIds }, config),
}

// ==================== 5b. GEO 监控（兼容旧 Monitor.vue slice） ====================

// ==================== 5. 报表 API ====================
// 仅保留首页 Dashboard 仍在使用的接口（overview / article-stats / stats）
export const reportsApi = {
  // 获取总览数据
  getOverview: () => get<any>('/reports/overview'),

  // 获取文章统计
  getArticleStats: (params?: { project_id?: number }) => get<any>('/reports/article-stats', params),

  // 数据总览卡片（首页「今日发布」等）
  getStats: (params: { project_id?: number; days?: number }) => get('/reports/stats', params),
}

// ==================== 6. 定时任务 API ====================
export const schedulerApi = {
  getJobs: () => get('/scheduler/jobs'),
  updateJob: (id: number, data: { cron_expression: string; is_active: boolean }) =>
    put(`/scheduler/jobs/${id}`, data),
  runJob: (jobId: string) => post(`/scheduler/jobs/${jobId}/run`, {}),
  start: () => post('/scheduler/start', {}),
  stop: () => post('/scheduler/stop', {}),
}

// ==================== 7. 发布管理 API ====================
export const publishApi = {
  // 获取支持的发布平台
  getPlatforms: () => get('/publish/platforms'),

  // 创建发布任务
  create: (data: { article_ids: number[]; account_ids: number[] }) => post('/publish/create', data),
  createTask: (data: { article_ids: number[]; account_ids: number[] }) => post('/publish/create', data),

  // 批量发布 GEO 文章（针对 GeoArticle，支持状态过滤）
  batch: (data: { article_ids: number[]; account_ids: number[]; scheduled_time?: string }) =>
    post('/publish/batch', data),

  // 🌟 立即发布 - 将文章状态设为 publishing 并立即启动
  start: (data: { article_ids: number[]; account_ids: number[] }) => post('/publish/start', data),

  // 🌟 定时发布 - 设置 scheduled_at 时间，等待调度器执行
  schedule: (data: { article_ids: number[]; account_ids: number[]; scheduled_time: string }) =>
    put('/publish/schedule', data),

  // 🌟 手动插队发布 - 无视定时时间，直接执行发布
  trigger: (articleId: number) => post(`/publish/trigger/${articleId}`),

  // 获取发布进度
  getProgress: (taskId: string) => get(`/publish/progress/${taskId}`),

  // 获取发布记录
  getRecords: (params?: any) => get('/publish/records', params),

  // 重试发布
  retry: (recordId: number) => post(`/publish/retry/${recordId}`)
}

// ==================== 8. 客户管理 API ====================
export const clientApi = {
  // 获取客户列表
  getList: (params?: {
    page?: number
    limit?: number
    status?: number
    keyword?: string
    industry?: string
  }) => get<any>('/clients', params),

  // 获取客户详情
  getDetail: (id: number) => get<any>(`/clients/${id}`),

  // 获取客户项目列表
  getProjects: (clientId: number) => get<any>(`/clients/${clientId}/projects`),

  // 创建客户
  create: (data: {
    name: string
    company_name?: string
    contact_person?: string
    phone?: string
    email?: string
    industry?: string
    location?: string
    website?: string
    address?: string
    description?: string
    status?: number
  }) => post<any>('/clients', data),

  // 更新客户
  update: (id: number, data: any) => put<any>(`/clients/${id}`, data),

  // 删除客户
  delete: (id: number) => del<any>(`/clients/${id}`),

  // 获取统计数据
  getStats: () => get<any>('/clients/stats/overview'),

  // 获取行业列表
  getIndustries: () => get<any>('/clients/indicators/list'),

  // 上传客户资料到RAGFlow知识库
  uploadFiles: (formData: FormData) =>
    post<any>('/knowledge/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 300000
    })
}

// ==================== 9. 自动发布任务 API ====================
export const autoPublishApi = {
  // 获取任务列表
  getTasks: (params?: { status?: string | string[]; limit?: number; offset?: number }) =>
    get('/auto-publish/tasks', params),

  // 获取任务详情（含子任务记录）
  getTask: (taskId: number) => get(`/auto-publish/tasks/${taskId}`),

  // 创建任务
  create: async (data: {
    name: string
    description?: string
    article_ids: number[]
    account_ids: number[]
    exec_type: 'immediate' | 'scheduled' | 'interval'
    run_in_background?: boolean
    scheduled_at?: string
    interval_minutes?: number
    declare_ai_content?: boolean
    execution_mode?: 'local_client' | 'cloud_browser' | 'api' | 'manual'
    assigned_device_id?: string
    targets?: Array<{ article_id: number; account_id: number }>
  }) => {
    let payload = data
    if (!data.assigned_device_id) {
      const electronAPI = (window as any).electronAPI
      if (electronAPI?.device?.getInfo) {
        try {
          const info = await electronAPI.device.getInfo()
          if (info?.device_id) {
            payload = { ...data, assigned_device_id: info.device_id }
          }
        } catch {
          // 读取设备信息失败时保持不绑定，不阻断创建任务
        }
      }
    }
    return post('/auto-publish/tasks', payload)
  },

  // 更新任务
  update: (taskId: number, data: {
    name?: string
    description?: string
    status?: string
    scheduled_at?: string
    interval_minutes?: number
  }) => put(`/auto-publish/tasks/${taskId}`, data),

  // 删除任务
  delete: (taskId: number) => del(`/auto-publish/tasks/${taskId}`),

  // 手动启动任务
  start: (taskId: number) => post(`/auto-publish/tasks/${taskId}/start`),

  // 取消任务
  cancel: (taskId: number) => post(`/auto-publish/tasks/${taskId}/cancel`),

  // 重试失败任务
  retry: (taskId: number) => post(`/auto-publish/tasks/${taskId}/retry`),

  // 获取最近的子任务记录（用于首页最近活动）
  getRecentRecords: (params?: { status?: string; limit?: number }) =>
    get<any>('/auto-publish/records', params),
}

// ==================== 10. 后台智能体对话 API ====================
export interface ConversationAttachment {
  ref: string
  filename: string
  category_id?: number | string
  category_name?: string
  client_id?: number
  company_name?: string
  kind?: 'material'
}

export interface ConversationAction {
  type: string // confirm / bind / clarify / create / next / upload / onboard / dismiss_onboarding ...
  label: string
  payload?: Record<string, any>
  link?: string
  disabled?: boolean // 不可点击（如"文章生成中…"占位卡）
}

export interface ConversationResult {
  success: boolean
  status: string
  reply: string
  conversation_id: string
  trace_id: string
  intent: string
  need_user_input: boolean
  next_questions: string[]
  task_id?: number | null
  article_id?: number | null
  params: Record<string, any>
  context: Record<string, any>
  actions?: ConversationAction[]
  async_task_refs?: { task_type: string; task_id: string; platform: string }[]
  tool_trace?: { name: string; ok: boolean; error?: string }[]
}

// 历史会话列表项（GET /agent-v2/sessions → items）
export interface ConversationSessionItem {
  id: string
  title: string | null
  status: string
  current_intent: string | null
  last_message: string | null
  last_message_role: string | null
  updated_at: string | null
}

// ==================== 11. 健康检查 API ====================
export interface HealthStatus {
  status: 'ok' | 'degraded' | 'error'
  timestamp: string
  services: {
    database: { status: 'connected' | 'error' | 'not_configured' | 'unknown'; message?: string }
    ragflow: { status: 'connected' | 'error' | 'not_configured' | 'unknown'; message?: string; code?: number }
  }
}

export const systemApi = {
  // 获取健康状态
  // 允许调用方透传 axios config（如 { timeout, silent }），用于单独控制超时、抑制全局错误提示
  getHealth: (config?: AxiosRequestConfig) => get<HealthStatus>('/health', undefined, config)
}

// ==================== 12. 知识库 API ====================
export const knowledgeApi = {
  // 企业分类
  getCategories: (params?: { keyword?: string; search?: string; page?: number; limit?: number }) => get<any>('/knowledge/categories', params),
  createCategory: (data: any) => post<any>('/knowledge/categories', data),
  updateCategory: (id: number, data: any) => put<any>(`/knowledge/categories/${id}`, data),
  deleteCategory: (id: number) => del<any>(`/knowledge/categories/${id}`),

  // 知识项
  getKnowledgeByCategory: (categoryId: number, params?: { keyword?: string }) =>
    get<any>(`/knowledge/categories/${categoryId}/knowledge`, params),
  createKnowledge: (categoryId: number, data: any) =>
    post<any>(`/knowledge/categories/${categoryId}/knowledge`, data),
  updateKnowledge: (id: number, data: any) => put<any>(`/knowledge/knowledge/${id}`, data),
  deleteKnowledge: (id: number) => del<any>(`/knowledge/knowledge/${id}`),

  // RAGFlow 直接管理
  getRAGFlowStatus: () => get<any>('/knowledge/ragflow/status'),
  getRAGFlowDatasets: (params?: { page?: number; limit?: number; search?: string }) =>
    get<any>('/knowledge/ragflow/datasets', params),
  createRAGFlowDataset: (data: { name: string; description?: string }) =>
    post<any>('/knowledge/ragflow/datasets', data),
  getRAGFlowDataset: (datasetId: string) => get<any>(`/knowledge/ragflow/datasets/${datasetId}`),
  updateRAGFlowDataset: (datasetId: string, data: any) =>
    put<any>(`/knowledge/ragflow/datasets/${datasetId}`, data),
  deleteRAGFlowDataset: (datasetId: string) =>
    del<any>(`/knowledge/ragflow/datasets/${datasetId}`),
  getRAGFlowDocuments: (datasetId: string, params?: any) =>
    get<any>(`/knowledge/ragflow/datasets/${datasetId}/documents`, params),
  getRAGFlowDocument: (datasetId: string, documentId: string) =>
    get<any>(`/knowledge/ragflow/datasets/${datasetId}/documents/${documentId}`),
  getRAGFlowDocumentDownloadUrl: (datasetId: string, documentId: string) =>
    get<any>(`/knowledge/ragflow/datasets/${datasetId}/documents/${documentId}/download`),
  deleteRAGFlowDocument: (datasetId: string, documentId: string) =>
    del<any>(`/knowledge/ragflow/datasets/${datasetId}/documents/${documentId}`),
  parseRAGFlowDocument: (datasetId: string, documentId: string) =>
    post<any>(`/knowledge/ragflow/datasets/${datasetId}/documents/${documentId}/parse`, {}),
  uploadRAGFlowDocument: (datasetId: string, formData: FormData) =>
    post<any>(`/knowledge/ragflow/datasets/${datasetId}/documents`, formData),
  getRAGFlowChunks: (datasetId: string, params?: { document_id?: string; page?: number; limit?: number }) =>
    get<any>(`/knowledge/ragflow/datasets/${datasetId}/chunks`, params)
}

// ==================== 13. 智能建站 API ====================
export const siteApi = {
  // 生成预览站点（debounce 自动触发，失败由页面自管提示）
  build: (data: { name: string; config: any; template_id: string }) =>
    post<any>('/sites/build', data, { silent: true }),
  // 发布站点（SFTP / S3）；后端 detail 为结构化对象 {code,message,suggestion}，由页面自管提示
  deploy: (data: any) => post<any>('/sites/deploy', data, { silent: true }),
  // AI 一键生成网页（从客户知识库检索 → DeepSeek 提取 → 模板渲染）
  aiGenerate: (data: { client_id: number; template_id: string; extra_instructions?: string }) =>
    post<any>('/sites/ai-generate', data),
  // 用已有结构化数据重新渲染（换模板/微调字段，不调 AI）
  aiRegenerate: (data: { site_id: string; structured_data: any; template_id: string }) =>
    post<any>('/sites/ai-regenerate', data),
  // 列出可用的 AI 网页模板
aiTemplates: () => get<any>('/sites/ai-templates'),
}

// 导出统一的api对象
export const api = {
  account: accountApi,
  client: clientApi,
  geoKeyword: geoKeywordApi,
  geoArticle: geoArticleApi,
  indexCheck: indexCheckApi,
  reports: reportsApi,
  geoEvaluation: geoEvaluationApi,
  scheduler: schedulerApi,
  publish: publishApi,
  autoPublish: autoPublishApi,
  system: systemApi,
  knowledge: knowledgeApi,
  site: siteApi,
}

// 导出默认实例
export default instance
