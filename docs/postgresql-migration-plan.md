# AutoGeo SQLite 到 PostgreSQL 迁移方案

> **2026-06-12 更新**：项目目标已经升级为“本地、测试、生产统一使用 PostgreSQL”。
> SQLite 仅作为历史数据迁移/调试旧库来源，不再作为默认运行数据库。
> 当前可执行任务书见：
>
> - `docs/postgresql-unified-migration-optimization-plan.md`
> - `docs/server-500-postgresql-schema-fix-runbook.md`
>
> 本文保留大量历史迁移背景和旧 SQLite 迁移示例；执行上线时请以“PostgreSQL 统一迁移任务书”和宝塔部署指南中的最新命令为准。

> 适用场景：将当前 AutoGeo 的 SQLite 单文件数据库部署形态，升级为 PostgreSQL 生产数据库形态。  
> 目标环境：宝塔服务器 + Docker Compose 部署。  
> 编写日期：2026-06-11。  
> 建议优先级：正式线上、多用户、长期运营前完成。

---

## 1. 结论先行

当前项目不是只能使用 SQLite。代码里已经有 PostgreSQL 支持基础：

- 后端使用 SQLAlchemy ORM，业务代码大多不直接依赖 SQLite。
- `backend/config.py` 已支持通过 `DATABASE_URL` 切换数据库连接。
- `backend/database/__init__.py` 已区分 SQLite 和 PostgreSQL，并为 PostgreSQL 配置连接池。
- `backend/requirements.txt` 已包含 `psycopg2-binary` 和 `alembic`。
- `backend/migrations/versions/` 已存在 Alembic 迁移脚本。
- `deploy/backend/docker-compose.yml` 已经有一条 PostgreSQL 连接路线。

但当前宝塔生产部署文件 `deploy/production/docker-compose.yml` 默认仍是 SQLite：

```yaml
DATABASE_URL: ${DATABASE_URL:-sqlite:////app/database/auto_geo_v3.db}
```

因此迁移不是从零重写，而是把已有 PostgreSQL 能力真正接入生产部署。整体改动量为中等偏小，主要改动集中在：

1. 宝塔服务器数据库服务。
2. Docker Compose 部署配置。
3. 后端启动流程。
4. Alembic 迁移执行。
5. 旧 SQLite 数据导入 PostgreSQL。
6. 部署文档、备份文档、验收流程。

业务模块如文章、账号、项目、发布、知识库等，大概率不需要大面积重写。

需要特别注意：当前 `models.py` 中的表数量已经多于早期 Alembic 迁移脚本覆盖的范围。迁移前必须先做一次 schema 差异审计，确认 Alembic 能创建当前代码需要的全部表和列。否则 PostgreSQL 空库启动可能“看起来连上了”，但部分新功能会在运行时因为缺表或缺列报错。

---

## 2. 为什么要从 SQLite 迁移到 PostgreSQL

### 2.1 SQLite 适合什么

SQLite 是文件型数据库，适合：

- 本地开发。
- 单人测试。
- 低并发演示环境。
- 快速部署验证功能。
- 数据量较小、写入频率不高的场景。

它的优点是简单，不需要额外安装数据库服务，一个 `.db` 文件就能运行。

### 2.2 SQLite 不适合什么

正式线上环境里，SQLite 的风险主要在：

- 并发写入能力弱，容易出现 `database is locked`。
- 不适合多个后端实例共享访问。
- 文件数据库备份、恢复、权限控制不够规范。
- 不利于后续做监控、慢查询分析、连接池管理。
- 容器部署时容易因为挂载路径、卷迁移、文件权限导致数据丢失或不可写。
- 数据增长后，维护和扩展能力弱。

AutoGeo 有账号管理、文章生成、发布任务、客户资料、知识库、飞书绑定、自动发布记录等长期数据，一旦进入正式使用，数据库应当走标准服务型数据库。

### 2.3 为什么推荐 PostgreSQL 而不是 MySQL

当前项目里已经明显按 PostgreSQL 方向做过适配：

- `get_database_type()` 只识别 `postgresql`，不识别 `mysql`。
- `backend/database/__init__.py` 里只针对 SQLite 和 PostgreSQL 分支处理。
- 迁移脚本中有多处 PostgreSQL dialect 适配。
- 依赖里已有 `psycopg2-binary`。
- 没有看到 MySQL 驱动如 `pymysql` 或 `mysqlclient`。

所以建议：

- 正式迁移目标：PostgreSQL。
- 暂不建议迁移 MySQL，除非另开一轮数据库兼容改造。

---

## 3. 当前项目数据库现状

### 3.0 Schema 差异已修复（2026-06-12）

