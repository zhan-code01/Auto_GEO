# AutoGeo 全量迁移 PostgreSQL 任务书

> 本文档面向 AI 编程助手。请按本文完成项目从“本地 SQLite + 服务器 PostgreSQL 混用”到“本地、测试、生产统一 PostgreSQL”的完整改造。

## 0. 当前状态说明

当前项目还没有完全统一 PostgreSQL。

已存在的修复方向：

- 已新增或计划使用 `backend/migrations/versions/0007_reconcile_postgresql_schema.py`，用于修复历史 PostgreSQL 库缺表、缺字段。
- 已新增或计划使用 `backend/scripts/check_postgres_schema.py`，用于检查 PostgreSQL 实际 schema 是否与 ORM 一致。
- 生产入口 `backend/entrypoint.sh` 应改为只执行 `alembic upgrade head`，禁止使用 `alembic stamp head` 掩盖迁移问题。

仍需完成的核心目标：

- 本地开发默认使用 PostgreSQL。
- 测试环境使用 PostgreSQL。
- 宝塔/服务器生产使用 PostgreSQL。
- SQLite 只作为历史数据迁移来源，不再作为默认运行数据库。
- 所有表结构和字段变更都通过 Alembic 管理。

## 1. 最终任务目标

请把项目改造成如下状态：

```text
Runtime database:
  local development  -> PostgreSQL
  test/CI            -> PostgreSQL
  production/server  -> PostgreSQL

Legacy SQLite:
  only allowed for historical data migration/debug
  not allowed as default runtime database
```

最终必须满足：

- `.env.example` 默认 PostgreSQL。
- 后端没有 `DATABASE_URL` 时直接报错，不再默默创建 SQLite。
- SQLite 必须通过显式变量启用，例如 `ALLOW_LEGACY_SQLITE=true`。
- PostgreSQL schema 只由 Alembic 管理。
- PostgreSQL 启动流程不执行 `Base.metadata.create_all()` 作为正式建表手段。
- PostgreSQL 启动流程不执行 `alembic stamp head`。
- 全新 PostgreSQL 空库可以执行 `alembic upgrade head`。
- 历史 PostgreSQL 旧库可以升级到 head。
- `python -m backend.scripts.check_postgres_schema` 输出 OK。
- 宝塔部署文档包含备份、迁移、schema 检查、回滚流程。

## 2. 背景问题

用户服务器出现过如下 500：

```text
psycopg2.errors.UndefinedColumn:
column index_check_records.keyword_count does not exist
```

原因：

- 代码 ORM 已经声明了 `index_check_records.keyword_count`。
- 服务器 PostgreSQL 实际表里没有该字段。
- 本地 SQLite 通过 `fix_database.py` 可能能补字段，所以本地正常。
- 服务器 PostgreSQL 不执行 SQLite 的 `fix_database.py`，导致线上缺字段。

这不是前端问题，而是数据库 schema 漂移问题。

## 3. 代码改造任务清单

请按顺序执行以下任务。

## Task 1：配置层强制 PostgreSQL

### 需要修改

```text
.env.example
backend/config.py
README.md
SETUP.md
docs/deployment-checklist.md
docs/postgresql-migration-plan.md
宝塔部署指南.md
```

### 目标行为

`DATABASE_URL` 必须显式配置。

推荐 `.env.example`：

```env
ENVIRONMENT=development

DATABASE_URL=postgresql://autogeo:your_password@localhost:5432/autogeo
POSTGRES_DB=autogeo
POSTGRES_USER=autogeo
POSTGRES_PASSWORD=your_password

RUN_DB_MIGRATIONS=true
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=3600

# Only for migrating/debugging old SQLite databases.
ALLOW_LEGACY_SQLITE=false
```

### `backend/config.py` 要求

实现规则：

```python
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL is required. PostgreSQL is the default runtime database.")

ALLOW_LEGACY_SQLITE = os.getenv("ALLOW_LEGACY_SQLITE", "false").lower() in {"1", "true", "yes", "on"}

if DATABASE_URL.lower().startswith("sqlite") and not ALLOW_LEGACY_SQLITE:
    raise ValueError("SQLite is legacy-only. Set ALLOW_LEGACY_SQLITE=true only for migration/debug.")
```

保留 SQLite 目录相关逻辑时，必须确保它只在 SQLite 被显式允许时生效。

