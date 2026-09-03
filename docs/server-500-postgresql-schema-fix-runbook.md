# AutoGeo PostgreSQL Schema 修复任务说明

> 本文档写给 AI 编程助手和后续开发者使用。目标不是只解释问题，而是让接手者可以按本文完成代码修复、数据库迁移、宝塔服务器部署维护和验收。

## 1. 任务目标

修复 AutoGeo 从 SQLite 迁移到 PostgreSQL 后，部署到服务器出现大量 500 的问题。

核心目标：

- PostgreSQL 生产库的表和字段必须与 `backend/database/models.py` 中的 ORM 模型一致。
- 生产环境不能继续依赖 `Base.metadata.create_all()` 隐式建表或补表。
- 生产环境不能用 `alembic stamp head` 掩盖没有真正执行的迁移。
- 宝塔服务器部署时必须有明确的数据库备份、迁移、字段检查、回滚流程。
- 本地 SQLite 兼容逻辑可以保留，但不能影响 PostgreSQL 生产 schema 管理。

## 2. 已确认的问题

用户提供的服务器报错中出现：

```text
psycopg2.errors.UndefinedColumn:
column index_check_records.keyword_count does not exist
```

触发接口：

```text
/app/backend/api/reports.py
get_summary_stats()
idx_total = idx_query.count()
```

说明：

- 后端 ORM 查询了 `IndexCheckRecord.keyword_count`。
- 生产 PostgreSQL 的 `index_check_records` 表里没有这个字段。
- SQLAlchemy 查询 ORM 实体时会选择模型中声明的列，数据库缺列就会抛 `UndefinedColumn`。
- 这是数据库 schema 漂移，不是前端问题。

## 3. 当前代码中的风险点

### 3.1 PostgreSQL 启动逻辑错误

文件：

```text
backend/entrypoint.sh
```

当前 PostgreSQL 模式下存在类似逻辑：

```bash
python -c "from backend.database import init_db; init_db()"
alembic stamp head
```

问题：

- `init_db()` 内部调用 `Base.metadata.create_all()`。
- `create_all()` 只创建不存在的表，不会给已存在表补缺失字段。
- `alembic stamp head` 只改 Alembic 版本号，不执行 `ALTER TABLE`。
- 结果是 `alembic_version` 看起来最新，但真实表结构可能仍然缺字段。

### 3.2 Alembic 迁移链不完整

目录：

```text
backend/migrations/versions/
```

风险：

- `0001_initial.py` 没有创建当前 ORM 的全部表。
- 后续迁移假设某些表已经存在，例如 `users`、`site_projects`。
- `index_check_records` 的增强字段只在 SQLite 专用 `fix_database.py` 中补过，没有进入 PostgreSQL Alembic migration。

### 3.3 SQLite 和 PostgreSQL schema 管理混用

相关文件：

```text
backend/main.py
backend/database/__init__.py
backend/scripts/fix_database.py
```

现状：

- 本地 SQLite：允许 `init_db()` + `fix_database.py` 自动补历史字段。
- PostgreSQL：应该只由 Alembic 管理。
- 当前生产入口把两者混在一起，导致 schema 管理不可控。

## 4. AI 编程助手需要完成的代码任务

### 任务 A：新增 PostgreSQL schema reconciliation migration

新增文件，版本号按当前最新版本之后顺延：

```text
backend/migrations/versions/0007_reconcile_postgresql_schema.py
```

如果仓库中已经出现更新的 revision，请使用下一个可用编号，并正确设置：

```python
down_revision = "0006_add_project_members_and_task_attribution"
```

如果当前最新 revision 已变化，以实际 Alembic head 为准。

#### A.1 migration 必须幂等

该 migration 要能在以下场景安全执行：

- 空 PostgreSQL 库。
- 已经由 `create_all()` 创建过部分表的库。
- 已经被 `alembic stamp head` 标记过但真实缺字段的库。
- 已有业务数据的生产库。

要求：

- 字段不存在才添加。
- 表不存在才创建。
- 索引不存在才创建。
- 外键不存在才创建。
- 不删除现有字段。
- 不清空数据。
- 不做破坏性重建表。

#### A.2 至少修复当前已知缺失字段

必须确保 `index_check_records` 存在这些字段：

```text
check_phase varchar(20) DEFAULT 'ongoing'
keyword_count integer
company_count integer
company_matched varchar(200)
confidence double precision
```

建议索引：

```text
index_check_records(check_phase)
index_check_records(check_time)
index_check_records(keyword_id)
```

#### A.3 对齐 ORM 中的所有表

以 `backend/database/models.py` 为准，至少检查这些表是否存在：