> 2026-06-12 已新增 Alembic migration `0007_reconcile_postgresql_schema.py`，
> 幂等补齐了 ORM 模型与 PostgreSQL 之间的全部表和字段差异。
> 包括 `index_check_records` 的 5 个增强字段、`conversation_sessions/messages`、
> `user_agent_preferences` 等之前未被 Alembic 覆盖的表。
>
> 同时修改了 `entrypoint.sh`，PostgreSQL 模式默认执行 `alembic upgrade head`
> 而不是 `init_db() + stamp head`。
>
> 新增了 `backend/scripts/check_postgres_schema.py` 用于部署验收。
>
> 详见 `docs/server-500-postgresql-schema-fix-runbook.md`。

### 3.1 当前默认数据库

本地和 `deploy/production/` 生产部署默认 SQLite：

```env
DATABASE_URL=sqlite:////app/database/auto_geo_v3.db
```

容器里 SQLite 文件存放在：

```text
/app/database/auto_geo_v3.db
```

对应 Docker volume：

```text
autogeo_backend_database
```

### 3.2 当前已具备的 PostgreSQL 基础

项目中已有 PostgreSQL 相关配置：

```env
DATABASE_URL=postgresql://user:password@host:5432/autogeo
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=3600
```

后端数据库初始化逻辑已经按 `DATABASE_URL` 判断：

- 包含 `postgresql`：按 PostgreSQL 处理。
- 其他情况：按 SQLite 处理。

### 3.3 当前主要隐患

目前有一个重要问题：`backend/main.py` 启动时无条件执行：

```python
check_and_fix_database()
```

但 `backend/scripts/fix_database.py` 是 SQLite 专用脚本，它直接使用：

```python
import sqlite3
```

并固定检查：

```text
backend/database/auto_geo_v3.db
```

如果生产环境切到 PostgreSQL，这个脚本不应该继续运行。正确做法应该是：

- SQLite 模式：继续执行 `check_and_fix_database()`，用于兼容历史本地库。
- PostgreSQL 模式：不执行 `check_and_fix_database()`，改由 Alembic 管理 schema。

### 3.4 Alembic 迁移可能落后于当前 models

复查当前仓库时，`backend/database/models.py` 中已包含这些较新的表：

```text
conversation_sessions
conversation_messages
user_agent_preferences
```

但现有 `backend/migrations/versions/0001` 到 `0006` 的迁移脚本中没有明显覆盖这些表。也就是说，迁移 PostgreSQL 前不能只假设 `alembic upgrade head` 一定完整。

迁移前必须做一次模型与迁移脚本对比：

```bash
cd backend
alembic upgrade head
```

然后在 PostgreSQL 中检查是否存在当前 `models.py` 的全部表：

```bash
docker compose --env-file .env -f docker-compose.yml exec postgres \
  psql -U autogeo -d autogeo -c "\dt"
```

如果发现缺表或缺列，需要先新增 Alembic migration，再做数据迁移。不要依赖 `Base.metadata.create_all()` 在生产环境偷偷补表，因为这样会让数据库结构脱离 migration 管理。

---

## 4. 迁移目标架构

### 4.1 推荐部署形态

```text
宝塔 Nginx
   |
   v
frontend 容器 :80
   |
   v
backend 容器 :8001
   |
   v
postgres 容器 :5432
```

服务建议：

```text
autogeo_frontend
autogeo_backend
autogeo_postgres
```

Docker volume 建议：

```text
autogeo_postgres_data      # PostgreSQL 数据
autogeo_backend_cookies    # 浏览器登录态
autogeo_backend_logs       # 后端日志
autogeo_backend_uploads    # 上传文件
autogeo_backend_sites      # 站点生成文件
```

### 4.2 是否复用 n8n PostgreSQL

项目里已有 `n8n_postgres`，并且 `deploy/backend/docker-compose.yml` 默认连接：

```env
postgresql://n8n:...@n8n_postgres:5432/autogeo
```

可以复用，但生产上更建议独立一个 `autogeo_postgres`。原因：

- AutoGeo 和 n8n 生命周期不同。
- 备份和恢复边界更清晰。
- 避免 n8n 升级或故障影响 AutoGeo。
- 权限最小化，不共用数据库用户。

建议：

- 测试阶段可以复用 `n8n_postgres`。
- 正式生产建议独立 PostgreSQL 容器。

---

## 5. 改动范围总览

| 环节 | 是否需要改 | 改动量 | 说明 |
|---|---:|---:|---|
| 宝塔服务器 | 是 | 中 | 增加 PostgreSQL 容器或 PostgreSQL 服务 |
| Docker Compose | 是 | 中 | 增加 postgres 服务，修改 `DATABASE_URL` |
| `.env` | 是 | 小 | 增加 PostgreSQL 用户、密码、库名 |
| 后端启动流程 | 是 | 小 | PostgreSQL 模式跳过 SQLite 修复脚本，执行 Alembic |
| 业务 API | 大概率否 | 小 | SQLAlchemy 屏蔽了大部分差异 |
| SQLAlchemy models | 需要检查 | 小到中 | 检查 JSON、Boolean、DateTime、默认值、索引 |
| Alembic 迁移 | 是 | 中 | 验证 migrations 能完整建表 |
| 数据迁移脚本 | 是 | 中 | 从 SQLite 导出并导入 PostgreSQL |
| 备份恢复脚本 | 是 | 中 | 从复制 `.db` 改为 `pg_dump` |
| 部署文档 | 是 | 中 | 宝塔部署指南需要同步 |

