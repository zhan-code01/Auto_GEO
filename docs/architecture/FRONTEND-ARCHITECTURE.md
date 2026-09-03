# auto_geo 前端架构设计文档

## 一、架构总览

### 1.1 技术栈选型

| 层级 | 技术选型 | 理由 |
|-----|---------|------|
| 框架 | **Electron 28+** | 跨平台桌面应用，成熟稳定 |
| 前端框架 | **Vue 3 + TypeScript** | Composition API + TS类型安全，开发效率高 |
| 构建工具 | **Vite** | 极速开发体验，原生ES模块支持 |
| 状态管理 | **Pinia** | Vue官方推荐，API简洁，TypeScript友好 |
| UI组件库 | **Element Plus** | 组件丰富，中文文档好 |
| 样式方案 | **SCSS + CSS Modules** | 变量系统，模块化隔离 |
| 通信层 | **axios + WebSocket** | HTTP API + 实时通信 |
| 工具库 | **lodash-es / dayjs** | 按需引入，包体积小 |

### 1.2 整体架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        Electron 主进程                          │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐      │
│  │  窗口管理     │  │  系统托盘     │  │  自动更新     │      │
│  │  WindowMgr    │  │  Tray         │  │  Updater      │      │
│  └───────────────┘  └───────────────┘  └───────────────┘      │
│                                │                                │
├────────────────────────────────┼────────────────────────────────┤
│                        IPC 通信层                              │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │     ipcMain/ipcRenderer + Bridge Pattern                │   │
│  └─────────────────────────────────────────────────────────┘   │
├────────────────────────────────┼────────────────────────────────┤
│                           ↓                                    │
│  ┌─────────────────────────────────────────────────────────┐   │
│ │                      渲染进程                              │   │
│ │ ┌─────────────────────────────────────────────────────┐  │   │
│ │ │                    页面层 (Pages)                    │  │   │
│ │ │  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐       │  │   │
│ │ │  │账号管理││文章编辑││批量发布││发布记录│  ...    │  │   │
│ │ │  └────────┘ └────────┘ └────────┘ └────────┘       │  │   │
│ │ ├─────────────────────────────────────────────────────┤  │   │
│ │ │                  业务组件层 (Business Components)    │  │   │
│ │ │  ┌──────────┐ ┌──────────┐ ┌──────────┐            │  │   │
│ │ │  │账号卡片  ││文章编辑器││发布进度条│  ...        │  │   │
│ │ │  └──────────┘ └──────────┘ └──────────┘            │  │   │
│ │ ├─────────────────────────────────────────────────────┤  │   │
│ │ │                  通用组件层 (Common Components)     │  │   │
│ │ │  ┌──────────┐ ┌──────────┐ ┌──────────┐            │  │   │
│ │ │  │按钮组件  ││表格组件  ││弹窗组件  │  ...        │  │   │
│ │ │  └──────────┘ └──────────┘ └──────────┘            │  │   │
│ │ ├─────────────────────────────────────────────────────┤  │   │
│ │ │                   平台适配层 (Platform Layer) ⭐     │  │   │
│ │ │  ┌──────────────────────────────────────────────┐  │  │   │
│ │ │  │           PlatformAdapter (适配器接口)        │  │  │   │
│ │ │  └──────────────────────────────────────────────┘  │  │   │
│ │ │           │           │           │               │  │   │
│ │ │      ┌────▼──┐    ┌───▼───┐   ┌──▼────┐          │  │   │
│ │ │      │知乎   │    │百家号 │   │搜狐   │  ...      │  │   │
│ │ │      │Zhihu  │    │Baijia │   │Sohu   │          │  │   │
│ │ │      └───────┘    └───────┘   └───────┘          │  │   │
│ │ ├─────────────────────────────────────────────────────┤  │   │
│ │ │                   状态管理层 (State)                │  │   │
│ │ │  ┌──────────┐ ┌──────────┐ ┌──────────┐            │  │   │
│ │ │  │accountStore│articleStore│publishStore│ ...     │  │   │
│ │ │  └──────────┘ └──────────┘ └──────────┘            │  │   │
│ │ ├─────────────────────────────────────────────────────┤  │   │
│ │ │                   服务层 (Services)                 │  │   │
│ │ │  ┌──────────┐ ┌──────────┐ ┌──────────┐            │  │   │
│ │ │  │API服务   ││IPC服务   ││存储服务  │  ...        │  │   │
│ │ │  └──────────┘ └──────────┘ └──────────┘            │  │   │
│ │ └─────────────────────────────────────────────────────┘  │   │
│ └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 二、目录结构设计

