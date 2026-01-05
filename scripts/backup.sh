#!/bin/bash

# 脚本出错时立即退出（但管道命令中的部分失败不会导致退出）
set -e

# --- 配置 ---
CONFIG_MANAGER="/config_manager.py"
SYSTEM_LOGGER="/app/system_logger.py"
BACKUP_DIR="/backups"
RETENTION_DAYS=7 # 默认备份保留天数
DATE=$(date +%Y%m%d_%H%M%S)

# --- 系统日志函数 ---
log_system() {
    local log_type="$1"  # info/warning/error/debug
    local category="$2"  # backup/notify/system/cron
    local message="$3"
    local details="$4"

    # 记录到数据库（后台执行，输出到 /dev/null）
    python3 "$SYSTEM_LOGGER" log \
        --type "$log_type" \
        --category "$category" \
        --message "$message" \
        --details "$details" > /dev/null 2>&1 &
}

# 从第一个命令行参数读取要备份的数据库类型
DB_TYPE_TO_BACKUP=$1
# 从第二个命令行参数读取触发方式（手动/自动）
TRIGGER_TYPE=${2:-自动}
# 从第三个命令行参数读取单个数据库ID（可选）
SINGLE_DB_ID=${3:-}

# --- 日志记录函数 ---
log_history() {
    local db_type="$1"
    local trigger_type="$2"
    local status="$3"
    local message="$4"
    local log_file="$5"
    local backup_file="$6"

    # 如果提供了日志文件路径，只取文件名部分
    if [[ -n "$log_file" ]]; then
        log_file="${log_file##*/}"
    fi

    # 使用 Python 记录到数据库
    # 提取数据库名称
    local db_name=""
    if [[ "$message" =~ 数据库[[:space:]](.+?)[[:space:]]已备份 ]] || [[ "$message" =~ 数据库[[:space:]](.+?)[[:space:]]备份 ]]; then
        db_name="${BASH_REMATCH[1]}"
    fi

    # 获取备份文件大小（等待文件写入完成）
    local file_size=0
    if [[ -n "$backup_file" ]]; then
        # 等待文件出现并稳定
        local max_wait=10
        local waited=0
        while [[ ! -f "$BACKUP_DIR/$backup_file" && $waited -lt $max_wait ]]; do
            sleep 0.5
            waited=$((waited + 1))
        done

        if [[ -f "$BACKUP_DIR/$backup_file" ]]; then
            file_size=$(stat -c%s "$BACKUP_DIR/$backup_file" 2>/dev/null || stat -f%z "$BACKUP_DIR/$backup_file" 2>/dev/null || echo 0)
        fi
    fi

    # 记录到数据库（后台执行，输出到 /dev/null）
    python3 /app/backup_logger.py log \
        --type "$db_type" \
        --name "$db_name" \
        --trigger "$trigger_type" \
        --status "$status" \
        --message "$message" \
        --file "$backup_file" \
        --size "$file_size" \
        --log "$log_file" > /dev/null 2>&1 &


    # 发送通知
    send_backup_notification "$db_type" "$status" "$message" "$trigger_type" "$backup_file"
}

# --- 通知函数 ---
send_backup_notification() {
    local db_type="$1"
    local status="$2"
    local message="$3"
    local trigger_type="$4"
    local backup_file="$5"

    # 检查通知模块是否存在
    if [[ ! -f "/app/notifications.py" ]]; then
        return 0
    fi

    # 调用通知模块（后台执行，不阻塞备份流程）
    local notify_args="--type \"$db_type\" --status \"$status\" --message \"$message\" --trigger \"$trigger_type\""
    if [[ -n "$backup_file" ]]; then
        notify_args="$notify_args --file \"$backup_file\""
    fi

    # 在后台执行通知发送，忽略错误以免影响备份任务（输出到 /dev/null）
    eval "python3 /app/notifications.py $notify_args" > /dev/null 2>&1 &
}