---

## 6. 推荐实施阶段

迁移不要直接在生产库上一次性完成，建议分 5 个阶段。

### 阶段 0：迁移前冻结与备份

目标：确保任何迁移失败都能恢复。

要做：

1. 确认当前生产是否已有真实数据。
2. 停止新增写入，避免迁移过程中数据变化。
3. 备份 SQLite 数据库。
4. 备份 `.env`。
5. 备份上传文件、站点文件、cookies、日志。

服务器上可执行：

```bash
cd /opt/Auto_GEO-main/deploy/production
docker compose --env-file .env -f docker-compose.yml ps
```

备份 SQLite volume：

```bash
TS=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR=/opt/autogeo-backups/pre-postgres-$TS
mkdir -p "$BACKUP_DIR/database"

docker run --rm \
  -v autogeo_backend_database:/data:ro \
  -v "$BACKUP_DIR":/backup \
  alpine sh -c "cp -a /data/. /backup/database/"

cp .env "$BACKUP_DIR/.env.backup"
```

验收：

```bash
ls -lah "$BACKUP_DIR"
ls -lah "$BACKUP_DIR/database"
```

必须看到：

```text
auto_geo_v3.db
```

如果还有 WAL 文件，也一起保存：

```text
auto_geo_v3.db-wal
auto_geo_v3.db-shm
```

### 阶段 1：本地或测试服务器验证 PostgreSQL schema

目标：不碰生产数据，先证明 PostgreSQL 能跑。

建议在测试环境中执行：

```bash
cd /opt/Auto_GEO-main/deploy/production
cp .env.example .env.postgres-test
```

设置测试库连接：

```env
DATABASE_URL=postgresql://autogeo:强密码@postgres:5432/autogeo
POSTGRES_DB=autogeo
POSTGRES_USER=autogeo
POSTGRES_PASSWORD=强密码
```

然后启动 PostgreSQL 和后端，执行：

```bash
docker compose --env-file .env.postgres-test -f docker-compose.yml up -d postgres
docker compose --env-file .env.postgres-test -f docker-compose.yml run --rm backend \
  bash -lc "cd /app/backend && alembic upgrade head"
docker compose --env-file .env.postgres-test -f docker-compose.yml up -d backend
```

验收：

```bash
curl http://127.0.0.1:8001/api/health
```

预期：

```json
{
  "status": "ok",
  "services": {
    "database": {
      "status": "connected"
    }
  }
}
```

### 阶段 2：代码层兼容改造

目标：让后端在 PostgreSQL 模式下使用 Alembic，不再跑 SQLite 修复脚本。

#### 2.1 修改 `backend/main.py`

当前逻辑：

```python
init_db()
check_and_fix_database()
```

建议改为：

```python
from backend.database import init_db
from backend.config import get_database_type

init_db()
if get_database_type() == "sqlite":
    check_and_fix_database()
else:
    logger.info("PostgreSQL 模式跳过 SQLite fix_database，schema 由 Alembic 管理")
```

说明：

- `init_db()` 当前会执行 `Base.metadata.create_all()`，对 PostgreSQL 也能创建不存在的表。
- 但生产上更规范的是 Alembic 管理 schema。
- 短期可保留 `init_db()`，但要避免 SQLite 专用修复脚本误跑。

#### 2.2 修改 `backend/entrypoint.sh`

建议在启动后端前增加可控的 Alembic 执行：

```bash
if [ "${RUN_DB_MIGRATIONS:-true}" = "true" ]; then
  echo "Running database migrations..."
  cd /app/backend
  alembic upgrade head
  cd /app
fi
```

然后继续：

```bash
exec python -m backend.main
```

注意：

- 需要确认容器工作目录和 `alembic.ini` 路径。
- 当前 Dockerfile 把代码复制到 `/app/backend/`，`alembic.ini` 位于 `/app/backend/alembic.ini`。
- 所以执行 Alembic 前应 `cd /app/backend`。

#### 2.3 确认 Alembic 环境

当前 `backend/migrations/env.py` 会读取 `DATABASE_URL` 并覆盖 `sqlalchemy.url`，这符合预期。

需要验证：

```bash
cd backend
alembic history
alembic current
alembic upgrade head
```

#### 2.4 检查模型兼容性

重点检查：

- `Boolean` 默认值是否兼容 PostgreSQL。
- `DateTime` 是否需要 timezone。
- `JSON` 字段是否正常映射。
- `Text`、`String` 长度是否合理。
- 唯一索引是否会因历史重复数据导入失败。
- 外键约束是否会因旧数据不干净导入失败。
- 表名、列名是否使用了 PostgreSQL 保留字。

建议先不大规模改模型，先以迁移验证结果为准。