### 2.1 完整目录树

```
fronted/                          # 前端根目录（拼写保留）
│
├── electron/                     # ⚡ Electron主进程
│   ├── main/                     #    主进程核心代码
│   │   ├── index.ts             #        主入口
│   │   ├── window-manager.ts    #        窗口管理器
│   │   ├── ipc-handlers.ts      #        IPC处理器注册
│   │   ├── tray-manager.ts      #        系统托盘管理
│   │   └── updater.ts           #        自动更新
│   │
│   ├── preload/                  #    预加载脚本（安全桥接）
│   │   ├── index.ts             #        预加载入口
│   │   └── api-expose.ts        #        暴露给渲染进程的API
│   │
│   └── resources/                #    资源文件
│       ├── icons/               #        应用图标
│       └── splash/              #        启动画面
│
├── src/                          # 🎨 渲染进程源码
│   │
│   ├── main.ts                   #    应用入口
│   ├── App.vue                   #    根组件
│   ├── vite-env.d.ts            #    Vite类型声明
│   │
│   ├── core/                     #    🔧 核心层（框架基础设施）
│   │   ├── platform/            #        ⭐ 平台适配系统（核心扩展机制）
│   │   │   ├── types.ts         #            平台类型定义
│   │   │   ├── registry.ts      #            平台注册中心
│   │   │   ├── adapter.ts       #            平台适配器接口（抽象基类）
│   │   │   └── adapters/        #            各平台适配器实现
│   │   │       ├── base.ts      #                基础适配器
│   │   │       ├── zhihu.ts     #                知乎适配器
│   │   │       ├── baijiahao.ts #                百家号适配器
│   │   │       ├── sohu.ts      #                搜狐适配器
│   │   │       └── toutiao.ts   #                头条号适配器
│   │   │       # └── wechat.ts  #                微信适配器（预留）
│   │   │
│   │   ├── config/              #        配置管理
│   │   │   ├── index.ts         #            配置导出
│   │   │   ├── app.ts           #            应用配置
│   │   │   └── platform.ts      #            ⭐ 平台配置（扩展点）
│   │   │
│   │   ├── constants/           #        常量定义
│   │   │   ├── index.ts
│   │   │   ├── enum.ts          #            枚举常量
│   │   │   └── events.ts        #            事件名称
│   │   │
│   │   ├── utils/               #        工具函数
│   │   │   ├── index.ts         #            统一导出
│   │   │   ├── format.ts        #            格式化工具
│   │   │   ├── validate.ts      #            验证工具
│   │   │   ├── storage.ts       #            本地存储封装
│   │   │   └── crypto.ts        #            加密解密工具
│   │   │
│   │   └── decorators/          #        装饰器（高级用法）
│   │       ├── logger.ts        #            日志装饰器
│   │       └── debounce.ts      #            防抖装饰器
│   │
│   ├── services/                 #    🌐 服务层（数据交互）
│   │   ├── api/                 #        HTTP API服务
│   │   │   ├── index.ts         #            axios实例配置
│   │   │   ├── request.ts       #            请求封装（拦截器）
│   │   │   ├── account.ts       #            账号API
│   │   │   ├── article.ts       #            文章API
│   │   │   └── publish.ts       #            发布API
│   │   │
│   │   ├── ipc/                 #        Electron IPC服务
│   │   │   ├── index.ts         #            IPC客户端
│   │   │   ├── channel.ts       #            通道定义
│   │   │   └── bridge.ts        #            双向通信桥
│   │   │
│   │   ├── websocket/           #        WebSocket服务
│   │   │   ├── index.ts         #            WS客户端
│   │   │   └── handlers.ts      #            消息处理器
│   │   │
│   │   └── storage/             #        本地存储服务
│   │       ├── index.ts         #            统一接口
│   │       ├── db.ts            #            IndexedDB封装
│   │       └── file.ts          #            文件系统访问
│   │
│   ├── stores/                   #    📦 状态管理层（Pinia）
│   │   ├── index.ts             #        Store注册
│   │   ├── modules/             #        Store模块
│   │   │   ├── app.ts           #            应用状态
│   │   │   ├── account.ts       #            账号状态
│   │   │   ├── article.ts       #            文章状态
│   │   │   ├── publish.ts       #            发布状态
│   │   │   └── platform.ts      #            ⭐ 平台状态（扩展）
│   │   │
│   │   └── types/               #        Store类型定义
│   │       └── index.ts
│   │
│   ├── composables/              #    🪝 组合式函数（Vue3特性）
│   │   ├── index.ts             #        统一导出
│   │   ├── usePlatform.ts       #        ⭐ 平台相关hooks
│   │   ├── useAccount.ts        #        账号相关hooks
│   │   ├── useArticle.ts        #        文章相关hooks
│   │   ├── usePublish.ts        #        发布相关hooks
│   │   ├── useRequest.ts        #        请求hooks
│   │   ├── useWebSocket.ts      #        WebSocket hooks
│   │   └── useTable.ts          #        表格hooks
│   │
│   ├── router/                   #    🧭 路由配置
│   │   ├── index.ts             #        路由入口
│   │   ├── routes.ts            #        路由定义
│   │   ├── guards.ts            #        路由守卫
│   │   └── modules/             #        路由模块
│   │       ├── account.ts       #            账号路由
│   │       ├── article.ts       #            文章路由
│   │       └── publish.ts       #            发布路由
│   │
│   ├── views/                    #    📄 页面层（路由视图）
│   │   ├── layout/              #        布局页面
│   │   │   ├── MainLayout.vue   #            主布局
│   │   │   ├── BlankLayout.vue  #            空白布局
│   │   │   └── components/      #            布局组件
│   │   │       ├── Sidebar.vue  #                侧边栏
│   │   │       ├── Header.vue   #                顶部栏
│   │   │       └── Tabs.vue     #                标签页
│   │   │
│   │   ├── account/             #        账号管理
│   │   │   ├── AccountList.vue  #            账号列表
│   │   │   ├── AccountAdd.vue   #            添加账号
│   │   │   └── AccountAuth.vue  #            授权页面
│   │   │
│   │   ├── article/             #        文章管理
│   │   │   ├── ArticleList.vue  #            文章列表
│   │   │   ├── ArticleEdit.vue  #            编辑文章
│   │   │   └── ArticlePreview.vue#           预览文章
│   │   │
│   │   ├── publish/             #        批量发布
│   │   │   ├── PublishPage.vue  #            发布主页
│   │   │   ├── PublishProgress.vue#          发布进度
│   │   │   └── PublishHistory.vue#           发布记录
│   │   │
│   │   └── settings/            #        设置
│   │       ├── SettingsPage.vue #            设置页
│   │       └── AboutPage.vue    #            关于页
│   │
│   ├── components/               #    🧩 组件层
│   │   ├── business/            #        业务组件（与业务强相关）
│   │   │   ├── account/         #            账号相关
│   │   │   │   ├── AccountCard.vue       # 账号卡片
│   │   │   │   ├── AccountSelector.vue   # 账号选择器
│   │   │   │   └── PlatformIcon.vue      # ⭐ 平台图标组件
│   │   │   │
│   │   │   ├── article/         #            文章相关
│   │   │   │   ├── ArticleEditor.vue     # 富文本编辑器
│   │   │   │   ├── TagSelector.vue       # 标签选择器
│   │   │   │   └── CoverUpload.vue       # 封面上传
│   │   │   │
│   │   │   └── publish/         #            发布相关
│   │   │       ├── PublishTask.vue        # 发布任务卡片
│   │   │       ├── ProgressCard.vue      # 进度卡片
│   │   │       └── PlatformSelector.vue  # ⭐ 平台选择器
│   │   │
│   │   ├── common/              #        通用组件（可复用）
│   │   │   ├── button/          #            按钮
│   │   │   ├── table/           #            表格
│   │   │   ├── dialog/          #            弹窗
│   │   │   ├── form/            #            表单
│   │   │   └── upload/          #            上传
│   │   │
│   │   └── _shared/             #        组件共享资源
│   │       ├── mixins.ts        #            混入
│   │       └── directives.ts    #            自定义指令
│   │
│   ├── assets/                   #    🎨 资源文件
│   │   ├── images/              #        图片
│   │   │   ├── platforms/       #            ⭐ 平台logo
│   │   │   │   ├── zhihu.svg
│   │   │   │   ├── baijiahao.svg
│   │   │   │   ├── sohu.svg
│   │   │   │   ├── toutiao.svg
│   │   │   │   └── wechat.svg   #                预留
│   │   │   └── ...
│   │   ├── styles/              #        样式文件
│   │   │   ├── index.scss       #            样式入口
│   │   │   ├── variables.scss   #            SCSS变量
│   │   │   ├── mixins.scss      #            SCSS混入
│   │   │   └── themes/          #            主题配置
│   │   │       ├── light.scss
│   │   │       └── dark.scss
│   │   └── fonts/               #        字体文件
│   │
│   ├── types/                    #    📝 TypeScript类型定义
│   │   ├── index.ts             #        统一导出
│   │   ├── global.d.ts          #        全局类型声明
│   │   ├── auto-imports.d.ts    #        自动导入类型
│   │   ├── api.ts               #        API类型
│   │   ├── account.ts           #        账号类型
│   │   ├── article.ts           #        文章类型
│   │   ├── publish.ts           #        发布类型
│   │   └── platform.ts          #        ⭐ 平台类型（扩展）
│   │
│   └── locale/                   #    🌍 国际化（预留）
│       ├── index.ts             #        i18n配置
│       ├── zh-CN.ts             #        简体中文
│       └── en-US.ts             #        英文
│
├── tests/                        # 🧪 测试文件
│   ├── unit/                    #    单元测试
│   └── e2e/                     #    E2E测试
│
├── build/                        # 🔨 构建配置
│   ├── vite.config.ts           #    Vite配置
│   ├── electron.vite.config.ts  #    Electron Vite配置
│   └── plugins/                 #    构建插件
│
├── scripts/                      # 📜 脚本工具
│   ├── dev.ts                   #    开发脚本
│   └── build.ts                 #    构建脚本
│
├── package.json                  #    依赖配置
├── tsconfig.json                 #    TS配置
└── README.md                     #    前端说明
```