```text
accounts
scheduled_tasks
clients
publish_records
projects
keywords
question_variants
index_check_records
geo_articles
knowledge_categories
knowledge_items
users
system_configs
reference_articles
site_projects
auto_publish_tasks
auto_publish_records
account_groups
account_operation_logs
feishu_user_bindings
feishu_events
keyword_usage_records
project_members
conversation_sessions
conversation_messages
user_agent_preferences
feishu_binding_codes
```

AI 编程助手需要逐表对比：

- ORM 字段。
- 现有 Alembic migration 字段。
- SQLite `fix_database.py` 补字段逻辑。

然后把 PostgreSQL 缺失的表和字段补进 `0007`。

### 任务 B：修改 PostgreSQL 启动迁移逻辑

修改文件：

```text
backend/entrypoint.sh
```

目标：

- PostgreSQL 生产环境默认执行 `alembic upgrade head`。
- 不要对已有 PostgreSQL 库执行 `alembic stamp head`。
- `stamp head` 只能用于明确确认真实 schema 已经等于 Alembic head 的空库初始化场景。

推荐逻辑：

```bash
if [ "${RUN_DB_MIGRATIONS}" = "true" ] && echo "${DATABASE_URL}" | grep -qi "postgresql"; then
  cd /app/backend
  alembic upgrade head
  cd /app
fi
```

如果担心已有生产库曾经被错误 `stamp head`，需要配合任务 A 的 reconciliation migration。因为如果数据库已经显示 head，普通 `upgrade head` 不会再执行旧 migration，所以 `0007` 必须成为新的 head。

### 任务 C：保留 SQLite 本地兼容逻辑，但限制适用范围

检查文件：

```text
backend/main.py
backend/scripts/fix_database.py
```

要求：

- SQLite 模式可以继续运行 `check_and_fix_database()`。
- PostgreSQL 模式必须跳过 `fix_database.py`。
- PostgreSQL 的 schema 一律通过 Alembic 迁移维护。

如果现有代码已经满足，可不改，但需要在最终说明中确认。

### 任务 D：增加 schema 检查脚本

建议新增：

```text
backend/scripts/check_postgres_schema.py
```

用途：

- 连接当前 `DATABASE_URL`。
- 读取 SQLAlchemy `Base.metadata` 中的表和字段。
- 读取 PostgreSQL `information_schema` 中的表和字段。
- 输出缺失表、缺失字段。
- 返回非 0 exit code 表示 schema 不一致。

最低验收：

```bash
python -m backend.scripts.check_postgres_schema
```

输出示例：

```text
OK: PostgreSQL schema matches SQLAlchemy models
```

或：

```text
Missing columns:
- index_check_records.keyword_count
- index_check_records.company_count
```

### 任务 E：更新部署文档

需要同步更新或引用本文：

```text
docs/deployment-checklist.md
docs/postgresql-migration-plan.md
宝塔部署指南.md
```

重点写清楚：

- 宝塔服务器部署 PostgreSQL 时必须先备份。
- 发版后必须执行 Alembic migration。
- 不允许只重启容器而不迁移数据库。
- 如果有表字段变更，必须跟随代码一起上线。

## 5. 宝塔服务器数据库维护要求

是的，既然代码改动了数据库结构，部署到宝塔服务器时必须维护生产数据库的表和字段。否则本地能跑，服务器仍然会因为缺表或缺列报 500。

### 5.1 每次上线前必须备份

在宝塔终端进入部署目录：

```bash
cd /www/wwwroot/Auto_GEO-main/deploy/production
```

备份 PostgreSQL：

```bash
mkdir -p /www/backup/autogeo-postgres
docker compose --env-file .env -f docker-compose.yml exec -T postgres \
  pg_dump -U autogeo -d autogeo \
  > /www/backup/autogeo-postgres/autogeo_before_deploy_$(date +%Y%m%d_%H%M%S).sql
```

如果 `.env` 中不是默认值，需要替换：

- `POSTGRES_USER`
- `POSTGRES_DB`

### 5.2 每次上线必须执行迁移

```bash
docker compose --env-file .env -f docker-compose.yml run --rm backend \
  bash -lc "cd /app/backend && alembic upgrade head"
```

然后重启：

```bash
docker compose --env-file .env -f docker-compose.yml up -d
```

### 5.3 每次上线后必须检查字段

检查 Alembic 版本：

```bash
docker compose --env-file .env -f docker-compose.yml exec postgres \
  psql -U autogeo -d autogeo -c "SELECT * FROM alembic_version;"
```

检查本次已知字段：

```bash
docker compose --env-file .env -f docker-compose.yml exec postgres \
  psql -U autogeo -d autogeo -c "
SELECT column_name
FROM information_schema.columns
WHERE table_schema='public'
  AND table_name='index_check_records'
  AND column_name IN (
    'check_phase',
    'keyword_count',
    'company_count',
    'company_matched',
    'confidence'
  )
ORDER BY column_name;
"
```

预期返回 5 行：

```text
check_phase
company_count
company_matched
confidence
keyword_count
```