### 阶段 3：生产部署配置改造

目标：让 `deploy/production/docker-compose.yml` 支持 PostgreSQL。

#### 3.1 推荐 compose 结构

建议在 `services` 下新增：

```yaml
  postgres:
    image: postgres:15-alpine
    container_name: autogeo_postgres
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-autogeo}
      POSTGRES_USER: ${POSTGRES_USER:-autogeo}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      TZ: Asia/Shanghai
    volumes:
      - postgres_data:/var/lib/postgresql/data
    networks:
      - autogeo_network
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-autogeo} -d ${POSTGRES_DB:-autogeo}"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 20s
```

后端增加依赖：

```yaml
    depends_on:
      postgres:
        condition: service_healthy
```

后端环境变量改为：

```yaml
      DATABASE_URL: ${DATABASE_URL:-postgresql://autogeo:${POSTGRES_PASSWORD}@postgres:5432/autogeo}
      DB_POOL_SIZE: ${DB_POOL_SIZE:-10}
      DB_MAX_OVERFLOW: ${DB_MAX_OVERFLOW:-20}
      DB_POOL_TIMEOUT: ${DB_POOL_TIMEOUT:-30}
      DB_POOL_RECYCLE: ${DB_POOL_RECYCLE:-3600}
      RUN_DB_MIGRATIONS: ${RUN_DB_MIGRATIONS:-true}
```

新增 volume：

```yaml
  postgres_data:
    name: autogeo_postgres_data
```

#### 3.2 推荐 `.env` 增加配置

```env
# PostgreSQL
POSTGRES_DB=autogeo
POSTGRES_USER=autogeo
POSTGRES_PASSWORD=请换成强密码
DATABASE_URL=postgresql://autogeo:请换成强密码@postgres:5432/autogeo

# PostgreSQL connection pool
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=3600

# Run Alembic before backend starts
RUN_DB_MIGRATIONS=true
```

密码生成：

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

#### 3.3 URL 密码转义问题

如果数据库密码里包含特殊字符，如：

```text
@ : / ? # & %
```

写入 `DATABASE_URL` 时需要 URL encode。

例如密码：

```text
abc@123
```

应写成：

```text
abc%40123
```

为了减少出错，建议 PostgreSQL 密码使用：

```text
大小写字母 + 数字 + 下划线
```

避免特殊符号。

### 阶段 4：数据迁移

目标：把 SQLite 旧数据导入 PostgreSQL。

数据迁移有两条路线。

#### 方案 A：使用 pgloader

优点：

- 成熟。
- 自动处理较多 SQLite 到 PostgreSQL 类型映射。

缺点：

- 宝塔服务器可能需要额外安装。
- 对复杂约束、布尔值、时间字段仍需验证。

示例：

```bash
pgloader sqlite:////opt/backup/auto_geo_v3.db postgresql://autogeo:密码@127.0.0.1:5432/autogeo
```

如果 PostgreSQL 在 Docker 内：

```bash
docker run --rm \
  --network autogeo_network \
  -v /opt/autogeo-backups/pre-postgres/database:/backup:ro \
  dimitri/pgloader:latest \
  pgloader sqlite:////backup/auto_geo_v3.db postgresql://autogeo:密码@postgres:5432/autogeo
```

#### 方案 B：编写 Python 迁移脚本

优点：

- 可控。
- 可以按表处理脏数据。
- 可以跳过临时表、修复外键、处理默认值。

缺点：

- 需要多写一个迁移脚本。
- 要维护表顺序。

推荐用 Python 迁移脚本，原因是 AutoGeo 表较多，并且已有历史 `fix_database.py` 补字段逻辑，旧 SQLite 可能存在 schema 差异。脚本可按 SQLAlchemy model 或固定表顺序迁移。

推荐迁移思路：

1. 先做 `models.py` 与 Alembic 迁移脚本的 schema 差异审计。
2. 如有缺表或缺列，先补 Alembic migration。
3. PostgreSQL 执行 `alembic upgrade head` 建好 schema。
4. 关闭外键检查或按依赖顺序导入。
5. 从 SQLite 逐表读取。
6. 对字段做兼容转换。
7. 写入 PostgreSQL。
8. 重置 PostgreSQL 自增序列。
9. 输出每张表迁移数量。
10. 做数据校验。

建议表顺序大致为：

```text
users
system_configs
clients
projects
project_members
keywords
question_variants
geo_articles
index_check_records
accounts
account_groups
account_operation_logs
publish_records
scheduled_tasks
knowledge_categories
knowledge_items
reference_articles
auto_publish_tasks
auto_publish_records
site_projects
feishu_user_bindings
feishu_events
feishu_binding_codes
keyword_usage_records
conversation_sessions
conversation_messages
user_agent_preferences
```

实际表名要以当前数据库和 models 为准：

```bash
docker compose --env-file .env -f docker-compose.yml exec backend \
  python -c "from backend.database import Base; import backend.database.models; print(sorted(Base.metadata.tables.keys()))"
```

