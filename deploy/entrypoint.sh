#!/bin/sh
set -e
# /data 可能是空卷挂载 —— 确保子目录存在
mkdir -p /data/sqlite /data/redis /data/backups /data/logs /data/keys
exec supervisord -n -c /etc/supervisor/supervisord.conf