---

## 三、平台适配器模式（核心扩展机制）⭐

### 3.1 设计理念

**开闭原则（OCP）**：对扩展开放，对修改关闭。新增平台时，只需添加配置和适配器实现，无需修改核心代码。

### 3.2 平台配置结构

```typescript
// src/core/config/platform.ts
export interface PlatformConfig {
  // 基础信息
  id: string;                    // 平台唯一标识
  name: string;                  // 平台中文名
  code: string;                  // 平台代码
  icon: string;                  // 图标路径

  // 功能开关
  features: {
    article: boolean;            // 是否支持文章发布
    video: boolean;              // 是否支持视频发布
    image: boolean;              // 是否支持图片上传
    draft: boolean;              // 是否支持草稿
    schedule: boolean;           // 是否支持定时发布
  };

  // 认证配置
  auth: {
    type: 'qrcode' | 'password' | 'oauth';  // 登录方式
    loginUrl: string;           // 登录页URL
    checkLoginInterval: number; // 登录检测间隔(ms)
    maxWaitTime: number;        // 最大等待时间(ms)
  };

  // 发布配置
  publish: {
    entryUrl: string;           // 发布入口URL
    selectors: {                // 选择器配置
      title: string;
      content: string;
      submit: string;
    };
    waitTimes: {                // 等待时间配置
      afterLoad: number;        // 页面加载后等待
      afterFill: number;        // 填充后等待
      afterSubmit: number;      // 提交后等待
    };
  };

  // 限制配置
  limits: {
    titleLength: [number, number];  // 标题长度范围
    contentLength: [number, number];// 内容长度范围
    imageCount: number;             // 最大图片数量
  };
}

// 当前支持的平台配置
export const PLATFORMS: Record<string, PlatformConfig> = {
  zhihu: {
    id: 'zhihu',
    name: '知乎',
    code: 'ZH',
    icon: 'zhihu.svg',
    features: { article: true, video: true, image: true, draft: true, schedule: false },
    auth: { type: 'qrcode', loginUrl: 'https://www.zhihu.com/signin', checkLoginInterval: 1000, maxWaitTime: 120000 },
    publish: { /* ... */ },
    limits: { titleLength: [1, 100], contentLength: [0, 100000], imageCount: 100 }
  },
  baijiahao: {
    id: 'baijiahao',
    name: '百家号',
    code: 'BJH',
    icon: 'baijiahao.svg',
    // ...
  },
  sohu: {
    id: 'sohu',
    name: '搜狐号',
    code: 'SOHU',
    icon: 'sohu.svg',
    // ...
  },
  toutiao: {
    id: 'toutiao',
    name: '头条号',
    code: 'TT',
    icon: 'toutiao.svg',
    // ...
  }
  // 新增平台只需在这里添加配置！
};
```

