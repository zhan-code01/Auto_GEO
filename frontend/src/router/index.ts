/**
 * 路由配置
 * 定义应用所有路由和侧边栏菜单结构
 */

import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router'
import { useUserStore } from '@/stores/modules/user'
import { ElMessage } from 'element-plus'

// 路由定义
const routes: RouteRecordRaw[] = [
  // 登录页（独立路由，不使用 MainLayout）
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/auth/LoginView.vue'),
    meta: { title: '登录', hidden: true, public: true },
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('@/views/auth/RegisterView.vue'),
    meta: { title: '注册', hidden: true, public: true },
  },
  {
    path: '/',
    component: () => import('@/views/layout/MainLayout.vue'),
    redirect: '/dashboard',
    children: [
      // 侧边栏菜单按业务流程排序：
      // 首页、客户管理、知识库管理、智能建站、关键词蒸馏、GEO文章生成、文章管理、账号管理、发布任务管理、批量发布、收录监控、数据报表、定时任务、系统设置

      // 1. 首页
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/views/dashboard/DashboardPage.vue'),
        meta: { title: '首页', icon: 'House', order: 1 },
      },

      // 2. 后台智能体
      {
        path: 'agent',
        name: 'AgentChat',
        component: () => import('@/views/agent/AgentChat.vue'),
        meta: { title: '后台智能体', icon: 'ChatDotRound', order: 2 },
      },

      // 3. 客户管理
      {
        path: 'clients',
        name: 'Clients',
        component: () => import('@/views/client/ClientPage.vue'),
        meta: { title: '客户管理', icon: 'UserFilled', order: 3 },
      },

      // 4. GEO项目管理
      {
        path: 'clients/projects',
        name: 'GeoProjects',
        component: () => import('@/views/geo/Projects.vue'),
        meta: { title: 'GEO项目管理', icon: 'Grid', order: 4 },
      },

      // 5. 知识库管理
      {
        path: 'knowledge',
        name: 'Knowledge',
        component: () => import('@/views/knowledge/KnowledgePage.vue'),
        meta: { title: '知识库管理', icon: 'Reading', order: 5 },
      },

      // 6. 智能建站
      {
        path: 'site-builder',
        name: 'SiteBuilder',
        component: () => import('@/views/site-builder/ConfigWizard.vue'),
        meta: { title: '智能建站', icon: 'Platform', order: 6 },
      },

      // 6.5 AI 网页生成（前端入口已隐藏，路由保留以便直接访问）
      {
        path: 'ai-webpage',
        name: 'AIWebPage',
        // @ts-expect-error - AIWebPage.vue is a dynamic Vue component
        component: () => import('@/views/site-builder/AIWebPage.vue'),
        meta: { title: 'AI 网页生成', icon: 'MagicStick', order: 6.5, menuHidden: true },
      },

      // 7. 文章生成（原关键词蒸馏已停用）
      {
        path: 'geo/articles',
        name: 'GeoArticles',
        component: () => import('@/views/geo/Articles.vue'),
        meta: { title: 'GEO文章生成', icon: 'EditPen', order: 8 },
      },

      // 8.2 智能文章生成（与旧 GEO 文章生成并列）
      {
        path: 'geo/smart-articles',
        name: 'SmartArticles',
        component: () => import('@/views/geo/SmartArticles.vue'),
        meta: { title: '智能文章生成', icon: 'MagicStick', order: 8.2 },
      },

      // 9. 文章管理
      {
        path: 'articles',
        name: 'Articles',
        component: () => import('@/views/article/ArticleList.vue'),
        meta: { title: '文章管理', icon: 'Document', order: 9 },
      },
      {
        path: 'articles/add',
        name: 'ArticleAdd',
        component: () => import('@/views/article/ArticleEdit.vue'),
        meta: { title: '新建文章', hidden: true },
      },
      {
        path: 'articles/edit/:id',
        name: 'ArticleEdit',
        component: () => import('@/views/article/ArticleEdit.vue'),
        meta: { title: '编辑文章', hidden: true },
      },
      {
        path: 'articles/batch-publish',
        name: 'BatchPublish',
        component: () => import('@/views/article/BatchPublish.vue'),
        meta: { title: '批量发布', hidden: true },
      },

      // 10. 账号管理
      {
        path: 'accounts',
        name: 'Accounts',
        component: () => import('@/views/account/AccountList.vue'),
        meta: { title: '账号管理', icon: 'User', order: 10 },
      },
      {
        path: 'accounts/add',
        name: 'AccountAdd',
        component: () => import('@/views/account/AccountAdd.vue'),
        meta: { title: '添加账号', hidden: true },
      },

      // 11. 发布任务管理
      {
        path: 'auto-publish',
        name: 'AutoPublish',
        component: () => import('@/views/publish/AutoPublishPage.vue'),
        meta: { title: '发布任务管理', icon: 'List', order: 11 },
      },

      // 12. 批量发布
      {
        path: 'publish',
        name: 'Publish',
        component: () => import('@/views/publish/PublishPage.vue'),
        meta: { title: '平台发布监控', icon: 'Monitor', order: 12 },
      },

      // 13. 收录监控
      {
        path: 'geo/monitor',
        name: 'GeoMonitor',
        component: () => import('@/views/geo/Monitor.vue'),
        meta: { title: '收录监控', icon: 'Monitor', order: 13 },
      },

      // 14. 定时任务
      {
        path: 'scheduler',
        name: 'Scheduler',
        component: () => import('@/views/scheduler/SchedulerPage.vue'),
        meta: { title: '定时任务', icon: 'Timer', order: 15 },
      },

      // 16. 系统设置
      {
        path: 'settings',
        name: 'Settings',
        component: () => import('@/views/settings/SettingsPage.vue'),
        meta: { title: '系统设置', icon: 'Setting', order: 16 },
      },

      // 用户菜单入口：账号绑定（不显示在侧边栏）
      {
        path: 'account-bindings',
        name: 'AccountBindings',
        component: () => import('@/views/account/AccountBindings.vue'),
        meta: { title: '账号绑定', icon: 'Link', menuHidden: true },
      },

      // 17. 后台管理（仅管理员）
      {
        path: 'admin',
        name: 'Admin',
        component: () => import('@/views/admin/AdminView.vue'),
        meta: { title: '后台管理', icon: 'Tools', order: 17, roles: ['admin'] },
      },

      // 18. 飞书用户绑定管理（仅管理员）
      {
        path: 'admin/feishu-bindings',
        name: 'FeishuBindings',
        component: () => import('@/views/admin/FeishuBindings.vue'),
        meta: { title: '飞书用户绑定', icon: 'Link', order: 18, roles: ['admin'] },
      },

    ],
  },
]

