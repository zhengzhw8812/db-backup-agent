#!/bin/bash

# 脚本出错时立即退出，管道命令中任何一步失败则整个管道失败
set -e
set -o pipefail

# --- 配置 ---
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/backups"
RETENTION_DAYS=7 # 备份保留天数

echo "[$(date)] 开始备份任务..."

# --------------------------
# 1. PostgreSQL 备份
# --------------------------
if [ -n "$PG_HOST" ]; then
    echo "正在备份 PostgreSQL (全局对象和数据库 $PG_DB)..."

    GLOBALS_FILE="$BACKUP_DIR/pg_globals_${DATE}.sql"
    DB_FILE="$BACKUP_DIR/pg_${PG_DB}_${DATE}.sql"
    ARCHIVE_FILE="$BACKUP_DIR/pg_backup_${DATE}.tar.gz"

    # 导出全局对象
    echo "  -> 正在导出 PostgreSQL 全局对象..."
    PGPASSWORD=$PG_PASSWORD pg_dumpall -h $PG_HOST -p $PG_PORT -U $PG_USER --globals-only -f "$GLOBALS_FILE"

    # 导出指定数据库
    echo "  -> 正在导出 PostgreSQL 数据库 '$PG_DB'..."
    PGPASSWORD=$PG_PASSWORD pg_dump -h $PG_HOST -p $PG_PORT -U $PG_USER -d $PG_DB -f "$DB_FILE"

    # 打包成 tar.gz
    echo "  -> 正在创建 tar.gz 归档文件..."
    tar -czf "$ARCHIVE_FILE" -C "$BACKUP_DIR" "$(basename "$GLOBALS_FILE")" "$(basename "$DB_FILE")"

    # 清理临时文件
    echo "  -> 正在清理临时文件..."
    rm -f "$GLOBALS_FILE" "$DB_FILE"

    echo "PostgreSQL 备份成功: $ARCHIVE_FILE"
fi

# --------------------------
# 2. MySQL 备份
# --------------------------
if [ -n "$MYSQL_HOST" ]; then
    echo "正在备份 MySQL (所有数据库)..."
    ARCHIVE_FILE="$BACKUP_DIR/mysql_all_databases_${DATE}.sql.gz"

    # 使用 MYSQL_PWD 环境变量传递密码，更安全
    MYSQL_PWD=$MYSQL_PASSWORD mysqldump -h $MYSQL_HOST -P $MYSQL_PORT -u $MYSQL_USER --all-databases | gzip > "$ARCHIVE_FILE"

    echo "MySQL 备份成功: $ARCHIVE_FILE"
fi

# --------------------------
# 3. 清理旧备份
# --------------------------
echo "正在清理 $RETENTION_DAYS 天前的旧备份..."
# 同时匹配 .sql.gz 和 .tar.gz 文件，并使用 -delete 高效删除
find "$BACKUP_DIR" -type f \( -name "*.sql.gz" -o -name "*.tar.gz" \) -mtime +$RETENTION_DAYS -delete

echo "[$(date)] 所有任务成功完成."