### 3.3 适配器接口定义

```typescript
// src/core/platform/adapter.ts
export interface IPlatformAdapter {
  // 平台标识
  readonly platformId: string;

  // 认证相关
  startAuth(): Promise<AuthResult>;           // 开始授权
  checkAuthStatus(): Promise<boolean>;        // 检查登录状态

  // 发布相关
  startPublish(article: Article): Promise<PublishResult>;  // 开始发布
  checkPublishStatus(taskId: string): Promise<PublishStatus>; // 检查发布状态

  // 验证相关
  validateArticle(article: Article): ValidationResult; // 验证文章格式

  // 工具方法
  getAuthUrl(): string;                       // 获取授权URL
  getPublishUrl(): string;                    // 获取发布URL
}

export abstract class BasePlatformAdapter implements IPlatformAdapter {
  abstract readonly platformId: string;

  // 通用实现（可被覆盖）
  validateArticle(article: Article): ValidationResult {
    const config = getPlatformConfig(this.platformId);
    // 通用验证逻辑
  }
}
```

### 3.4 各平台适配器实现

```typescript
// src/core/platform/adapters/zhihu.ts
export class ZhihuAdapter extends BasePlatformAdapter {
  readonly platformId = 'zhihu';

  async startAuth(): Promise<AuthResult> {
    // 知乎特有的授权逻辑
  }

  async startPublish(article: Article): Promise<PublishResult> {
    // 知乎特有的发布逻辑
  }
}

// 新增平台：只需创建新适配器类，实现接口即可
// export class WechatAdapter extends BasePlatformAdapter { ... }
```