// 创建路由实例
const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

// 路由守卫
router.beforeEach(async (to, from, next) => {
  // 设置页面标题
  if (to.meta?.title) {
    document.title = `${to.meta.title} - AutoGeo`
  }

  // 获取用户 store
  const userStore = useUserStore()

  // 初始化用户状态（从本地存储恢复）
  if (!userStore.user) {
    userStore.initUser()
  }

  // 公开页面（如登录/注册页）直接放行
  // 注意：hidden 仅表示"不在侧边栏显示"，仍需要登录认证！
  if (to.meta?.public) {
    // 如果已登录且访问登录页，重定向到首页
    if (userStore.isLoggedIn && (to.path === '/login' || to.path === '/register')) {
      next('/dashboard')
      return
    }
    next()
    return
  }

  // 检查是否已登录
  if (!userStore.isLoggedIn) {
    // 尝试从服务器获取当前用户信息（token 可能还有效）
    const isValid = await userStore.fetchCurrentUser()
    if (!isValid) {
      ElMessage.warning('请先登录')
      next({
        path: '/login',
        query: { redirect: to.fullPath },
      })
      return
    }
  }

  // 检查角色权限
  const requiredRoles = to.meta?.roles as string[] | undefined
  if (requiredRoles && requiredRoles.length > 0) {
    if (!requiredRoles.includes(userStore.user?.role || '')) {
      ElMessage.error('您没有权限访问此页面')
      next('/dashboard')
      return
    }
  }

  next()
})

export default router
