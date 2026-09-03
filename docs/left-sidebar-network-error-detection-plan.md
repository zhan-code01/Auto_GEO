# 左侧页面点击后大量 Network Error 的问题判断与检测方案

## 1. 现象

在前端左侧菜单切换页面时，页面连续弹出多个 `Network Error`。

浏览器 Network 面板里可以看到：

- `OPTIONS` 预检请求返回 `200`
- 真正的 `XHR` 请求返回 `500`
- 失败接口集中在：
  - `/api/reports/overview`
  - `/api/reports/article-stats`
  - `/api/accounts?limit=1`
  - `/api/auto-publish/tasks?limit=1`
  - `/api/reports/stats?days=1`
  - `/api/conversation/sessions?limit=50`
  - `/api/knowledge/categories`

因此，这个问题不是浏览器跨域预检失败。预检已经通过，失败发生在后端业务接口执行阶段。

## 2. 问题本质

当前截图里的 `Network Error` 是前端统一错误提示，不是根因。

根因应按后端 `500 Internal Server Error` 排查。结合仓库现有代码和文档，最可能的问题是：

**PostgreSQL 实际表结构与 SQLAlchemy ORM 模型不一致，接口查询字段或表时触发数据库异常。**

仓库中已有一份相关说明：

```text
docs/server-500-postgresql-schema-fix-runbook.md
```

里面已经记录过类似错误：

```text
psycopg2.errors.UndefinedColumn:
column index_check_records.keyword_count does not exist
```

这说明后端 ORM 已经声明了 `IndexCheckRecord.keyword_count` 等字段，但生产 PostgreSQL 的 `index_check_records` 表没有这些列。

当报表、仪表盘、文章统计、会话、知识库等页面加载时，前端会并发请求多个接口；只要这些接口查询到缺失字段或缺失表，就会全部返回 500，于是前端连续弹出多条 `Network Error`。

## 3. 为什么每个左侧页面都会报错

左侧页面切换时，页面组件通常会同时加载多个初始化接口：

- 概览数据
- 文章统计
- 账号数量
- 自动发布任务数量
- 会话历史
- 知识库分类

这些接口大多依赖同一个后端服务和同一个 PostgreSQL schema。

如果数据库 schema 有系统性漂移，例如某些 Alembic migration 没有真正执行，或者曾经使用过 `alembic stamp head` 只标记版本但没有实际 `ALTER TABLE`，那么多个接口会同时失败。

所以表现为：不是某一个页面坏了，而是“左侧菜单一切换就刷一堆错”。

## 4. 直接修复方向

优先修复数据库迁移和 schema 一致性，不建议只改前端。

当前仓库里已经具备关键修复组件：

```text
backend/migrations/versions/0007_reconcile_postgresql_schema.py
backend/scripts/check_postgres_schema.py
backend/entrypoint.sh
```

修复目标：

- PostgreSQL 启动/部署时执行 `alembic upgrade head`
- 不再用 `alembic stamp head` 掩盖未执行的迁移
- 确保 PostgreSQL 表和字段与 `backend/database/models.py` 对齐
- 用 `backend/scripts/check_postgres_schema.py` 做上线后验收

## 5. 检测方案

### 5.1 前端确认

打开浏览器 DevTools，进入 Network 面板：

1. 勾选 `Preserve log`
2. 点击左侧任意模块
3. 找到红色 `500` 的 XHR 请求
4. 点开 Response 或 Preview

重点判断：

- 如果 `OPTIONS` 是 `200`，则不是 CORS 预检问题
- 如果 XHR 是 `500`，继续查后端日志
- 如果响应里出现 `UndefinedColumn`、`UndefinedTable`、`relation does not exist`，基本就是数据库 schema 问题

### 5.2 后端日志确认

本地或服务器查看后端日志。

Docker 部署常用命令：

```bash
docker compose --env-file .env -f docker-compose.yml logs -f backend
```

重点搜索：

```text
UndefinedColumn
UndefinedTable
relation does not exist
column ... does not exist
psycopg2.errors
sqlalchemy.exc.ProgrammingError
```

如果看到类似：

```text
column index_check_records.keyword_count does not exist
```

则可以确认是 PostgreSQL 表字段缺失。

### 5.3 健康检查

请求后端健康检查：

```bash
curl http://127.0.0.1:8011/api/health
```

重点看：

- `services.database.status` 是否为 `connected`
- `services.database.alembic_revision` 是否存在
- 是否返回 database error

注意：`/api/health` 正常只代表数据库能连通，不代表表字段完全一致，所以还必须执行 schema 检查。

### 5.4 Alembic 版本检查

进入后端环境后执行：