### 3.5 平台注册中心

```typescript
// src/core/platform/registry.ts
class PlatformRegistry {
  private adapters = new Map<string, IPlatformAdapter>();

  // 注册平台适配器
  register(adapter: IPlatformAdapter): void {
    this.adapters.set(adapter.platformId, adapter);
  }

  // 获取平台适配器
  get(platformId: string): IPlatformAdapter | undefined {
    return this.adapters.get(platformId);
  }

  // 获取所有已注册平台
  getAll(): IPlatformAdapter[] {
    return Array.from(this.adapters.values());
  }
}

export const platformRegistry = new PlatformRegistry();

// 自动注册所有适配器
platformRegistry.register(new ZhihuAdapter());
platformRegistry.register(new BaijiahaoAdapter());
platformRegistry.register(new SohuAdapter());
platformRegistry.register(new ToutiaoAdapter());
// 新增平台：添加一行注册代码即可！
```

---

## 四、组件层次结构

### 4.1 组件分类原则

| 层级 | 目录 | 特点 | 示例 |
|-----|------|------|------|
| **布局组件** | `views/layout/` | 页面骨架，不含业务逻辑 | Sidebar, Header, Tabs |
| **页面组件** | `views/*/` | 路由视图，组合业务组件 | AccountList, ArticleEdit |
| **业务组件** | `components/business/` | 含业务逻辑，可复用 | AccountCard, ArticleEditor |
| **通用组件** | `components/common/` | 纯UI组件，业务无关 | Button, Table, Dialog |

### 4.2 组件命名规范

```
├── 业务组件：PascalCase + 业务前缀
│   ├── account/             # 账号相关
│   │   ├── AccountCard.vue          # 账号卡片
│   │   ├── AccountSelector.vue      # 账号选择器
│   │   └── AccountAuthModal.vue     # 账号授权弹窗
│   ├── article/             # 文章相关
│   │   ├── ArticleEditor.vue        # 文章编辑器
│   │   ├── ArticleListItem.vue      # 文章列表项
│   │   └── ArticlePreview.vue       # 文章预览
│   └── publish/             # 发布相关
│       ├── PublishTaskCard.vue      # 发布任务卡片
│       ├── PublishProgress.vue      # 发布进度条
│       └── PlatformSelector.vue     # 平台选择器
│
└── 通用组件：PascalCase，无业务前缀
    ├── BaseButton.vue       # 基础按钮
    ├── BaseTable.vue        # 基础表格
    ├── BaseDialog.vue       # 基础弹窗
    └── BaseForm.vue         # 基础表单
```

