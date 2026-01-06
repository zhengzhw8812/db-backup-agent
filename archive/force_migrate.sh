#!/bin/bash
# 数据库强制迁移工具
# 用于手动修复数据库表缺失问题

echo "========================================"
echo "数据库强制迁移工具"
echo "========================================"
echo ""

# 检查容器是否运行
if ! docker exec db-backup-test echo "OK" &>/dev/null; then
    echo "容器未运行，请先启动容器"
    exit 1
fi

echo "1. 停止 Flask 应用（避免数据库锁定）"
docker exec db-backup-test pkill -f "python3 /app.py" || true

echo ""
echo "2. 备份当前数据库"
docker exec db-backup-test cp /backups/users.db /backups/users.db.backup_$(date +%Y%m%d_%H%M%S)
echo "✅ 数据库已备份"

echo ""
echo "3. 检查当前数据库版本和表"
docker exec db-backup-test python3 << 'EOF'
import sqlite3

conn = sqlite3.connect('/backups/users.db')
cursor = conn.cursor()

# 获取所有表
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [row[0] for row in cursor.fetchall()]

print(f"当前数据库表数量: {len(tables)}")
for t in tables:
    if t != 'sqlite_sequence':
        cursor.execute(f"SELECT COUNT(*) FROM {t}")
        count = cursor.fetchone()[0]
        print(f"  - {t}: {count} 条")

# 检查 v2.2.0 必需的表
v22_tables = [
    'users',
    'backup_history',
    'notification_history',
    'system_logs',
    'database_connections',
    'backup_schedules',
    'notification_config',
    'email_notification_config',
    'wechat_notification_config'
]

missing = [t for t in v22_tables if t not in tables]
if missing:
    print(f"\n❌ 缺少 v2.2.0 必需的表: {', '.join(missing)}")
else:
    print("\n✅ 所有 v2.2.0 表都存在")

conn.close()
EOF

echo ""
echo "4. 执行数据库迁移"
docker exec db-backup-test python3 /migrate_db.py

echo ""
echo "5. 验证迁移结果"
docker exec db-backup-test python3 << 'EOF'
import sqlite3

conn = sqlite3.connect('/backups/users.db')
cursor = conn.cursor()

# 获取所有表
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [row[0] for row in cursor.fetchall()]

print(f"迁移后数据库表数量: {len(tables)}")

v22_tables = [
    'database_connections',
    'backup_schedules',
    'notification_config',
    'email_notification_config',
    'wechat_notification_config'
]

missing = [t for t in v22_tables if t not in tables]
if missing:
    print(f"\n❌ 仍然缺少表: {', '.join(missing)}")
    print("\n尝试手动创建缺失的表...")
else:
    print("\n✅ 所有 v2.2.0 表都已正确创建")

conn.close()
EOF

echo ""
echo "6. 重启容器"
echo "请运行以下命令重启容器:"
echo "  docker-compose restart"
echo ""
echo "或者:"
echo "  docker-compose down"
echo "  docker-compose up -d"

echo ""
echo "========================================"
echo "强制迁移完成"
echo "========================================"