注意：不要在同一个目标库里混用“pgloader 自动建表导入”和“先 Alembic 建表再导入”两种方式。推荐生产路线是先 Alembic 建 schema，再用受控脚本逐表导入数据。pgloader 更适合作为测试和对照工具。

#### 4.1 迁移前数据统计

SQLite 统计：

```bash
sqlite3 auto_geo_v3.db ".tables"
sqlite3 auto_geo_v3.db "SELECT count(*) FROM users;"
sqlite3 auto_geo_v3.db "SELECT count(*) FROM projects;"
sqlite3 auto_geo_v3.db "SELECT count(*) FROM geo_articles;"
sqlite3 auto_geo_v3.db "SELECT count(*) FROM accounts;"
```

PostgreSQL 统计：

```bash
docker compose --env-file .env -f docker-compose.yml exec postgres \
  psql -U autogeo -d autogeo -c "\dt"
```

```bash
docker compose --env-file .env -f docker-compose.yml exec postgres \
  psql -U autogeo -d autogeo -c "SELECT count(*) FROM users;"
```

#### 4.2 迁移后序列修复

PostgreSQL 导入显式 ID 后，自增序列可能没有更新。需要修复。

示例：

```sql
SELECT setval(pg_get_serial_sequence('users', 'id'), COALESCE(MAX(id), 1)) FROM users;
SELECT setval(pg_get_serial_sequence('projects', 'id'), COALESCE(MAX(id), 1)) FROM projects;
SELECT setval(pg_get_serial_sequence('geo_articles', 'id'), COALESCE(MAX(id), 1)) FROM geo_articles;
```

建议迁移脚本自动为所有有 `id` 序列的表执行修复。

---

## 7. 详细操作步骤

### 7.1 生产迁移前准备

确认当前服务：

```bash
cd /opt/Auto_GEO-main/deploy/production
docker compose --env-file .env -f docker-compose.yml ps
```

确认健康检查：

```bash
curl http://127.0.0.1:8080/api/health
```

确认数据库文件存在：

```bash
docker run --rm -v autogeo_backend_database:/data alpine ls -lah /data
```

### 7.2 停止服务写入

建议迁移窗口内暂停服务：

```bash
docker compose --env-file .env -f docker-compose.yml stop frontend backend
```

注意：不要执行 `down -v`，否则会删除 volume。

### 7.3 完整备份

```bash
TS=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR=/opt/autogeo-backups/pre-postgres-$TS
mkdir -p "$BACKUP_DIR"

cp .env "$BACKUP_DIR/.env.backup"

docker run --rm \
  -v autogeo_backend_database:/data:ro \
  -v "$BACKUP_DIR":/backup \
  alpine sh -c "mkdir -p /backup/database && cp -a /data/. /backup/database/"

docker run --rm \
  -v autogeo_backend_cookies:/data:ro \
  -v "$BACKUP_DIR":/backup \
  alpine sh -c "mkdir -p /backup/cookies && cp -a /data/. /backup/cookies/" || true

docker run --rm \
  -v autogeo_backend_uploads:/data:ro \
  -v "$BACKUP_DIR":/backup \
  alpine sh -c "mkdir -p /backup/uploads && cp -a /data/. /backup/uploads/" || true

docker run --rm \
  -v autogeo_backend_sites:/data:ro \
  -v "$BACKUP_DIR":/backup \
  alpine sh -c "mkdir -p /backup/sites && cp -a /data/. /backup/sites/" || true
```

备份完成后马上确认文件：

```bash
find "$BACKUP_DIR" -maxdepth 3 -type f | sort
```

至少应包含：

```text
.env.backup
database/auto_geo_v3.db
```

如果 `auto_geo_v3.db-wal` 和 `auto_geo_v3.db-shm` 存在，也必须在备份目录里。

### 7.4 修改 compose 和 `.env`

按第 6 章修改：

- `deploy/production/docker-compose.yml`
- `deploy/production/.env`
- `deploy/production/.env.example`

修改后先只做配置解析检查：

```bash
docker compose --env-file .env -f docker-compose.yml config >/tmp/autogeo-compose-rendered.yml
```

如果这一步报错，说明 YAML 或环境变量有问题，先不要启动容器。

### 7.5 启动 PostgreSQL

```bash
docker compose --env-file .env -f docker-compose.yml up -d postgres
docker compose --env-file .env -f docker-compose.yml ps postgres
```

查看日志：

```bash
docker compose --env-file .env -f docker-compose.yml logs -f postgres
```

检查可连接：

```bash
docker compose --env-file .env -f docker-compose.yml exec postgres \
  pg_isready -U autogeo -d autogeo
```

### 7.6 执行 schema migration

```bash
docker compose --env-file .env -f docker-compose.yml run --rm backend \
  bash -lc "cd /app/backend && alembic upgrade head"
```

查看表：

```bash
docker compose --env-file .env -f docker-compose.yml exec postgres \
  psql -U autogeo -d autogeo -c "\dt"
```