---

## 五、状态管理方案

### 5.1 Store模块划分

```
stores/
├── index.ts                    # Store注册入口
└── modules/
    ├── app.ts                  # 应用全局状态
    ├── account.ts              # 账号状态
    ├── article.ts              # 文章状态
    ├── publish.ts              # 发布状态
    └── platform.ts             # ⭐ 平台状态（扩展）
```

### 5.2 平台Store示例

```typescript
// stores/modules/platform.ts
import { defineStore } from 'pinia';
import { PLATFORMS, type PlatformConfig } from '@/core/config/platform';

export const usePlatformStore = defineStore('platform', {
  state: () => ({
    // 当前激活的平台
    activePlatformIds: ['zhihu', 'baijiahao', 'sohu', 'toutiao'],

    // 平台配置缓存
    configs: PLATFORMS,

    // 平台状态映射
    platformStates: {} as Record<string, {
      enabled: boolean;        // 是否启用
      available: boolean;      // 是否可用（服务检测）
      lastCheckTime: number;   // 最后检测时间
    }>
  }),

  getters: {
    // 获取启用的平台列表
    enabledPlatforms: (state) => {
      return state.activePlatformIds
        .map(id => state.configs[id])
        .filter(Boolean);
    },

    // 根据ID获取平台配置
    getPlatformConfig: (state) => (id: string) => {
      return state.configs[id];
    },

    // 获取平台图标
    getPlatformIcon: () => (id: string) => {
      return `/src/assets/images/platforms/${id}.svg`;
    }
  },

  actions: {
    // 启用平台
    enablePlatform(platformId: string) {
      if (!this.activePlatformIds.includes(platformId)) {
        this.activePlatformIds.push(platformId);
      }
    },

    // 禁用平台
    disablePlatform(platformId: string) {
      this.activePlatformIds = this.activePlatformIds.filter(
        id => id !== platformId
      );
    },

    // 检查平台可用性
    async checkPlatformAvailable(platformId: string) {
      // 调用后端API检查平台服务状态
    }
  }
});
```

### 5.3 组合式函数封装

```typescript
// composables/usePlatform.ts
import { computed } from 'vue';
import { usePlatformStore } from '@/stores/modules/platform';

export function usePlatform() {
  const platformStore = usePlatformStore();

  // 响应式计算属性
  const enabledPlatforms = computed(() => platformStore.enabledPlatforms);
  const platformConfigs = computed(() => platformStore.configs);

  // 方法
  const getPlatformConfig = (id: string) => platformStore.getPlatformConfig(id);
  const getPlatformIcon = (id: string) => platformStore.getPlatformIcon(id);

  return {
    enabledPlatforms,
    platformConfigs,
    getPlatformConfig,
    getPlatformIcon
  };
}
```

---

## 六、API服务层设计

### 6.1 请求封装

```typescript
// services/api/request.ts
import axios from 'axios';

const request = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
  timeout: 30000,
});

// 请求拦截器
request.interceptors.request.use(
  (config) => {
    // 添加token等
    return config;
  },
  (error) => Promise.reject(error)
);

// 响应拦截器
request.interceptors.response.use(
  (response) => response.data,
  (error) => {
    // 统一错误处理
    return Promise.reject(error);
  }
);

export default request;
```

### 6.2 模块化API

```typescript
// services/api/account.ts
import request from './request';

export const accountApi = {
  // 获取账号列表
  getList: () => request.get('/api/accounts'),

  // 添加账号
  add: (data: AccountAddParams) => request.post('/api/accounts', data),

  // 删除账号
  delete: (id: number) => request.delete(`/api/accounts/${id}`),

  // 开始授权
  startAuth: (platformId: string) => request.post(`/api/accounts/auth/${platformId}`),

  // 检查授权状态
  checkAuth: (taskId: string) => request.get(`/api/accounts/auth/status/${taskId}`),
};

// services/api/publish.ts
export const publishApi = {
  // 创建发布任务
  createTask: (data: PublishTaskParams) => request.post('/api/publish/task', data),

  // 获取发布进度
  getProgress: (taskId: string) => request.get(`/api/publish/progress/${taskId}`),

  // 取消发布
  cancel: (taskId: string) => request.post(`/api/publish/cancel/${taskId}`),
};
```

