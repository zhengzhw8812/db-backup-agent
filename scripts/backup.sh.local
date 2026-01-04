#!/bin/bash

# 脚本出错时立即退出
set -e
set -o pipefail

# --- 配置 ---
CONFIG_FILE="/backups/config.json"
BACKUP_DIR="/backups"
RETENTION_DAYS=7 # 默认备份保留天数
DATE=$(date +%Y%m%d_%H%M%S)
DETAIL_LOG_DIR="/backups/logs/details"

# 从第一个命令行参数读取要备份的数据库类型
DB_TYPE_TO_BACKUP=$1

HISTORY_LOG_FILE="/backups/backup_history.log"

# --- 日志记录函数 ---
log_history() {
    local db_type="$1"
    local trigger_type="$2"
    local status="$3"
    local message="$4"
    local log_file="$5"

    # 如果提供了日志文件路径，只取文件名部分
    if [[ -n "$log_file" ]]; then
        log_file="${log_file##*/}"
    fi

    # 统一日志格式为6个字段
    echo "$(date '+%Y-%m-%d %H:%M:%S') | ${db_type} | ${trigger_type} | ${status} | ${message} | ${log_file}" >> "$HISTORY_LOG_FILE"
}

# --- 备份函数 ---
backup_postgresql() {
    local trigger_type=$1
    echo "[$(date)] 正在备份 PostgreSQL 数据库..."
    
    pg_dbs=$(jq -r '.postgresql[] | "\(.host);\(.port);\(.user);\(.password);\(.db)"' "$CONFIG_FILE")

    for db_info in $pg_dbs; do
        IFS=';' read -r host port user password dbname < <(echo "$db_info")
        
        backup_file="${BACKUP_DIR}/pg_${dbname}_${DATE}.sql.gz"
        
        echo "[$(date)] > 正在备份 ${dbname} 到 ${backup_file}..."
        
        export PGPASSWORD=$password
        if pg_dump -h "$host" -p "$port" -U "$user" -d "$dbname" | gzip > "$backup_file"; then
            log_history "PostgreSQL" "$trigger_type" "成功" "数据库 ${dbname} 已备份到 ${backup_file##*/}"
        else
            log_history "PostgreSQL" "$trigger_type" "失败" "数据库 ${dbname} 备份失败" "$DETAIL_LOG_FILE"
            rm -f "$backup_file" # 删除失败的备份文件
        fi
        unset PGPASSWORD
    done
}

backup_mysql() {
    local trigger_type=$1
    echo "[$(date)] 正在备份 MySQL 数据库..."

    mysql_dbs=$(jq -r '.mysql[] | "\(.host);\(.port);\(.user);\(.password);\(.db)"' "$CONFIG_FILE")

    for db_info in $mysql_dbs; do
        IFS=';' read -r host port user password dbname < <(echo "$db_info")
        
        if [ -z "$dbname" ]; then # 备份所有数据库
            backup_file="${BACKUP_DIR}/mysql_all_${DATE}.sql.gz"
            echo "[$(date)] > 正在备份所有 MySQL 数据库到 ${backup_file}..."
            if mysqldump -h "$host" -P "$port" -u "$user" --password="$password" --all-databases | gzip > "$backup_file"; then
                log_history "MySQL" "$trigger_type" "成功" "所有数据库已备份到 ${backup_file##*/}"
            else
                log_history "MySQL" "$trigger_type" "失败" "所有数据库备份失败" "$DETAIL_LOG_FILE"
                rm -f "$backup_file"
            fi
        else # 备份单个数据库
            backup_file="${BACKUP_DIR}/mysql_${dbname}_${DATE}.sql.gz"
            echo "[$(date)] > 正在备份数据库 ${dbname} 到 ${backup_file}..."
            if mysqldump -h "$host" -P "$port" -u "$user" --password="$password" --databases "$dbname" | gzip > "$backup_file"; then
                log_history "MySQL" "$trigger_type" "成功" "数据库 ${dbname} 已备份到 ${backup_file##*/}"
            else
                log_history "MySQL" "$trigger_type" "失败" "数据库 ${dbname} 备份失败" "$DETAIL_LOG_FILE"
                rm -f "$backup_file"
            fi
        fi
    done
}

# --- 清理函数 ---
cleanup_old_backups() {
    echo "[$(date)] 正在清理旧备份..."
    local retention_days=$(jq -r '.retention_days // 7' "$CONFIG_FILE")
    echo "保留最近 ${retention_days} 天的备份。"
    
    find "$BACKUP_DIR" -name "*.sql.gz" -o -name "*.tar.gz" -mtime +$((retention_days - 1)) -exec rm -f {} \;
}

# --- 主逻辑 ---
main() {
    # 确保详细日志目录存在
    mkdir -p "$DETAIL_LOG_DIR"

    DETAIL_LOG_FILE="${DETAIL_LOG_DIR}/backup_${DATE}.log"
    # 将所有输出重定向到日志文件，同时也在控制台显示
    exec &> >(tee -a "$DETAIL_LOG_FILE")

    echo "[$(date)] 开始备份任务... (日志文件: ${DETAIL_LOG_FILE##*/})"
    
    DB_TYPE_TO_BACKUP=$1
    # 第二个参数是触发类型。如果未提供，则默认为“手动”。
    local trigger_type=${2:-“手动”}

    if [ ! -s "$CONFIG_FILE" ]; then
        echo "[$(date)] 配置文件 $CONFIG_FILE 不存在或为空，跳过备份。"
        log_history "系统" "$trigger_type" "警告" "配置文件不存在或为空"
        exit 1
    fi

    # 根据传入的参数决定备份哪个数据库
    if [ -z "$DB_TYPE_TO_BACKUP" ] || [ "$DB_TYPE_TO_BACKUP" == "postgresql" ]; then
        if [ "$(jq -r '.postgresql | length' "$CONFIG_FILE")" -gt 0 ]; then
            backup_postgresql "$trigger_type"
        else
            echo "[$(date)] 未配置PostgreSQL数据库，跳过备份。"
            log_history "PostgreSQL" "$trigger_type" "跳过" "未配置"
        fi
    fi

    if [ -z "$DB_TYPE_TO_BACKUP" ] || [ "$DB_TYPE_TO_BACKUP" == "mysql" ]; then
        if [ "$(jq -r '.mysql | length' "$CONFIG_FILE")" -gt 0 ]; then
            backup_mysql "$trigger_type"
        else
            echo "[$(date)] 未配置MySQL数据库，跳过备份。"
            log_history "MySQL" "$trigger_type" "跳过" "未配置"
        fi
    fi

    # 如果是自动任务，则执行清理
    if [ "$trigger_type" == "自动" ]; then
        cleanup_old_backups
    fi

    echo "[$(date)] 所有任务成功完成."
}

main "$@"