# --- 备份函数 ---
backup_postgresql() {
    local trigger_type=$1
    local specific_db_id=$2  # 可选：只备份指定的数据库

    echo "[$(date)] 正在备份 PostgreSQL 数据库..."

    if [[ -n "$specific_db_id" ]]; then
        log_system "info" "backup" "开始 PostgreSQL 单个数据库备份任务" "触发方式: $trigger_type, 数据库ID: $specific_db_id"
    else
        log_system "info" "backup" "开始 PostgreSQL 备份任务" "触发方式: $trigger_type"
    fi

    pg_dbs=$(python3 "$CONFIG_MANAGER" get_dbs --db_type postgresql 2>/dev/null)

    if [[ -z "$pg_dbs" ]]; then
        echo "[$(date)] 未配置PostgreSQL数据库，跳过备份。"
        log_history "PostgreSQL" "$trigger_type" "跳过" "未配置"
        log_system "warning" "backup" "未配置PostgreSQL数据库，跳过备份"
        return
    fi

    for db_info in $pg_dbs; do
        IFS=';' read -r host port user password dbname conn_id < <(echo "$db_info")

        # 如果指定了数据库ID，只备份匹配的数据库
        if [[ -n "$specific_db_id" && "$conn_id" != "$specific_db_id" ]]; then
            continue
        fi

        if [ -z "$dbname" ]; then # 备份所有数据库
            backup_file="${BACKUP_DIR}/pg_all_${DATE}.sql.gz"
            echo "[$(date)] > 正在备份所有 PostgreSQL 数据库到 ${backup_file}..."
            log_system "info" "backup" "开始备份所有 PostgreSQL 数据库" "目标文件: ${backup_file##*/}"

            export PGPASSWORD=$password

            # 逐个备份所有用户数据库（排除系统模板数据库）
            databases=$(psql -h "$host" -p "$port" -U "$user" -d "postgres" -tAc "SELECT datname FROM pg_database WHERE datistemplate = false ORDER BY datname" 2>/dev/null)

            if [[ -n "$databases" ]]; then
                # 创建临时文件
                local temp_file="${BACKUP_DIR}/pg_all_${DATE}.tmp.sql.gz"

                # 逐个转储数据库并合并
                first=true
                for db in $databases; do
                    echo "[$(date)] >> 备份数据库: $db"
                    if $first; then
                        # 第一个数据库，直接创建文件
                        pg_dump -h "$host" -p "$port" -U "$user" -d "$db" 2>/dev/null | gzip > "$temp_file"
                        first=false
                    else
                        # 后续数据库，追加到文件
                        pg_dump -h "$host" -p "$port" -U "$user" -d "$db" 2>/dev/null | gzip >> "$temp_file"
                    fi
                done

                # 重命名为最终文件
                mv "$temp_file" "$backup_file"

                if [[ -f "$backup_file" && -s "$backup_file" ]]; then
                    log_history "PostgreSQL" "$trigger_type" "成功" "所有数据库已备份到 ${backup_file##*/}" "" "${backup_file##*/}"
                    log_system "info" "backup" "PostgreSQL 所有数据库备份成功" "文件: ${backup_file##*/}"
                else
                    log_history "PostgreSQL" "$trigger_type" "失败" "所有数据库备份失败" "" ""
                    log_system "error" "backup" "PostgreSQL 所有数据库备份失败" "主机: ${host}"
                    rm -f "$backup_file"
                fi
            else
                log_history "PostgreSQL" "$trigger_type" "失败" "无法获取数据库列表" "" ""
                log_system "error" "backup" "PostgreSQL 无法获取数据库列表" "主机: ${host}"
            fi
            unset PGPASSWORD
        else # 备份单个数据库
            backup_file="${BACKUP_DIR}/pg_${dbname}_${DATE}.sql.gz"

            echo "[$(date)] > 正在备份 ${dbname} 到 ${backup_file}..."
            log_system "info" "backup" "开始备份数据库: $dbname" "目标文件: ${backup_file##*/}"

            export PGPASSWORD=$password
            if pg_dump -h "$host" -p "$port" -U "$user" -d "$dbname" | gzip > "$backup_file"; then
                log_history "PostgreSQL" "$trigger_type" "成功" "数据库 ${dbname} 已备份到 ${backup_file##*/}" "" "${backup_file##*/}"
                log_system "info" "backup" "PostgreSQL 数据库备份成功" "数据库: ${dbname}, 文件: ${backup_file##*/}"
            else
                log_history "PostgreSQL" "$trigger_type" "失败" "数据库 ${dbname} 备份失败" "" ""
                log_system "error" "backup" "PostgreSQL 数据库备份失败" "数据库: ${dbname}, 主机: ${host}"
                rm -f "$backup_file" # 删除失败的备份文件
            fi
            unset PGPASSWORD
        fi
    done
}