执行完 migration 后，必须做一次“代码模型表”和“PostgreSQL 实际表”的对比。

查看当前代码模型需要的表：

```bash
docker compose --env-file .env -f docker-compose.yml run --rm backend \
  python -c "from backend.database import Base; import backend.database.models; print('\n'.join(sorted(Base.metadata.tables.keys())))"
```

查看 PostgreSQL 实际已经创建的表：

```bash
docker compose --env-file .env -f docker-compose.yml exec postgres \
  psql -U autogeo -d autogeo -Atc "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename;"
```

如果模型表里有、PostgreSQL 里没有，例如：

```text
conversation_sessions
conversation_messages
user_agent_preferences
```

就说明 Alembic 迁移脚本还没补齐。此时不要继续导入数据，应先新增 migration，重新执行 `alembic upgrade head`，再继续后续步骤。

### 7.7 导入数据

如果使用 pgloader：

```bash
docker run --rm \
  --network autogeo_network \
  -v "$BACKUP_DIR/database":/backup:ro \
  dimitri/pgloader:latest \
  pgloader sqlite:////backup/auto_geo_v3.db postgresql://autogeo:密码@postgres:5432/autogeo
```

如果使用 Python 脚本：

```bash
docker compose --env-file .env -f docker-compose.yml run --rm \
  -v "$BACKUP_DIR/database":/backup:ro \
  backend \
  python /app/backend/scripts/migrate_sqlite_to_postgres.py \
    --sqlite /backup/auto_geo_v3.db \
    --postgres "$DATABASE_URL"
```

这里需要先编写 `backend/scripts/migrate_sqlite_to_postgres.py`，并把备份目录挂入容器。上面的 `-v "$BACKUP_DIR/database":/backup:ro` 就是把 SQLite 备份目录以只读方式挂进后端容器。

导入完成后建议立刻保存一份 PostgreSQL dump，作为“迁移后、业务启动前”的检查点：

```bash
mkdir -p /opt/autogeo-backups/postgres-checkpoints
docker compose --env-file .env -f docker-compose.yml exec -T postgres \
  pg_dump -U autogeo -d autogeo > /opt/autogeo-backups/postgres-checkpoints/autogeo_after_import_$(date +%Y%m%d_%H%M%S).sql
```

### 7.8 启动后端和前端

```bash
docker compose --env-file .env -f docker-compose.yml up -d backend frontend
docker compose --env-file .env -f docker-compose.yml ps
```

### 7.9 验收

健康检查：

```bash
curl http://127.0.0.1:8080/api/health
```

容器日志：

```bash
docker compose --env-file .env -f docker-compose.yml logs -f backend
```

数据库类型确认：

```bash
docker compose --env-file .env -f docker-compose.yml exec backend \
  python -c "from backend.database import get_engine_info; print(get_engine_info())"
```

必须看到：

```text
'type': 'postgresql'
```

---

## 8. 验收清单

### 8.1 技术验收

- `/api/health` 返回正常。
- 后端日志无 `database is locked`。
- 后端日志无 `sqlite3` 修复脚本误执行 PostgreSQL 的异常。
- Alembic 当前版本为最新：

```bash
docker compose --env-file .env -f docker-compose.yml run --rm backend \
  bash -lc "cd /app/backend && alembic current"
```

- PostgreSQL 有业务表：

```bash
docker compose --env-file .env -f docker-compose.yml exec postgres \
  psql -U autogeo -d autogeo -c "\dt"
```

- 核心表数据量和 SQLite 迁移前一致或符合预期：

```sql
SELECT count(*) FROM users;
SELECT count(*) FROM projects;
SELECT count(*) FROM geo_articles;
SELECT count(*) FROM accounts;
SELECT count(*) FROM auto_publish_tasks;
```

### 8.2 业务验收

至少验证以下流程：

1. 打开前端登录页。
2. 使用已有账号登录。
3. 查看客户列表。
4. 查看项目列表。
5. 打开文章列表。
6. 查看账号管理。
7. 新建一个测试项目。
8. 新建一个测试关键词。
9. 新建或保存一篇测试文章。
10. 查看定时任务页面。
11. 查看知识库页面。
12. 如果启用飞书，验证飞书绑定列表。
13. 如果启用自动发布，验证任务创建和状态读取。

### 8.3 数据一致性验收

迁移前后对比：

| 表 | SQLite 数量 | PostgreSQL 数量 | 是否一致 |
|---|---:|---:|---|
| users |  |  |  |
| projects |  |  |  |
| keywords |  |  |  |
| geo_articles |  |  |  |
| accounts |  |  |  |
| clients |  |  |  |
| knowledge_categories |  |  |  |
| reference_articles |  |  |  |
| auto_publish_tasks |  |  |  |
| auto_publish_records |  |  |  |

---

## 9. 回滚方案

如果迁移后出现严重问题，应快速回滚到 SQLite。

### 9.1 回滚条件

满足任一情况即可回滚：