### 验收

- `.env.example` 不再默认 SQLite。
- 删除 `DATABASE_URL` 后启动后端会报错。
- 设置 SQLite 且未设置 `ALLOW_LEGACY_SQLITE=true` 会报错。
- 设置 PostgreSQL 时正常启动配置加载。

## Task 2：本地开发提供 PostgreSQL 服务

### 需要新增或修改

优先新增：

```text
docker-compose.local.yml
```

或：

```text
deploy/local/docker-compose.yml
deploy/local/.env.example
```

选择一种即可，优先使用项目已有风格。

### 本地 PostgreSQL compose 示例

```yaml
services:
  postgres:
    image: postgres:15-alpine
    container_name: autogeo_local_postgres
    environment:
      POSTGRES_DB: autogeo
      POSTGRES_USER: autogeo
      POSTGRES_PASSWORD: autogeo_dev_password
      TZ: Asia/Shanghai
    ports:
      - "5432:5432"
    volumes:
      - autogeo_local_postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U autogeo -d autogeo"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  autogeo_local_postgres_data:
```

### 文档中写清本地启动流程

```bash
docker compose -f docker-compose.local.yml up -d postgres

cd backend
alembic upgrade head
python -m backend.scripts.check_postgres_schema
python -m backend.main
```

### 验收

- 新开发者可以一键启动本地 PostgreSQL。
- 本地 `.env` 可以直接连接本地 PostgreSQL。
- 本地不再依赖 SQLite 作为默认运行数据库。

## Task 3：修复 Alembic 迁移链

### 目标

必须支持：

```text
全新 PostgreSQL 空库: alembic upgrade head 成功
历史 PostgreSQL 旧库: alembic upgrade head 成功
历史 stamp/head 但缺字段的库: 能通过新的 reconciliation migration 修复
```

### 需要检查

```text
backend/migrations/versions/0001_initial.py
backend/migrations/versions/0002_add_user_isolation.py
backend/migrations/versions/0003_add_user_auth_system_config.py
backend/migrations/versions/0006_add_project_members_and_task_attribution.py
backend/migrations/versions/0007_reconcile_postgresql_schema.py
```

### 已知风险

早期 migration 顺序可能有依赖问题：

- `0002_add_user_isolation.py` 依赖 `users`、`site_projects`。
- `0003_add_user_auth_system_config.py` 依赖 `users`。
- `0006_add_project_members_and_task_attribution.py` 依赖 `auto_publish_tasks`。

如果 `0001_initial.py` 没有创建这些表，空 PostgreSQL 从 base 执行到 head 会失败。

### 推荐改法

优先修补 `0001_initial.py`，让它创建后续 migration 依赖的基础表：

```text
users
site_projects
auto_publish_tasks
```

注意：

- 不要破坏已有历史库升级。
- 如果表已经存在，后续 `0007` 仍负责补齐当前 ORM 所需字段。
- 如修改历史 migration 风险太大，请新增清晰的 baseline 策略，但必须在文档中说明新库和旧库如何分别处理。

### `0007_reconcile_postgresql_schema.py` 要求

必须幂等：

- 表不存在才创建。
- 字段不存在才添加。
- 索引不存在才创建。
- 不删除生产字段。
- 不清空数据。
- PostgreSQL-only，非 PostgreSQL 应明确 skip。

必须至少补齐：

```text
index_check_records.check_phase
index_check_records.keyword_count
index_check_records.company_count
index_check_records.company_matched
index_check_records.confidence
```

### 验收

用一个全新 PostgreSQL 数据库验证：

```bash
cd backend
alembic upgrade head
python -m backend.scripts.check_postgres_schema
```

预期：

```text
OK: PostgreSQL schema matches SQLAlchemy models
```

## Task 4：后端启动逻辑 PostgreSQL 化

### 需要修改

```text
backend/main.py
backend/database/__init__.py
backend/entrypoint.sh
```

### PostgreSQL 规则

PostgreSQL 下：

- 只允许 Alembic 管理 schema。
- 容器启动时可以执行 `alembic upgrade head`。
- Alembic 失败时容器启动失败。
- 不执行 `init_db()` 作为 PostgreSQL 正式建表方案。
- 不执行 `alembic stamp head`。

### SQLite 规则

SQLite 下：

