#!/usr/bin/env bash
set -euo pipefail

mkdir -p /data/sqlite /data/redis /data/logs /data/backups

# 加载 .env(若存在)
if [ -f /app/.env ]; then export $(grep -v '^#' /app/.env | xargs); fi

: "${APP_DATA_DIR:=/data}"
: "${APP_PORT:=5001}"
export APP_DATA_DIR APP_PORT

exec supervisord -c /app/deploy/supervisord.conf