- 后端无法启动。
- 登录失败且短时间无法修复。
- 核心数据缺失。
- 发布任务无法读取。
- 数据迁移数量明显不一致。
- PostgreSQL 性能或连接异常影响线上使用。

### 9.2 回滚步骤

停止服务：

```bash
cd /opt/Auto_GEO-main/deploy/production
docker compose --env-file .env -f docker-compose.yml stop frontend backend
```

恢复 `.env`：

```bash
cp /opt/autogeo-backups/pre-postgres-时间戳/.env.backup .env
```

确认 `.env` 中恢复为：

```env
DATABASE_URL=sqlite:////app/database/auto_geo_v3.db
```

如果 SQLite volume 被改动过，恢复数据库 volume：

```bash
docker run --rm \
  -v autogeo_backend_database:/data \
  -v /opt/autogeo-backups/pre-postgres-时间戳/database:/backup:ro \
  alpine sh -c "rm -rf /data/* && cp -a /backup/. /data/"
```

启动服务：

```bash
docker compose --env-file .env -f docker-compose.yml up -d backend frontend
```

验证：

```bash
curl http://127.0.0.1:8080/api/health
```

### 9.3 回滚后处理

回滚后不要立刻删除 PostgreSQL volume。保留至少 7 天：

```text
autogeo_postgres_data
```

这样后续可以分析失败原因。

---

## 10. 备份与恢复新方案

迁移到 PostgreSQL 后，不能再只备份 `.db` 文件。应使用 `pg_dump`。

### 10.1 每日备份

```bash
BACKUP_DIR=/opt/autogeo-backups/postgres
mkdir -p "$BACKUP_DIR"
DATE=$(date +%Y%m%d_%H%M%S)

docker compose --env-file .env -f docker-compose.yml exec -T postgres \
  pg_dump -U autogeo -d autogeo > "$BACKUP_DIR/autogeo_$DATE.sql"

gzip "$BACKUP_DIR/autogeo_$DATE.sql"
```

### 10.2 保留最近 14 天

```bash
find /opt/autogeo-backups/postgres -name "autogeo_*.sql.gz" -mtime +14 -delete
```

### 10.3 恢复

恢复前先停后端：

```bash
docker compose --env-file .env -f docker-compose.yml stop backend
```

恢复数据库：

```bash
gunzip -c /opt/autogeo-backups/postgres/autogeo_时间.sql.gz | \
docker compose --env-file .env -f docker-compose.yml exec -T postgres \
  psql -U autogeo -d autogeo
```

启动后端：

```bash
docker compose --env-file .env -f docker-compose.yml up -d backend
```

---

## 11. 风险点与应对

### 11.1 SQLite 历史库 schema 不一致

风险：

历史 SQLite 可能依赖 `fix_database.py` 动态补列，而 Alembic migration 未完全覆盖这些列。

应对：

- 迁移前用 `PRAGMA table_info` 导出 SQLite schema。
- PostgreSQL 执行 Alembic 后导出 schema。
- 对比缺失列。
- 必要时补 Alembic migration。

### 11.2 旧数据违反新约束

风险：

PostgreSQL 比 SQLite 更严格，可能出现：

- 外键不满足。
- 唯一索引冲突。
- Boolean 值不是合法布尔。
- 空字符串和 NULL 处理差异。

应对：

- 先在测试库迁移。
- 迁移脚本输出失败行。
- 对脏数据做清洗。
- 不直接在生产首次尝试。

### 11.3 自增 ID 序列未同步

风险：

导入旧 ID 后，新建数据时报主键冲突。

应对：

- 迁移后执行序列修复。
- 新建用户、项目、文章各测试一次。

### 11.4 PostgreSQL 密码特殊字符导致连接失败

风险：

密码里有 `@` 或 `#`，`DATABASE_URL` 解析失败。

应对：

- 密码只使用字母、数字、下划线。
- 或使用 URL encode。

### 11.5 后端启动时数据库未就绪

风险：

后端比 PostgreSQL 先启动，连接失败。

应对：

- Compose 增加 `depends_on.condition: service_healthy`。
- 后端 entrypoint 中可增加等待数据库逻辑。

### 11.6 Alembic 与 `init_db()` 双重建表

风险：

`alembic upgrade head` 和 `Base.metadata.create_all()` 同时存在，长期可能造成 schema 管理混乱。

应对：

- 短期允许共存，但以 Alembic 为准。
- 中长期建议生产环境只由 Alembic 迁移 schema。
- `init_db()` 保留给本地 SQLite 快速初始化。

---

## 12. 建议代码改造清单

### 必改

- `backend/migrations/versions/`
  - 补齐当前 `backend/database/models.py` 中尚未被 Alembic 覆盖的表和列。
  - 当前重点关注 `conversation_sessions`、`conversation_messages`、`user_agent_preferences` 等较新模型。
  - PostgreSQL 生产环境必须以 Alembic 为准，不能依赖 `Base.metadata.create_all()` 隐式建表。

