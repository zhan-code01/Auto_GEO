/**
 * Pinia Store 入口
 * 我用这个来注册所有 store！
 */

import { createPinia } from 'pinia'

const pinia = createPinia()

export default pinia

// 导出所有 store
export * from './modules/index'
