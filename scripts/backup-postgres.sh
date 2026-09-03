#!/usr/bin/env bash
# ============================================================
# AutoGeo PostgreSQL 备份脚本
#
# 用法:
#   ./scripts/backup-postgres.sh [COMPOSE_ENV_FILE] [COMPOSE_FILE]
#
# 默认值:
#   COMPOSE_ENV_FILE = deploy/production/.env
#   COMPOSE_FILE     = deploy/production/docker-compose.yml
#
# 备份存放位置:
#   /opt/autogeo-backups/postgres/autogeo_YYYYMMDD_HHMMSS.sql.gz
#
# 定时任务 (crontab -e):
#   0 2 * * * /opt/Auto_GEO-main/scripts/backup-postgres.sh >> /var/log/autogeo-backup.log 2>&1
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

COMPOSE_ENV_FILE="${1:-${PROJECT_DIR}/deploy/production/.env}"
COMPOSE_FILE="${2:-${PROJECT_DIR}/deploy/production/docker-compose.yml}"

BACKUP_BASE="/opt/autogeo-backups/postgres"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"

# 加载 .env 获取 POSTGRES_USER / POSTGRES_DB
if [ -f "${COMPOSE_ENV_FILE}" ]; then
    # 只提取需要的变量，不污染环境
    POSTGRES_USER=$(grep -E '^POSTGRES_USER=' "${COMPOSE_ENV_FILE}" | tail -1 | cut -d= -f2- || echo "autogeo")
    POSTGRES_DB=$(grep -E '^POSTGRES_DB=' "${COMPOSE_ENV_FILE}" | tail -1 | cut -d= -f2- || echo "autogeo")
else
    POSTGRES_USER="autogeo"
    POSTGRES_DB="autogeo"
fi

DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_BASE}/autogeo_${DATE}.sql"

echo "=========================================="
echo "AutoGeo PostgreSQL Backup"
echo "Time:       $(date '+%Y-%m-%d %H:%M:%S')"
echo "Database:   ${POSTGRES_DB}"
echo "User:       ${POSTGRES_USER}"
echo "Output:     ${BACKUP_FILE}.gz"
echo "=========================================="

# 创建备份目录
mkdir -p "${BACKUP_BASE}"

# 执行 pg_dump
docker compose \
    --env-file "${COMPOSE_ENV_FILE}" \
    -f "${COMPOSE_FILE}" \
    exec -T postgres \
    pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
    --no-owner --no-acl --clean --if-exists \
    > "${BACKUP_FILE}"

# 压缩
gzip "${BACKUP_FILE}"

# 检查结果
if [ -f "${BACKUP_FILE}.gz" ]; then
    SIZE=$(du -h "${BACKUP_FILE}.gz" | cut -f1)
    echo "✅ 备份成功: ${BACKUP_FILE}.gz (${SIZE})"
else
    echo "❌ 备份失败!"
    exit 1
fi

# 清理过期备份
DELETED=$(find "${BACKUP_BASE}" -name "autogeo_*.sql.gz" -mtime +${RETENTION_DAYS} -delete -print | wc -l || true)
if [ "${DELETED}" -gt 0 ]; then
    echo "🗑️  已清理 ${DELETED} 个超过 ${RETENTION_DAYS} 天的旧备份"
fi

echo "=========================================="
echo "Backup completed"
echo "=========================================="
