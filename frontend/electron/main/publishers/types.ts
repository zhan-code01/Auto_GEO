/**
 * AutoGeo 发布引擎 - 共享类型定义
 *
 * 所有发布器（BasePublisher 及其子类）共用的接口与类型，
 * 编译为 CommonJS 模块（tsconfig "module": "CommonJS"）。
 */

/** 待发布的文章 */
export interface ArticlePayload {
  /** 数据库主键，新文章可能为 null */
  id: number | null
  /** 文章标题 */
  title: string | null
  /** 服务端下发的 HTML 正文 */
  content: string | null
}

/** 绑定到某个平台的帐号信息 */
export interface AccountInfo {
  /** 显示用帐号名 */
  account_name: string | null
  /** 平台标识，如 "zhihu"、"jianshu" */
  platform: string | null
  /** 认证方式，如 "cookie"、"token"、"oauth" */
  auth_mode: string | null
}

/** 发布操作的返回结果 */
export interface PublishResult {
  /** 是否成功 */
  success: boolean
  /** 发布后的文章链接（成功时） */
  url?: string
  /** 错误描述（失败时） */
  error?: string
  /** 是否需要人工介入 */
  manual_required?: boolean
  /** 人工介入的原因 */
  manual_reason?: string
}

/** 平台的静态配置信息 */
export interface PlatformConfig {
  /** 平台登录页 URL */
  login_url: string
  /** 平台发布页 URL */
  publish_url: string
  /** 平台显示名称 */
  name: string
}
