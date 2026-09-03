# AutoGeo 后端 API 文档

> **AutoGeo 智能多平台文章发布助手 - 后端 API 接口文档**

---

## 基础信息

- **Base URL**: `http://127.0.0.1:8001`
- **API 文档**: `/docs` (Swagger UI)
- **备用文档**: `/redoc` (ReDoc)

---

## 目录

1. [基础接口](#基础接口)
2. [账号管理](#账号管理)
3. [文章管理](#文章管理)
4. [发布管理](#发布管理)
5. [候选人管理](#候选人管理)
6. [文件上传](#文件上传)
7. [GEO 系统](#geo-系统)
8. [知识库管理](#知识库管理)
9. [定时任务](#定时任务)
10. [数据报表](#数据报表)
11. [预警通知](#预警通知)
12. [收录检测](#收录检测)

---

## 基础接口

### GET /
健康检查

**响应**
```json
{
  "name": "AutoGeo Backend",
  "version": "2.0.0",
  "status": "running"
}
```

### GET /api/health
健康检查

**响应**
```json
{
  "status": "ok"
}
```

### GET /api/platforms
获取支持的平台列表

**响应**
```json
{
  "platforms": [
    {"id": "zhihu", "name": "知乎", "code": "ZH", "color": "#0084FF"},
    {"id": "baijiahao", "name": "百家号", "code": "BJH", "color": "#E53935"},
    {"id": "sohu", "name": "搜狐号", "code": "SOHU", "color": "#FF6B00"},
    {"id": "toutiao", "name": "头条号", "code": "TT", "color": "#333333"}
  ]
}
```

---

## 账号管理

### GET /api/accounts
获取账号列表

**查询参数**
- `platform`: 平台筛选
- `status`: 状态筛选

### POST /api/accounts
创建账号

**请求体**
```json
{
  "platform": "zhihu",
  "account_name": "我的知乎号",
  "remark": "备注"
}
```

### GET /api/accounts/{account_id}
获取账号详情

### PUT /api/accounts/{account_id}
更新账号信息

### DELETE /api/accounts/{account_id}
删除账号

### POST /api/accounts/auth/start
开始账号授权

**请求体**
```json
{
  "platform": "zhihu",
  "account_id": 123,
  "account_name": "我的知乎号"
}
```

### GET /api/accounts/auth/status/{task_id}
获取授权状态

### POST /api/accounts/auth/confirm/{task_id}
确认授权完成

### DELETE /api/accounts/auth/task/{task_id}
取消授权任务

---

## 文章管理

### GET /api/articles
获取文章列表

**查询参数**
- `page`: 页码
- `limit`: 每页数量
- `status`: 状态筛选
- `keyword`: 关键词搜索

### POST /api/articles
创建文章

**请求体**
```json
{
  "title": "文章标题",
  "content": "文章内容",
  "tags": "标签1,标签2",
  "category": "分类",
  "cover_image": "封面图URL"
}
```

### GET /api/articles/{article_id}
获取文章详情

### PUT /api/articles/{article_id}
更新文章

### DELETE /api/articles/{article_id}
删除文章

### POST /api/articles/{article_id}/publish
标记文章为已发布

---

## 发布管理

### GET /api/publish/records
获取发布记录

### POST /api/publish/create
创建发布任务

**请求体**
```json
{
  "article_ids": [1, 2],
  "account_ids": [1, 2, 3]
}
```

### GET /api/publish/progress/{task_id}
获取发布进度

### POST /api/publish/retry/{record_id}
重试发布失败的任务

### GET /api/publish/platforms
获取发布平台状态

---

## 候选人管理

### GET /api/candidates
获取候选人列表

**查询参数**
- `page`: 页码
- `limit`: 每页数量
- `status`: 状态筛选
- `is_send`: 是否已发送
- `keyword`: 关键词搜索

**响应**
```json
{
  "success": true,
  "total": 100,
  "items": [
    {
      "id": 1,
      "uid": "candidate_12345",
      "detail": {"name": "张三", "position": "工程师"},
      "attached": {"resume_url": "https://..."},
      "is_send": false,
      "article_id": null,
      "status": 1,
      "created_at": "2024-01-01T00:00:00"
    }
  ]
}
```

### GET /api/candidates/{candidate_id}
获取候选人详情

### POST /api/candidates/sync
同步候选人数据

> **注意**: 此接口通常由外部系统调用，前端也可用于手动同步

**用途**: 外部系统筛选候选人后调用此接口保存到数据库

**请求体**
```json
{
  "uid": "candidate_12345",
  "detail": {"name": "张三", "position": "工程师", "experience": "5年"},
  "attached": {"resume_url": "https://example.com/resume.pdf"},
  "is_send": false
}
```

### POST /api/candidates/{candidate_id}/send
发送文章给候选人

**请求体**
```json
{
  "article_id": 123
}
```

### PUT /api/candidates/{candidate_id}
更新候选人信息

### DELETE /api/candidates/{candidate_id}
删除候选人

### GET /api/candidates/stats/overview
获取候选人统计信息

**响应**
```json
{
  "success": true,
  "data": {
    "total": 100,
    "sent": 60,
    "pending": 40,
    "send_rate": 60.0
  }
}
```

---

## 文件上传

### POST /api/upload/image
上传单张图片（富文本编辑器专用）

**请求**: `multipart/form-data`
- `file`: 图片文件

**支持格式**: jpg, jpeg, png, gif, webp
**大小限制**: 5MB
**用途**: WangEditor 富文本编辑器图片上传

**响应**
```json
{
  "success": true,
  "message": "上传成功",
  "data": {
    "url": "/api/upload/images/20240101_abc123.png",
    "filename": "20240101_abc123.png",
    "size": 123456,
    "original_name": "原始文件名.png"
  }
}
```

### POST /api/upload/images
批量上传图片

**请求**: `multipart/form-data`
- `files`: 图片文件数组（最多10张）

### GET /api/upload/images/{filename}
获取上传的图片

### DELETE /api/upload/images/{filename}
删除上传的图片

---

## GEO 系统

### GET /api/geo/projects
获取项目列表

### POST /api/keywords/projects
创建项目

### GET /api/geo/keywords
获取关键词列表

### POST /api/keywords/distill
关键词蒸馏

### GET /api/geo/articles
获取 GEO 文章列表

### POST /api/geo/generate
生成 GEO 文章

### POST /api/geo/articles/{article_id}/check-quality
质检文章

---

## 知识库管理

### GET /api/knowledge/categories
获取分类列表

### POST /api/knowledge/categories
创建分类

### GET /api/knowledge/knowledge/search
搜索知识条目

### POST /api/knowledge/knowledge
创建知识条目

---

## 定时任务

### GET /api/scheduler/status
获取定时任务状态

### GET /api/scheduler/jobs
获取任务列表

### POST /api/scheduler/start
启动定时任务

### POST /api/scheduler/stop
停止定时任务

---

## 数据报表

### GET /api/reports/stats
获取数据总览卡片数据

**查询参数**
- `project_id` (可选): 项目ID筛选
- `days` (可选): 时间范围天数，默认7天

**响应**
```json
{
  "total_articles": 15,
  "common_articles": 5,
  "geo_articles": 10,
  "publish_success_rate": 85.5,
  "publish_success_count": 13,
  "publish_total_count": 15,
  "keyword_hit_rate": 72.3,
  "keyword_hit_count": 8,
  "keyword_check_count": 11,
  "company_hit_rate": 63.6,
  "company_hit_count": 7,
  "company_check_count": 11
}
```

### GET /api/reports/platform-comparison
AI平台对比分析

**查询参数**
- `project_id` (可选): 项目ID筛选
- `days` (可选): 时间范围天数，默认7天
- `platform` (可选): 平台筛选（DeepSeek/豆包/通义千问）

**响应**
```json
[
  {
    "platform": "DeepSeek",
    "hit_count": 8,
    "total_count": 11,
    "hit_rate": 72.7
  },
  {
    "platform": "豆包",
    "hit_count": 6,
    "total_count": 10,
    "hit_rate": 60.0
  },
  {
    "platform": "通义千问",
    "hit_count": 7,
    "total_count": 12,
    "hit_rate": 58.3
  }
]
```

### GET /api/reports/project-leaderboard
项目影响力排行榜

**查询参数**
- `days` (可选): 时间范围天数，默认7天

**响应**
```json
[
  {
    "rank": 1,
    "project_name": "SEO优化项目",
    "company_name": "示例科技公司",
    "content_volume": 25,
    "ai_mention_rate": 85.5,
    "brand_relevance": 85.5
  },
  {
    "rank": 2,
    "project_name": "品牌推广",
    "company_name": "推广公司",
    "content_volume": 18,
    "ai_mention_rate": 72.3,
    "brand_relevance": 72.3
  }
]
```

### GET /api/reports/content-analysis
高贡献内容分析

**查询参数**
- `project_id` (可选): 项目ID筛选
- `days` (可选): 时间范围天数，默认7天
- `platform` (可选): 平台筛选

**响应**
```json
[
  {
    "rank": 1,
    "title": "如何优化AI搜索引擎收录",
    "platform": "DeepSeek",
    "ai_contribution": 90.0,
    "publish_time": "2026-02-03 14:30"
  },
  {
    "rank": 2,
    "title": "GEO内容生成策略",
    "platform": "豆包",
    "ai_contribution": 90.0,
    "publish_time": "2026-02-02 10:15"
  }
]
```

---

## 预警通知

### GET /api/notifications/summary
获取通知摘要

### POST /api/notifications/check
执行预警检查

---

## 收录检测

### GET /api/index-check/records
获取检测记录

### POST /api/index-check/check
执行收录检测

---

## WebSocket

### WS /ws?client_id={client_id}
WebSocket 连接端点

用于实时推送发布进度、授权状态等。

---

## 错误码

| 状态码 | 说明 |
|--------|------|
| 200 | 成功 |
| 400 | 请求参数错误 |
| 404 | 资源不存在 |
| 500 | 服务器内部错误 |

---

## 更新日志

### v3.1.0 (2026-02-10)
- ✅ 关键词蒸馏与文章生成改为直连 DeepSeek，移除 n8n 依赖

### v3.0.0 (2026-02-06)
- ✅ 补充关键词蒸馏、问题生成、文章生成、收录分析的完整API文档
- ✅ 更新前端候选人管理API说明

### v2.9.0 (2026-02-04)
- ✅ 新增数据报表完整功能
- ✅ `/api/reports/stats` - 数据总览卡片
- ✅ `/api/reports/platform-comparison` - AI平台对比分析
- ✅ `/api/reports/project-leaderboard` - 项目影响力排行榜
- ✅ `/api/reports/content-analysis` - 高贡献内容分析
- ✅ 所有接口支持项目、时间、平台筛选

### v2.2.0 (2025-01-26)
- ✅ 更换富文本编辑器为 WangEditor 5
- ✅ 完善 `/api/upload/image` 接口文档
- ✅ 支持所见即所得编辑
- ✅ 图片上传自动集成

### v2.1.0 (2025-01-26)
- ✅ 新增候选人管理 API
- ✅ 新增文件上传 API
- ✅ 修复授权页面路径错误 (`auth_confirm.hl` → `.html`)
- ✅ 修复 Candidate 模型拼写 (`attached`)
- ✅ 所有 API 模块导入测试通过
- ✅ 所有数据库模型测试通过
- ✅ 所有路由注册测试通过