- 仅 `ALLOW_LEGACY_SQLITE=true` 时允许启动。
- `check_and_fix_database()` 仅用于 SQLite。
- SQLite 路径必须明确是 legacy/debug/migration。

### `backend/entrypoint.sh` 目标逻辑

```bash
if [ "${RUN_DB_MIGRATIONS}" = "true" ] && echo "${DATABASE_URL}" | grep -qi "postgresql"; then
  cd /app/backend
  alembic upgrade head
  cd /app
fi
```

### 禁止

```bash
alembic stamp head
python -c "from backend.database import init_db; init_db()"
```

用于 PostgreSQL 生产启动。

### 验收

搜索确认：

```bash
rg -n "stamp head|init_db\\(\\)" backend/entrypoint.sh
```

生产入口不应再出现 `stamp head` 和 PostgreSQL fallback `init_db()`。

## Task 5：完善 PostgreSQL schema 检查脚本

### 文件

```text
backend/scripts/check_postgres_schema.py
```

### 要求

脚本必须：

- 导入全部 ORM 模型。
- 从 `Base.metadata` 获取 ORM 表/字段。
- 从 PostgreSQL `information_schema` 获取真实表/字段。
- 输出缺失表。
- 输出缺失字段。
- 有差异时 exit code 非 0。
- SQLite 环境明确 SKIP，不报错。

### 命令

```bash
python -m backend.scripts.check_postgres_schema
```

### 成功输出

```text
OK: PostgreSQL schema matches SQLAlchemy models
```

### 失败输出示例

```text
Missing columns:
  - index_check_records.keyword_count
  - index_check_records.company_count
```

### 验收

- PostgreSQL 环境可用于部署验收。
- SQLite 环境输出 SKIP。
- 失败时 exit code 为 1 或 2。

## Task 6：SQLite 历史数据迁移到 PostgreSQL

### 文件

```text
backend/scripts/migrate_sqlite_to_postgres.py
```

### 目标

SQLite 不再作为运行库，只作为旧数据来源。

### 迁移流程文档必须写清

```bash
# 1. 备份 SQLite 文件
# 2. 启动 PostgreSQL
# 3. 执行 schema migration
cd backend
alembic upgrade head
python -m backend.scripts.check_postgres_schema

# 4. 执行数据迁移
python -m backend.scripts.migrate_sqlite_to_postgres \
  --sqlite /path/to/auto_geo_v3.db \
  --postgres postgresql://autogeo:password@localhost:5432/autogeo

# 5. 再次检查
python -m backend.scripts.check_postgres_schema
```

### 验收

迁移后抽查：

```sql
SELECT count(*) FROM users;
SELECT count(*) FROM projects;
SELECT count(*) FROM keywords;
SELECT count(*) FROM geo_articles;
SELECT count(*) FROM accounts;
```

自增序列必须正确，新增数据不能主键冲突。

## Task 7：测试与 CI 使用 PostgreSQL

### 需要检查或修改

```text
tests/conftest.py
pyproject.toml
docs/CI-CD-WORKFLOWS.md
```

### 最低测试链路

必须能在 PostgreSQL 上执行：

```bash
cd backend
alembic upgrade head
python -m backend.scripts.check_postgres_schema
pytest
```

如果 CI 暂时不能完全迁移，至少新增一个 PostgreSQL migration/schema check job。

### 验收

- 数据库相关测试不再只依赖 SQLite。
- migration 失败会阻止发布。
- schema check 失败会阻止发布。

## Task 8：宝塔服务器部署标准化

### 需要更新

```text
宝塔部署指南.md
docs/deployment-checklist.md
docs/postgresql-migration-plan.md
```

### 必须写入宝塔上线流程

```bash
cd /www/wwwroot/Auto_GEO-main
git pull

cd deploy/production

mkdir -p /www/backup/autogeo-postgres
docker compose --env-file .env -f docker-compose.yml exec -T postgres \
  pg_dump -U autogeo -d autogeo \
  > /www/backup/autogeo-postgres/autogeo_before_deploy_$(date +%Y%m%d_%H%M%S).sql

docker compose --env-file .env -f docker-compose.yml build

docker compose --env-file .env -f docker-compose.yml run --rm backend \
  bash -lc "cd /app/backend && alembic upgrade head"

docker compose --env-file .env -f docker-compose.yml run --rm backend \
  python -m backend.scripts.check_postgres_schema

docker compose --env-file .env -f docker-compose.yml up -d

docker compose --env-file .env -f docker-compose.yml ps
docker compose --env-file .env -f docker-compose.yml logs -f backend
```

