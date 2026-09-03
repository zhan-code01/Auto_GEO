/**
 * 全局类型定义
 * 我用这个来统一管理所有类型！
 */

// ==================== 平台相关 ====================

export type PlatformId =
  | 'zhihu'
  | 'baijiahao'
  | 'sohu'
  | 'toutiao'
  | 'wenku'
  | 'penguin'
  | 'weixin'
  | 'wangyi'
  | 'zijie'
  | 'xiaohongshu'
  | 'bilibili'
  | '36kr'
  | 'huxiu'
  | 'woshipm'
  | 'douyin'
  | 'kuaishou'
  | 'video_account'
  | 'sohu_video'
  | 'weibo'
  | 'haokan'
  | 'xigua'
  | 'jianshu'
  | 'juejin'
  | 'iqiyi'
  | 'dayu'
  | 'acfun'
  | 'tencent_video'
  | 'yidian'
  | 'pipixia'
  | 'meipai'
  | 'douban'
  | 'kuai_chuan'
  | 'dafeng'
  | 'xueqiu'
  | 'yiche'
  | 'chejia'
  | 'duoduo'
  | 'weishi'
  | 'mango'
  | 'ximalaya'
  | 'meituan'
  | 'alipay'
  | 'douyin_company'
  | 'douyin_company_lead'
  | 'custom'

export interface PlatformConfig {
  id: PlatformId
  name: string
  code: string
  color: string
}

// ==================== 账号相关 ====================

export interface Account {
  id: number
  platform: PlatformId
  account_name: string
  username?: string
  status: AccountStatus
  last_auth_time?: string
  remark?: string
  created_at: string
  updated_at: string
}

export enum AccountStatus {
  DISABLED = 0,
  ACTIVE = 1,
  EXPIRED = -1,
}

// ==================== 文章相关 ====================

export interface Article {
  id: number
  title: string
  content: string
  tags?: string
  category?: string
  cover_image?: string
  status: ArticleStatus
  view_count: number
  created_at: string
  updated_at: string
  published_at?: string
}

export enum ArticleStatus {
  DRAFT = 0,
  PUBLISHED = 1,
}

// ==================== 发布相关 ====================

export interface PublishTask {
  id: string
  articleId: number
  articleTitle: string
  accountId: number
  accountName: string
  platform: PlatformId
  platformName: string
  status: PublishStatus
  platformUrl?: string
  errorMsg?: string
}

export enum PublishStatus {
  PENDING = 0,
  PUBLISHING = 1,
  SUCCESS = 2,
  FAILED = 3,
}

export interface PublishRecord {
  id: number
  articleId: number
  articleTitle: string
  accountId: number
  accountName: string
  platform: PlatformId
  platformName: string
  status: PublishStatus
  platformUrl?: string
  errorMsg?: string
  retryCount: number
  createdAt: string
  publishedAt?: string
}

// ==================== API 响应相关 ====================

export interface ApiResponse<T = any> {
  success: boolean
  message?: string
  data?: T
  timestamp?: string
}

export interface PaginatedResponse<T> {
  total: number
  items: T[]
  page?: number
  pageSize?: number
}

// ==================== 授权相关 ====================

export interface AuthResult {
  taskId: string
  status: 'pending' | 'success' | 'failed' | 'timeout'
  isLoggedIn?: boolean
  message?: string
}

// ==================== WebSocket 相关 ====================

export interface WSMessage {
  type: 'publish_progress' | 'publish_complete' | 'auth_complete'
  data: any
}

export interface PublishProgressMessage {
  taskId: string
  articleId: number
  articleTitle: string
  accountId: number
  accountName: string
  platform: PlatformId
  platformName: string
  status: PublishStatus
  errorMsg?: string
  platformUrl?: string
}

// ==================== 表单相关 ====================

export interface AccountFormData {
  platform: PlatformId
  account_name: string
  remark?: string
}

export interface ArticleFormData {
  title: string
  content: string
  tags?: string
  category?: string
  cover_image?: string
}

// ==================== 路由相关 ====================

export interface RouteMeta {
  title?: string
  icon?: string
  hidden?: boolean
}

// ==================== 账号检测相关 ====================

export interface AccountCheckResult {
  account_id: number
  platform: PlatformId
  account_name: string
  status_before: number
  is_valid: boolean
  message: string
  check_time: string
}

export interface AccountCheckSummary {
  total: number
  success: number
  failed: number
  results: AccountCheckResult[]
  check_time: string
}

export interface AccountCheckProgressMessage {
  type: 'account_check_progress' | 'account_check_complete'
  current?: number
  total?: number
  progress?: number
  result?: AccountCheckResult
  summary?: AccountCheckSummary
}