---

## 七、路由设计

### 7.1 路由结构

```typescript
// router/routes.ts
export const routes = [
  {
    path: '/',
    component: () => import('@/views/layout/MainLayout.vue'),
    children: [
      {
        path: '/account',
        name: 'Account',
        component: () => import('@/views/account/AccountList.vue'),
        meta: { title: '账号管理', icon: 'User' }
      },
      {
        path: '/article',
        name: 'Article',
        component: () => import('@/views/article/ArticleList.vue'),
        meta: { title: '文章管理', icon: 'Document' }
      },
      {
        path: '/publish',
        name: 'Publish',
        component: () => import('@/views/publish/PublishPage.vue'),
        meta: { title: '批量发布', icon: 'Send' }
      },
      {
        path: '/history',
        name: 'History',
        component: () => import('@/views/publish/PublishHistory.vue'),
        meta: { title: '发布记录', icon: 'Clock' }
      }
    ]
  },
  {
    path: '/auth/:platformId',
    name: 'AccountAuth',
    component: () => import('@/views/account/AccountAuth.vue'),
    meta: { title: '账号授权', fullscreen: true }
  }
];
```

---

## 八、开发规范

### 8.1 文件命名

| 类型 | 命名规范 | 示例 |
|-----|---------|------|
| 组件文件 | PascalCase | `AccountCard.vue` |
| 工具文件 | camelCase | `format.ts` |
| 类型文件 | camelCase | `account.ts` |
| 常量文件 | camelCase | `enum.ts` |
| 样式文件 | kebab-case | `account-card.scss` |

### 8.2 代码风格

```typescript
// 组件结构顺序
<script setup lang="ts">
// 1. 导入
import { ref, computed } from 'vue';

// 2. 类型定义
interface Props { /* ... */ }

// 3. Props/Emits定义
const props = defineProps<Props>();
const emit = defineEmits<{
  (e: 'change', value: string): void;
}>();

// 4. 组合式函数
const { data } = useData();

// 5. 响应式状态
const count = ref(0);

// 6. 计算属性
const double = computed(() => count.value * 2);

// 7. 方法
const increment = () => { count.value++; };

// 8. 生命周期
onMounted(() => { /* ... */ });
</script>

<template>
  <!-- 模板内容 -->
</template>

<style scoped lang="scss">
/* 样式内容 */
</style>
```

---

## 九、扩展新平台指南

### 步骤1：添加平台配置
```typescript
// src/core/config/platform.ts
export const PLATFORMS = {
  // ...现有平台
  xinhao: {
    id: 'xinhao',
    name: '新平台',
    code: 'XH',
    icon: 'xinhao.svg',
    // ...配置项
  }
};
```

### 步骤2：实现平台适配器
```typescript
// src/core/platform/adapters/xinhao.ts
export class XinhaoAdapter extends BasePlatformAdapter {
  readonly platformId = 'xinhao';
  // 实现接口方法...
}
```

### 步骤3：注册适配器
```typescript
// src/core/platform/registry.ts
platformRegistry.register(new XinhaoAdapter());
```

### 步骤4：添加平台图标
```
src/assets/images/platforms/xinhao.svg
```

### 完成！无需修改任何核心代码！

---

## 十、构建配置

### 10.1 Vite配置

```typescript
// build/vite.config.ts
import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import { resolve } from 'path';

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, '../src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
});
```

---

## 附录：类型定义汇总

```typescript
// types/platform.ts
export type PlatformId = 'zhihu' | 'baijiahao' | 'sohu' | 'toutiao' | 'wechat';

export interface PlatformAccount {
  id: number;
  platformId: PlatformId;
  accountName: string;
  username: string;
  status: AccountStatus;
  lastAuthTime: string;
}

export interface Article {
  id?: number;
  title: string;
  content: string;
  tags: string[];
  coverImage?: string;
}

export interface PublishTask {
  id: string;
  articleId: number;
  targetAccounts: number[];
  status: PublishStatus;
}

export enum AccountStatus {
  Active = 1,
  Inactive = 0,
  Expired = -1,
}

export enum PublishStatus {
  Pending = 0,
  Publishing = 1,
  Success = 2,
  Failed = 3,
}
```

---

**文档版本**：v1.0
**更新日期**：2025-01-08
**维护者**：开发者