```bash
cd /app/backend
alembic current
alembic heads
alembic history
```

期望：

- `current` 与 `heads` 一致
- 当前版本包含最新的 schema reconciliation migration
- 不应只依赖 `stamp head`

### 5.5 PostgreSQL 字段检查

进入 PostgreSQL 执行：

```sql
SELECT column_name
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'index_check_records'
  AND column_name IN (
    'check_phase',
    'keyword_count',
    'company_count',
    'company_matched',
    'confidence'
  )
ORDER BY column_name;
```

期望返回 5 个字段：

```text
check_phase
company_count
company_matched
confidence
keyword_count
```

如果少任何一个字段，报表类接口都可能 500。

### 5.6 ORM 与 PostgreSQL 全量对齐检查

执行仓库已有脚本：

```bash
python -m backend.scripts.check_postgres_schema
```

期望输出：

```text
OK: PostgreSQL schema matches SQLAlchemy models
```

如果输出：

```text
Missing tables:
Missing columns:
```

则按缺失项继续补 migration 或执行现有 migration。

## 6. 修复步骤

### 6.1 先备份数据库

生产环境必须先备份：

```bash
docker compose --env-file .env -f docker-compose.yml exec -T postgres \
  pg_dump -U autogeo -d autogeo \
  > autogeo_before_schema_fix_$(date +%Y%m%d_%H%M%S).sql
```

### 6.2 执行 Alembic 迁移

```bash
docker compose --env-file .env -f docker-compose.yml run --rm backend \
  bash -lc "cd /app/backend && alembic upgrade head"
```

### 6.3 运行 schema 检查

```bash
docker compose --env-file .env -f docker-compose.yml run --rm backend \
  bash -lc "python -m backend.scripts.check_postgres_schema"
```

### 6.4 重启后端

```bash
docker compose --env-file .env -f docker-compose.yml restart backend
```

### 6.5 验证接口

逐个请求截图中失败的接口：

```bash
curl -i http://127.0.0.1:8011/api/reports/overview
curl -i http://127.0.0.1:8011/api/reports/article-stats
curl -i "http://127.0.0.1:8011/api/accounts?limit=1"
curl -i "http://127.0.0.1:8011/api/auto-publish/tasks?limit=1"
curl -i "http://127.0.0.1:8011/api/reports/stats?days=1"
curl -i "http://127.0.0.1:8011/api/conversation/sessions?limit=50"
curl -i "http://127.0.0.1:8011/api/knowledge/categories"
```

注意：这些接口可能需要 JWT。若返回 `401`，说明认证链路正常；若返回 `500`，继续看后端日志。

## 7. 临时止血 SQL

如果线上已经大量 500，并且日志明确是 `index_check_records` 缺字段，可以先执行临时止血 SQL。

执行前必须备份数据库。

```sql
ALTER TABLE index_check_records
  ADD COLUMN IF NOT EXISTS check_phase varchar(20) DEFAULT 'ongoing',
  ADD COLUMN IF NOT EXISTS keyword_count integer,
  ADD COLUMN IF NOT EXISTS company_count integer,
  ADD COLUMN IF NOT EXISTS company_matched varchar(200),
  ADD COLUMN IF NOT EXISTS confidence double precision;

CREATE INDEX IF NOT EXISTS ix_index_check_records_check_phase
  ON index_check_records (check_phase);
```

这只是止血，不是最终方案。最终仍要执行 Alembic migration，并确保 `check_postgres_schema.py` 通过。

## 8. 前端侧优化建议

前端不应该把所有后端 500 都展示成 `Network Error`，否则排障信息不够明确。

建议优化 `frontend/src/services/api/index.ts`：

- 500 时显示后端返回的 `detail` 或 `message`
- 对同一时间窗口内的重复错误做合并提示
- 对 `ERR_NETWORK` 和 `HTTP 500` 分开显示

但这只是体验优化，不能替代后端 schema 修复。

## 9. 最终验收标准

修复完成后应满足：

- 浏览器 Network 面板中上述接口不再返回 500
- 左侧菜单切换不再连续弹出 `Network Error`
- 后端日志没有 `UndefinedColumn`、`UndefinedTable`
- `alembic current` 等于 `alembic heads`
- `python -m backend.scripts.check_postgres_schema` 输出 OK
- `/api/health` 中 database 为 connected

## 10. 一句话结论

这批报错的核心不是前端页面点击逻辑坏了，而是页面点击后触发的多个后端接口返回了 500。结合现有代码和历史文档，优先按 PostgreSQL schema 未迁移或字段缺失处理：备份数据库，执行 `alembic upgrade head`，跑 `check_postgres_schema.py`，再逐个验证失败接口。