### 5.4 宝塔上线标准流程

```bash
cd /www/wwwroot/Auto_GEO-main

# 1. 拉代码
git pull

# 2. 进入生产 compose 目录
cd deploy/production

# 3. 备份数据库
mkdir -p /www/backup/autogeo-postgres
docker compose --env-file .env -f docker-compose.yml exec -T postgres \
  pg_dump -U autogeo -d autogeo \
  > /www/backup/autogeo-postgres/autogeo_before_deploy_$(date +%Y%m%d_%H%M%S).sql

# 4. 构建镜像
docker compose --env-file .env -f docker-compose.yml build

# 5. 执行数据库迁移
docker compose --env-file .env -f docker-compose.yml run --rm backend \
  bash -lc "cd /app/backend && alembic upgrade head"

# 6. 启动服务
docker compose --env-file .env -f docker-compose.yml up -d

# 7. 查看状态
docker compose --env-file .env -f docker-compose.yml ps

# 8. 查看后端日志
docker compose --env-file .env -f docker-compose.yml logs -f backend
```

### 5.5 宝塔回滚流程

如果迁移后出现严重异常：

```bash
cd /www/wwwroot/Auto_GEO-main/deploy/production

# 1. 停后端，避免继续写入
docker compose --env-file .env -f docker-compose.yml stop backend

# 2. 恢复备份
cat /www/backup/autogeo-postgres/autogeo_before_deploy_时间.sql | \
docker compose --env-file .env -f docker-compose.yml exec -T postgres \
  psql -U autogeo -d autogeo

# 3. 回到上一版代码
git log --oneline -5
git checkout <上一版commit>

# 4. 重建并启动
docker compose --env-file .env -f docker-compose.yml build
docker compose --env-file .env -f docker-compose.yml up -d
```

注意：如果线上有新写入数据，恢复旧备份会覆盖这些数据。生产回滚前必须确认影响范围。

## 6. 当前 500 的临时止血 SQL

如果现在服务器已经大量 500，可以先执行以下 SQL 止血。

必须先备份，再执行：

```bash
docker compose --env-file .env -f docker-compose.yml exec postgres \
  psql -U autogeo -d autogeo -c "
ALTER TABLE index_check_records
  ADD COLUMN IF NOT EXISTS check_phase varchar(20) DEFAULT 'ongoing',
  ADD COLUMN IF NOT EXISTS keyword_count integer,
  ADD COLUMN IF NOT EXISTS company_count integer,
  ADD COLUMN IF NOT EXISTS company_matched varchar(200),
  ADD COLUMN IF NOT EXISTS confidence double precision;

CREATE INDEX IF NOT EXISTS ix_index_check_records_check_phase
  ON index_check_records (check_phase);
"
```

然后：

```bash
docker compose --env-file .env -f docker-compose.yml restart backend
```

这只是止血，不是最终根治。最终仍需完成 Alembic migration。

## 7. 验收标准

代码修复完成后，AI 编程助手必须验证：

- 新增 Alembic migration 存在，并且 revision 链正确。
- `backend/entrypoint.sh` PostgreSQL 模式不再默认 `init_db()` + `stamp head`。
- PostgreSQL 模式执行 `alembic upgrade head`。
- SQLite 模式仍可保留历史 `fix_database.py` 兼容逻辑。
- `index_check_records` 包含 5 个增强字段。
- `/api/health` 正常。
- 仪表盘和报表接口不再出现 `UndefinedColumn`。
- 后端日志没有 `UndefinedTable`。
- 宝塔部署文档中包含备份、迁移、字段检查、回滚流程。

建议测试命令：

```bash
cd backend
alembic history
alembic upgrade head
```

如果可以连接测试 PostgreSQL：

```bash
python -m backend.scripts.check_postgres_schema
```

## 8. 禁止事项

- 不要在生产环境直接删 PostgreSQL volume，除非用户明确确认数据可以丢弃。
- 不要用 `alembic stamp head` 代替迁移。
- 不要只修改 ORM 模型而不写 Alembic migration。
- 不要只修 SQLite 的 `fix_database.py`，PostgreSQL 不会执行它。
- 不要在没有备份的情况下执行生产数据库结构变更。

## 9. 给接手 AI 的最短执行摘要

请完成以下工作：

1. 新增一个 Alembic migration，幂等补齐 PostgreSQL 当前 ORM 所需表和字段，优先修复 `index_check_records` 的 5 个缺失字段。
2. 修改 `backend/entrypoint.sh`，PostgreSQL 下执行 `alembic upgrade head`，不要再对已有库 `stamp head`。
3. 新增 PostgreSQL schema 检查脚本，对比 ORM 与 `information_schema`。
4. 更新宝塔部署文档，加入备份、迁移、字段检查、回滚流程。
5. 验证服务器不再出现 `psycopg2.errors.UndefinedColumn`。
