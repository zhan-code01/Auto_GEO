# AutoGeo 前端

> Electron + Vue3 + TypeScript 桌面应用前端

## 技术栈

| 技术 | 版本 | 说明 |
|------|------|------|
| Electron | ^28.0.0 | 跨平台桌面应用框架 |
| Vue | ^3.4.0 | 渐进式前端框架 |
| TypeScript | ^5.3.0 | JavaScript 超集 |
| Vite | ^5.0.0 | 下一代前端构建工具 |
| Pinia | ^2.1.7 | Vue 官方状态管理 |
| Element Plus | ^2.5.0 | Vue 3 组件库 |

## 快速开始

### 前置要求

⚠️ **启动前端前，必须先启动后端服务！**

### 1. 安装依赖

```bash
cd fronted
npm install
```

### 2. 启动开发服务器

```bash
npm run dev
```

这会自动：
- 编译 Electron 主进程代码
- 启动 Vite 开发服务器（http://127.0.0.1:5173）
- 打开 Electron 桌面窗口

## 可用脚本

| 命令 | 说明 |
|------|------|
| `npm run dev` | 启动开发服务器 + Electron |
| `npm run build` | 构建生产版本 |
| `npm run build:renderer` | 仅构建渲染进程 |
| `npm run build:electron` | 仅构建 Electron 主进程 |
| `npm run preview` | 预览构建结果 |
| `npm run type-check` | TypeScript 类型检查 |
| `npm run lint` | ESLint 代码检查 |

## 目录结构

```
fronted/
├── electron/              # Electron 主进程代码
│   ├── main/             #   主进程入口
│   │   ├── index.ts      #     主入口
│   │   ├── backend-manager.ts  # 后端管理
│   │   ├── window-manager.ts   # 窗口管理
│   │   ├── ipc-handlers.ts     # IPC 处理器
│   │   └── tray-manager.ts     # 托盘管理
│   └── preload/          #   预加载脚本
├── src/                  # 渲染进程源码
│   ├── components/      #   Vue 组件
│   ├── views/           #   页面视图
│   ├── stores/          #   Pinia 状态管理
│   ├── services/        #   API 服务
│   └── types/           #   TypeScript 类型定义
├── scripts/             # 构建脚本
│   └── dev.js          #   开发启动脚本
├── package.json         # 依赖配置
├── vite.config.ts       # Vite 配置
└── tsconfig.json        # TypeScript 配置
```

## 端口配置

| 服务 | 地址 |
|------|------|
| Vite 开发服务器 | http://127.0.0.1:5173 |
| 后端 API（需先启动） | http://127.0.0.1:8001 |
| WebSocket | ws://127.0.0.1:8001/ws |

## 常见问题

### Q: 启动后提示 "ECONNREFUSED 127.0.0.1:8001"？

A: 后端服务没有启动。请先在另一个终端启动后端：
```bash
cd ../backend
python main.py
```

### Q: TypeScript 编译报错？

A: 运行 `npm run build:electron` 单独编译 Electron 主进程。

### Q: npm install 报错？

A: 尝试清理缓存重装：
```bash
rm -rf node_modules package-lock.json
npm cache clean --force
npm install
```

## 开发规范

- 组件命名：PascalCase（如 `AccountCard.vue`）
- 文件命名：camelCase（如 `useAccount.ts`）
- 代码风格：遵循 ESLint 配置
- 提交前请运行 `npm run lint` 检查代码

---

**维护者**: 开发者
**更新日期**: 2025-01-13
