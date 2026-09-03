#!/usr/bin/env bash
# ============================================================
# AutoGeo PostgreSQL 恢复脚本
#
# 用法:
#   ./scripts/restore-postgres.sh <备份文件.sql.gz> [COMPOSE_ENV_FILE] [COMPOSE_FILE]
#
# 示例:
#   ./scripts/restore-postgres.sh /opt/autogeo-backups/postgres/autogeo_20260611_120000.sql.gz
#
# 注意:
#   - 恢复前会自动停止后端服务，防止写入冲突
#   - 恢复完成后需要手动重启后端
#   - 备份文件必须为 .sql.gz 格式
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

BACKUP_FILE="${1:?用法: $0 <备份文件.sql.gz> [COMPOSE_ENV_FILE] [COMPOSE_FILE]}"
COMPOSE_ENV_FILE="${2:-${PROJECT_DIR}/deploy/production/.env}"
COMPOSE_FILE="${3:-${PROJECT_DIR}/deploy/production/docker-compose.yml}"

# 参数校验
if [ ! -f "${BACKUP_FILE}" ]; then
    echo "❌ 备份文件不存在: ${BACKUP_FILE}"
    exit 1
fi

if [[ "${BACKUP_FILE}" != *.sql.gz ]]; then
    echo "❌ 备份文件必须是 .sql.gz 格式"
    exit 1
fi

# 加载 .env
if [ -f "${COMPOSE_ENV_FILE}" ]; then
    POSTGRES_USER=$(grep -E '^POSTGRES_USER=' "${COMPOSE_ENV_FILE}" | tail -1 | cut -d= -f2- || echo "autogeo")
    POSTGRES_DB=$(grep -E '^POSTGRES_DB=' "${COMPOSE_ENV_FILE}" | tail -1 | cut -d= -f2- || echo "autogeo")
else
    POSTGRES_USER="autogeo"
    POSTGRES_DB="autogeo"
fi

echo "=========================================="
echo "⚠️  AutoGeo PostgreSQL 恢复"
echo "=========================================="
echo "备份文件:   ${BACKUP_FILE}"
echo "数据库:     ${POSTGRES_DB}"
echo "用户:       ${POSTGRES_USER}"
echo ""
echo "⚠️  此操作将:"
echo "  1. 停止后端服务"
echo  "  2. 恢复数据库到备份时的状态"
echo "  3. 当前数据库数据将被覆盖"
echo ""
read -p "确认继续? (yes/no): " CONFIRM
if [ "${CONFIRM}" != "yes" ]; then
    echo "已取消"
    exit 0
fi

# 1. 停止后端
echo ""
echo "⏸️  停止后端服务..."
docker compose \
    --env-file "${COMPOSE_ENV_FILE}" \
    -f "${COMPOSE_FILE}" \
    stop backend

# 2. 解压并恢复
echo "📦 恢复数据库..."
gunzip -c "${BACKUP_FILE}" | \
    docker compose \
        --env-file "${COMPOSE_ENV_FILE}" \
        -f "${COMPOSE_FILE}" \
        exec -T postgres \
        psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
        2>&1 | tail -20

# 3. 验证
echo ""
echo "🔍 验证数据库..."
TABLE_COUNT=$(docker compose \
    --env-file "${COMPOSE_ENV_FILE}" \
    -f "${COMPOSE_FILE}" \
    exec -T postgres \
    psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
    -t -c "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'" \
    | tr -d '[:space:]')

echo "  公共表数量: ${TABLE_COUNT}"

# 4. 提示重启
echo ""
echo "=========================================="
echo "✅ 数据库恢复完成"
echo ""
echo "下一步 — 启动后端:"
echo "  docker compose --env-file ${COMPOSE_ENV_FILE} -f ${COMPOSE_FILE} up -d backend"
echo "=========================================="