backup_mysql() {
    local trigger_type=$1
    local specific_db_id=$2  # 可选：只备份指定的数据库

    echo "[$(date)] 正在备份 MySQL 数据库..."

    if [[ -n "$specific_db_id" ]]; then
        log_system "info" "backup" "开始 MySQL 单个数据库备份任务" "触发方式: $trigger_type, 数据库ID: $specific_db_id"
    else
        log_system "info" "backup" "开始 MySQL 备份任务" "触发方式: $trigger_type"
    fi

    mysql_dbs=$(python3 "$CONFIG_MANAGER" get_dbs --db_type mysql 2>/dev/null)

    if [[ -z "$mysql_dbs" ]]; then
        echo "[$(date)] 未配置MySQL数据库，跳过备份。"
        log_history "MySQL" "$trigger_type" "跳过" "未配置"
        log_system "warning" "backup" "未配置MySQL数据库，跳过备份"
        return
    fi

    for db_info in $mysql_dbs; do
        IFS=';' read -r host port user password dbname conn_id < <(echo "$db_info")

        # 如果指定了数据库ID，只备份匹配的数据库
        if [[ -n "$specific_db_id" && "$conn_id" != "$specific_db_id" ]]; then
            continue
        fi

        if [ -z "$dbname" ]; then # 备份所有数据库
            backup_file="${BACKUP_DIR}/mysql_all_${DATE}.sql.gz"
            echo "[$(date)] > 正在备份所有 MySQL 数据库到 ${backup_file}..."
            log_system "info" "backup" "开始备份所有 MySQL 数据库" "目标文件: ${backup_file##*/}"
            if mysqldump -h "$host" -P "$port" -u "$user" --password="$password" --all-databases | gzip > "$backup_file"; then
                log_history "MySQL" "$trigger_type" "成功" "所有数据库已备份到 ${backup_file##*/}" "" "${backup_file##*/}"
                log_system "info" "backup" "MySQL 所有数据库备份成功" "文件: ${backup_file##*/}"
            else
                log_history "MySQL" "$trigger_type" "失败" "所有数据库备份失败" "" ""
                log_system "error" "backup" "MySQL 所有数据库备份失败" "主机: ${host}"
                rm -f "$backup_file"
            fi
        else # 备份单个数据库
            backup_file="${BACKUP_DIR}/mysql_${dbname}_${DATE}.sql.gz"
            echo "[$(date)] > 正在备份数据库 ${dbname} 到 ${backup_file}..."
            log_system "info" "backup" "开始备份 MySQL 数据库: $dbname" "目标文件: ${backup_file##*/}"
            if mysqldump -h "$host" -P "$port" -u "$user" --password="$password" --databases "$dbname" | gzip > "$backup_file"; then
                log_history "MySQL" "$trigger_type" "成功" "数据库 ${dbname} 已备份到 ${backup_file##*/}" "" "${backup_file##*/}"
                log_system "info" "backup" "MySQL 数据库备份成功" "数据库: ${dbname}, 文件: ${backup_file##*/}"
            else
                log_history "MySQL" "$trigger_type" "失败" "数据库 ${dbname} 备份失败" "" ""
                log_system "error" "backup" "MySQL 数据库备份失败" "数据库: ${dbname}, 主机: ${host}"
                rm -f "$backup_file"
            fi
        fi
    done
}

# --- 清理函数 ---
cleanup_old_backups() {
    echo "[$(date)] 正在清理旧备份..."

    # 获取 PostgreSQL 的保留天数作为默认值
    local retention_days=$(python3 "$CONFIG_MANAGER" get_retention --db_type postgresql 2>/dev/null || echo 7)

    echo "保留最近 ${retention_days} 天的备份。"
    log_system "info" "cleanup" "开始清理旧备份" "保留天数: ${retention_days}"

    local deleted_count=$(find "$BACKUP_DIR" -name "*.sql.gz" -o -name "*.tar.gz" -mtime +$((retention_days - 1)) -print | wc -l)
    find "$BACKUP_DIR" -name "*.sql.gz" -o -name "*.tar.gz" -mtime +$((retention_days - 1)) -exec rm -f {} \;

    log_system "info" "cleanup" "清理旧备份完成" "删除了 ${deleted_count} 个文件"

    # 清理数据库中的旧系统日志（保留30天）
    echo "[$(date)] 正在清理数据库旧系统日志..."
    local log_retention_days=30
    local deleted_logs=$(python3 "$SYSTEM_LOGGER" clear --days $log_retention_days 2>/dev/null || echo 0)
    log_system "info" "cleanup" "清理系统日志完成" "删除了 ${deleted_logs} 条系统日志，保留最近 ${log_retention_days} 天"

    # 清理数据库中的旧备份历史记录（保留30天）
    echo "[$(date)] 正在清理数据库旧备份历史记录..."
    local backup_history_retention_days=30
    local deleted_backup_history=$(python3 /app/backup_logger.py clear --days $backup_history_retention_days 2>/dev/null || echo 0)
    log_system "info" "cleanup" "清理备份历史完成" "删除了 ${deleted_backup_history} 条备份历史记录，保留最近 ${backup_history_retention_days} 天"
}

# --- 主逻辑 ---
main() {
    echo "[$(date)] 开始备份任务..."

    DB_TYPE_TO_BACKUP=$1
    # 第二个参数是触发类型。如果未提供，则默认为"手动"。
    local trigger_type=${2:-"手动"}
    # 第三个参数是单个数据库ID（可选）
    local db_id=${3:-}

    # 根据传入的参数决定备份哪个数据库
    if [ -z "$DB_TYPE_TO_BACKUP" ] || [ "$DB_TYPE_TO_BACKUP" == "postgresql" ]; then
        backup_postgresql "$trigger_type" "$db_id"
    fi

    if [ -z "$DB_TYPE_TO_BACKUP" ] || [ "$DB_TYPE_TO_BACKUP" == "mysql" ]; then
        backup_mysql "$trigger_type" "$db_id"
    fi

    # 如果是自动任务，则执行清理
    if [ "$trigger_type" == "自动" ]; then
        cleanup_old_backups
    fi

    echo "[$(date)] 所有任务成功完成."
}

main "$@"