### 必须写入回滚流程

```bash
cd /www/wwwroot/Auto_GEO-main/deploy/production

docker compose --env-file .env -f docker-compose.yml stop backend

cat /www/backup/autogeo-postgres/autogeo_before_deploy_时间.sql | \
docker compose --env-file .env -f docker-compose.yml exec -T postgres \
  psql -U autogeo -d autogeo

cd /www/wwwroot/Auto_GEO-main
git checkout <上一版commit>

cd deploy/production
docker compose --env-file .env -f docker-compose.yml build
docker compose --env-file .env -f docker-compose.yml up -d
```

### 宝塔部署禁令

文档必须明确：

- 不允许只 `git pull` 后重启容器。
- 不允许跳过数据库备份。
- 不允许跳过 `alembic upgrade head`。
- 不允许使用 `alembic stamp head` 代替 migration。

## Task 9：最终验证

请在完成代码改造后执行以下检查。

### 静态检查

```bash
rg -n "sqlite:///|auto_geo_v3.db|stamp head|create_all" .env.example backend docs README.md SETUP.md 宝塔部署指南.md
```

要求：

- `.env.example` 中不应再默认 SQLite。
- PostgreSQL 生产路径不应出现 `stamp head`。
- PostgreSQL 生产路径不应依赖 `create_all()`。

### Alembic 检查

```bash
cd backend
alembic heads
alembic history --verbose
```

要求：

```text
Only one head
```

### 新 PostgreSQL 空库检查

使用干净 PostgreSQL 数据库：

```bash
cd backend
alembic upgrade head
python -m backend.scripts.check_postgres_schema
```

要求：

```text
OK: PostgreSQL schema matches SQLAlchemy models
```

### 旧库升级检查

使用旧库备份恢复后执行：

```bash
alembic upgrade head
python -m backend.scripts.check_postgres_schema
```

要求：

```text
OK: PostgreSQL schema matches SQLAlchemy models
```

### API 检查

```bash
curl http://127.0.0.1:8001/api/health
```

要求：

- database connected。
- 后端日志没有 `UndefinedColumn`。
- 后端日志没有 `UndefinedTable`。

## 4. 禁止事项

AI 编程助手不得做以下事情：

- 不要删除生产数据。
- 不要删除 PostgreSQL volume。
- 不要用 `alembic stamp head` 代替真实迁移。
- 不要只改 ORM 模型而不写 migration。
- 不要只修 SQLite 的 `fix_database.py`。
- 不要让 `.env.example` 默认 SQLite。
- 不要在没有备份说明的情况下写生产部署步骤。

## 5. 最终交付物

完成后应交付：

- 修改后的 `.env.example`。
- 本地 PostgreSQL compose 文件。
- 修复后的 Alembic migration 链。
- 完善的 `0007_reconcile_postgresql_schema.py`。
- 完善的 `backend/scripts/check_postgres_schema.py`。
- PostgreSQL 化后的 `backend/config.py`。
- PostgreSQL 化后的 `backend/entrypoint.sh`。
- 更新后的宝塔部署文档。
- 更新后的通用部署文档。
- 一份最终验证结果说明。

## 6. 完成定义

只有同时满足以下条件，才算任务完成：

- 本地默认 PostgreSQL。
- 测试/CI 至少覆盖 PostgreSQL migration 和 schema check。
- 宝塔/生产默认 PostgreSQL。
- 新库 `alembic upgrade head` 成功。
- 旧库 `alembic upgrade head` 成功。
- `check_postgres_schema` 输出 OK。
- 服务器不再出现 `psycopg2.errors.UndefinedColumn`。
- 文档说明清楚备份、迁移、检查、回滚。

## 7. 一句话目标

把 AutoGeo 的数据库生命周期统一为：

```text
ORM model change
→ Alembic migration
→ local PostgreSQL validation
→ CI/test PostgreSQL validation
→ production backup
→ production alembic upgrade head
→ schema check
→ service start
```

不要再出现“本地 SQLite 正常，服务器 PostgreSQL 500”的情况。