- `backend/main.py`
  - PostgreSQL 模式跳过 `check_and_fix_database()`。

- `backend/entrypoint.sh`
  - 启动前可选执行 `alembic upgrade head`。

- `deploy/production/docker-compose.yml`
  - 增加 postgres 服务。
  - 后端依赖 postgres healthcheck。
  - 后端 `DATABASE_URL` 默认改为 PostgreSQL。
  - 增加连接池环境变量。

- `deploy/production/.env.example`
  - 增加 PostgreSQL 配置模板。
  - 将 SQLite 标为本地/快速测试模式。

- `宝塔部署指南.md`
  - 从 SQLite 快速部署版升级为 PostgreSQL 正式部署版。

### 建议新增

- `backend/scripts/migrate_sqlite_to_postgres.py`
  - SQLite 到 PostgreSQL 的可控数据迁移脚本。
  - 脚本应输出每张表的读取数量、写入数量、跳过数量、失败行详情。
  - 脚本应自动修复 PostgreSQL 自增序列。

- `scripts/backup-postgres.sh`
  - PostgreSQL 备份脚本。

- `scripts/restore-postgres.sh`
  - PostgreSQL 恢复脚本。

- `docs/postgresql-runbook.md`
  - 日常运维手册，可后续拆分。

### 可后续优化

- 生产环境禁用 `Base.metadata.create_all()`，只使用 Alembic。
- 增加数据库连接重试。
- 增加 `/api/health` 返回数据库类型和 migration version。
- 增加迁移集成测试。

### 迁移脚本最低要求

`migrate_sqlite_to_postgres.py` 至少应具备：

- `--sqlite`：SQLite 文件路径。
- `--postgres`：PostgreSQL 连接字符串。
- `--dry-run`：只统计和校验，不写入。
- `--tables`：可选，只迁移指定表，方便调试。
- `--truncate-target`：可选，清空目标表后重新导入。生产慎用。
- 导入前检查目标库是否为空或是否允许覆盖。
- 自动按依赖顺序迁移表。
- 对 JSON/Text、Boolean、DateTime、空字符串、NULL 做兼容转换。
- 导入后自动修复所有序列。
- 生成迁移报告，例如 `migration_report_YYYYMMDD_HHMMSS.json`。

迁移报告建议包含：

```json
{
  "source": "auto_geo_v3.db",
  "target": "postgresql://autogeo@postgres:5432/autogeo",
  "started_at": "2026-06-11T20:00:00+08:00",
  "finished_at": "2026-06-11T20:03:00+08:00",
  "tables": {
    "users": {"read": 10, "inserted": 10, "failed": 0},
    "projects": {"read": 5, "inserted": 5, "failed": 0}
  }
}
```

---

## 13. 推荐执行顺序

推荐顺序如下：

1. 新增本文档，团队确认方案。
2. 改 `backend/main.py`，让 PostgreSQL 跳过 SQLite 修复脚本。
3. 改 `backend/entrypoint.sh`，支持 `RUN_DB_MIGRATIONS=true`。
4. 改 `deploy/production/docker-compose.yml`，增加 postgres 服务。
5. 改 `.env.example`，提供 PostgreSQL 模板。
6. 本地或测试服务器启动 PostgreSQL。
7. 执行 `alembic upgrade head`。
8. 跑后端健康检查。
9. 写并测试 SQLite 到 PostgreSQL 数据迁移脚本。
10. 在测试库迁移一份生产 SQLite 备份。
11. 对比表数量和核心业务流程。
12. 安排生产维护窗口。
13. 备份生产 SQLite。
14. 停止生产前后端。
15. 启动生产 PostgreSQL。
16. 执行 Alembic。
17. 导入 SQLite 数据。
18. 修复序列。
19. 启动后端和前端。
20. 按验收清单验证。
21. 保留 SQLite 备份和 PostgreSQL 迁移日志。

---

## 14. 工期预估

如果只做 PostgreSQL 空库部署：

```text
0.5 - 1 天
```

如果需要迁移现有 SQLite 真实数据：

```text
1.5 - 3 天
```

如果历史数据比较脏，或 Alembic 与 SQLite 实际 schema 差异较大：

```text
3 - 5 天
```

建议不要压缩测试阶段。真正的风险不在“能不能连上 PostgreSQL”，而在“旧数据能不能完整、干净、可回滚地导入”。

---

## 15. 最终建议

AutoGeo 正式部署建议切换到 PostgreSQL，但不要直接在当前宝塔生产环境上裸改。最佳路线是：

1. 保留 SQLite 作为本地开发和快速演示方案。
2. 将宝塔正式部署默认改为 PostgreSQL。
3. PostgreSQL schema 全部交给 Alembic。
4. SQLite 历史修复脚本只在 SQLite 模式运行。
5. 先测试迁移一份生产备份，确认数据和业务流程无误后，再切正式环境。

这样迁移风险可控，也给后续多用户、长期运营、自动发布任务增长留出稳定基础。
