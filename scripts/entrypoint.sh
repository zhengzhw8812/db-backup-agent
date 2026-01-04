#!/bin/bash

CONFIG_FILE="/backups/config.json"

# 函数：从 config.json 更新 crontab
update_cron_from_config() {
    echo "正在从配置文件更新 cron 计划..."
    CRON_FILE="/etc/cron.d/backup-cron"

    # 1. 创建一个干净的 crontab 文件并设置头部
    echo "SHELL=/bin/bash" > "$CRON_FILE"
    echo "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" >> "$CRON_FILE"

    # 2. 检查配置文件是否存在
    if [ ! -f "$CONFIG_FILE" ]; then
        echo "配置文件 $CONFIG_FILE 未找到。不设置任何 cron 任务。"
    else
        # 3. 为 PostgreSQL 设置 cron 任务
        pg_schedule=$(jq -r '.schedules.postgresql // "disabled"' "$CONFIG_FILE")
        if [ "$pg_schedule" != "disabled" ] && [ -n "$pg_schedule" ]; then
            echo "为 PostgreSQL 设置备份计划: $pg_schedule"
            echo "$pg_schedule root /usr/local/bin/backup.sh postgresql 自动 >> /var/log/cron.log 2>&1" >> "$CRON_FILE"
        else
            echo "PostgreSQL 的自动备份已禁用。"
        fi

        # 4. 为 MySQL 设置 cron 任务
        mysql_schedule=$(jq -r '.schedules.mysql // "disabled"' "$CONFIG_FILE")
        if [ "$mysql_schedule" != "disabled" ] && [ -n "$mysql_schedule" ]; then
            echo "为 MySQL 设置备份计划: $mysql_schedule"
            echo "$mysql_schedule root /usr/local/bin/backup.sh mysql 自动 >> /var/log/cron.log 2>&1" >> "$CRON_FILE"
        else
            echo "MySQL 的自动备份已禁用。"
        fi
    fi

    # 5. 设置正确的文件权限并应用 crontab
    chmod 0644 "$CRON_FILE"
    crontab "$CRON_FILE"
    echo "Cron 计划更新完成。"
}

# --- 脚本开始 ---

# 1. 初始化：将环境变量写入 /etc/environment，以便 cron 作业可以访问
printenv | grep -v "no_proxy" > /etc/environment

# 2. 从配置文件设置初始的 cron 计划
update_cron_from_config

# 3. 创建并设置 cron 日志文件
echo "确保 cron 日志文件存在..."
touch /var/log/cron.log
chmod 0644 /var/log/cron.log

# 4. 启动 cron 服务 (在后台运行)
echo "启动 cron 服务..."
cron

# 5. 启动 Flask 应用 (在前台运行，以便 Docker 日志可以捕获输出)
echo "启动 Flask Web 服务器..."
exec python3 /app.py
