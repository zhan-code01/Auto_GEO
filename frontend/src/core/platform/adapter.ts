/**
 * 平台适配器接口和基类
 * 我用这个来实现开闭原则！
 */

import type { PlatformConfig } from '../config/platform'
import { getPlatformConfig } from '../config/platform'

// ==================== 类型定义 ====================

export interface AuthResult {
  success: boolean
  message: string
  data?: any
}

export interface PublishResult {
  success: boolean
  platformUrl?: string
  errorMsg?: string
}

export interface ValidationResult {
  valid: boolean
  errors: string[]
}

export interface Article {
  id?: number
  title: string
  content: string
  tags?: string[]
  category?: string
  coverImage?: string
}

export interface Account {
  id: number
  platformId: string
  accountName: string
  username?: string
  status: number
  lastAuthTime?: string
}

// ==================== 适配器接口 ====================

/**
 * 平台适配器接口
 * 我定义这个接口，所有平台适配器必须实现！
 */
export interface IPlatformAdapter {
  /** 平台标识 */
  readonly platformId: string

  /** 认证相关 */
  startAuth(): Promise<AuthResult>
  checkAuthStatus(): Promise<boolean>

  /** 发布相关 */
  startPublish(article: Article): Promise<PublishResult>
  checkPublishStatus(taskId: string): Promise<any>

  /** 验证相关 */
  validateArticle(article: Article): ValidationResult

  /** 工具方法 */
  getAuthUrl(): string
  getPublishUrl(): string
  getConfig(): PlatformConfig
}

// ==================== 适配器基类 ====================

/**
 * 平台适配器基类
 * 我实现了通用逻辑，子类只需实现特定方法！
 */
export abstract class BasePlatformAdapter implements IPlatformAdapter {
  abstract readonly platformId: string

  protected config: PlatformConfig

  constructor(platformId?: string) {
    this.config = getPlatformConfig(platformId || '') || {} as PlatformConfig
  }

  /**
   * 开始授权（默认实现）
   * 子类可以覆盖实现特定逻辑
   */
  async startAuth(): Promise<AuthResult> {
    // 默认通过后端API启动授权
    return { success: true, message: '授权已启动' }
  }

  /**
   * 检查授权状态
   */
  async checkAuthStatus(): Promise<boolean> {
    return false
  }

  /**
   * 开始发布（子类必须实现）
   */
  abstract startPublish(article: Article): Promise<PublishResult>

  /**
   * 检查发布状态
   */
  async checkPublishStatus(taskId: string): Promise<any> {
    return { taskId, status: 'pending' }
  }

  /**
   * 验证文章格式（通用实现）
   * 我实现了通用验证逻辑！
   */
  validateArticle(article: Article): ValidationResult {
    const errors: string[] = []

    // 验证标题长度
    const [minTitle, maxTitle] = this.config.limits.titleLength
    if (!article.title || article.title.length < minTitle) {
      errors.push(`标题长度不能少于 ${minTitle} 个字符`)
    }
    if (article.title && article.title.length > maxTitle) {
      errors.push(`标题长度不能超过 ${maxTitle} 个字符`)
    }

    // 验证内容长度
    const [minContent, maxContent] = this.config.limits.contentLength
    if (!article.content || article.content.length < minContent) {
      errors.push(`内容长度不能少于 ${minContent} 个字符`)
    }
    if (article.content && article.content.length > maxContent) {
      errors.push(`内容长度不能超过 ${maxContent} 个字符`)
    }

    return {
      valid: errors.length === 0,
      errors,
    }
  }

  /**
   * 获取授权URL
   */
  getAuthUrl(): string {
    return this.config.auth.loginUrl
  }

  /**
   * 获取发布URL
   */
  getPublishUrl(): string {
    return this.config.publish.entryUrl
  }

  /**
   * 获取平台配置
   */
  getConfig(): PlatformConfig {
    return this.config
  }
}

// ==================== 平台注册中心 ====================

/**
 * 平台注册中心
 * 我用这个来管理所有平台适配器！
 */
class PlatformRegistry {
  private adapters = new Map<string, IPlatformAdapter>()

  /** 注册平台适配器 */
  register(adapter: IPlatformAdapter): void {
    this.adapters.set(adapter.platformId, adapter)
  }

  /** 获取平台适配器 */
  get(platformId: string): IPlatformAdapter | undefined {
    return this.adapters.get(platformId)
  }

  /** 获取所有已注册平台 */
  getAll(): IPlatformAdapter[] {
    return Array.from(this.adapters.values())
  }

  /** 检查平台是否已注册 */
  has(platformId: string): boolean {
    return this.adapters.has(platformId)
  }
}

// 导出单例
export const platformRegistry = new PlatformRegistry()
