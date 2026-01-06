#!/bin/bash
# 数据库迁移诊断工具

echo "========================================"
echo "数据库迁移诊断工具"
echo "========================================"
echo ""

# 检查数据库文件
echo "1. 检查数据库文件"
if [ -f "/root/db-backup-agent/backups/users.db" ]; then
    echo "✅ 数据库文件存在"
    ls -lh /root/db-backup-agent/backups/users.db
else
    echo "❌ 数据库文件不存在"
    exit 1
fi

echo ""
echo "2. 检查容器中的数据库文件"
docker exec db-backup-test ls -lh /backups/users.db

echo ""
echo "3. 检查迁移脚本"
docker exec db-backup-test ls -lh /migrate_db.py

echo ""
echo "4. 手动运行迁移脚本"
docker exec db-backup-test python3 /migrate_db.py

echo ""
echo "5. 检查数据库表结构"
docker exec db-backup-test python3 << 'EOF'
import sqlite3

conn = sqlite3.connect('/backups/users.db')
cursor = conn.cursor()

# 检查所有表
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [row[0] for row in cursor.fetchall() if row[0] != 'sqlite_sequence']

print(f"数据库表数量: {len(tables)}")
print("\n当前存在的表:")
for table in tables:
    # 检查表结构
    cursor.execute(f"PRAGMA table_info({table})")
    columns = [col[1] for col in cursor.fetchall()]
    print(f"  - {table}")
    print(f"    列: {', '.join(columns)}")

# 检查是否缺少 v2.2.0 的表
v22_required_tables = [
    'database_connections',
    'backup_schedules',
    'notification_config',
    'email_notification_config',
    'wechat_notification_config'
]

missing_tables = []
for table in v22_required_tables:
    if table not in tables:
        missing_tables.append(table)

if missing_tables:
    print(f"\n❌ 缺少 v2.2.0 的表: {', '.join(missing_tables)}")
else:
    print("\n✅ 所有 v2.2.0 表都存在")

# 检查表结构是否正确
print("\n检查表结构是否正确:")

# 检查 email_notification_config 表结构
if 'email_notification_config' in tables:
    cursor.execute("PRAGMA table_info(email_notification_config)")
    actual_cols = set([col[1] for col in cursor.fetchall()])
    expected_cols = {
        'id', 'enabled', 'smtp_server', 'smtp_port', 'use_tls',
        'username', 'password', 'from_address', 'recipients', 'updated_at'
    }

    if actual_cols == expected_cols:
        print("  ✅ email_notification_config 表结构正确")
    else:
        print("  ❌ email_notification_config 表结构不匹配")
        print(f"     期望: {expected_cols}")
        print(f"     实际: {actual_cols}")
else:
    print("  ❌ email_notification_config 表不存在")

conn.close()
EOF

echo ""
echo "========================================"
echo "诊断完成"
echo "========================================"
