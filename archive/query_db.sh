#!/bin/bash
# 数据库查询工具
# 用于快速查看 users.db 的内容

DB_FILE="/root/db-backup-agent/backups/users.db"

if [ ! -f "$DB_FILE" ]; then
    echo "错误: 数据库文件不存在: $DB_FILE"
    exit 1
fi

docker exec db-backup-test python3 << EOF
import sqlite3
from datetime import datetime

conn = sqlite3.connect('/backups/users.db')
cursor = conn.cursor()

print("=" * 70)
print("数据库备份管理器 - users.db 查询结果")
print("=" * 70)
print(f"数据库文件: /backups/users.db")
print(f"查询时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 70)

# 1. 查看所有表
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [row[0] for row in cursor.fetchall() if row[0] != 'sqlite_sequence']
print(f"\n【数据库表】共 {len(tables)} 个表")
for table in tables:
    cursor.execute(f"SELECT COUNT(*) FROM {table}")
    count = cursor.fetchone()[0]
    print(f"  ✓ {table:<30} ({count} 条记录)")

# 2. 用户表
print("\n" + "=" * 70)
print("【用户列表】")
print("=" * 70)
cursor.execute("SELECT id, username, created_at FROM users ORDER BY id")
users = cursor.fetchall()
if users:
    print(f"{'ID':<5} {'用户名':<15} {'创建时间':<20}")
    print("-" * 70)
    for user in users:
        print(f"{user[0]:<5} {user[1]:<15} {user[2]}")
else:
    print("  (无用户)")

# 3. 数据库连接
print("\n" + "=" * 70)
print("【数据库连接配置】")
print("=" * 70)
cursor.execute("SELECT COUNT(*) FROM database_connections")
db_count = cursor.fetchone()[0]
if db_count > 0:
    cursor.execute("""
        SELECT id, db_type, host, port, user, db_name
        FROM database_connections
    """)
    print(f"{'ID':<36} {'类型':<12} {'地址':<20} {'数据库':<15}")
    print("-" * 70)
    for row in cursor.fetchall():
        db_name = row[5] if row[5] else "所有数据库"
        print(f"{row[0]:<36} {row[1]:<12} {row[2]}:{row[3]:<15} {db_name:<15}")
else:
    print("  (暂无数据库连接配置)")

# 4. 备份历史
print("\n" + "=" * 70)
print("【备份历史】")
print("=" * 70)
cursor.execute("SELECT COUNT(*) FROM backup_history")
total = cursor.fetchone()[0]

if total > 0:
    # 统计信息
    cursor.execute("""
        SELECT
            db_type,
            COUNT(*) as total,
            SUM(CASE WHEN status = '成功' THEN 1 ELSE 0 END) as success,
            SUM(CASE WHEN status = '失败' THEN 1 ELSE 0 END) as failed
        FROM backup_history
        GROUP BY db_type
    """)
    print("按数据库类型统计:")
    for row in cursor.fetchall():
        print(f"  {row[0]:<10} 总计: {row[1]:>3}, 成功: {row[2]:>3}, 失败: {row[3]:>3}")

    # 最近10条记录
    print("\n最近10条备份记录:")
    cursor.execute("""
        SELECT db_type, db_name, trigger_type, status,
               backup_file, file_size, duration, created_at
        FROM backup_history
        ORDER BY created_at DESC
        LIMIT 10
    """)

    print(f"{'时间':<20} {'类型':<10} {'数据库':<15} {'触发':<6} {'状态':<6} {'文件大小':<10}")
    print("-" * 70)

    for row in cursor.fetchall():
        db_name = row[1] if row[1] else "所有数据库"
        size = f"{row[5]/1024/1024:.2f}MB" if row[5] else "N/A"
        duration = f"{row[6]:.1f}s" if row[6] else "N/A"
        time = row[7][:19] if row[7] else "N/A"

        print(f"{time:<20} {row[0]:<10} {db_name:<15} {row[2]:<6} {row[3]:<6} {size:<10}")
else:
    print("  (暂无备份记录)")

# 5. 通知配置
print("\n" + "=" * 70)
print("【通知配置】")
print("=" * 70)

cursor.execute("SELECT enabled, on_success, on_failure FROM notification_config")
notif = cursor.fetchone()
if notif:
    status = "启用" if notif[0] else "禁用"
    print(f"通知状态: {status}")
    print(f"  成功时通知: {'是' if notif[1] else '否'}")
    print(f"  失败时通知: {'是' if notif[2] else '否'}")

cursor.execute("SELECT enabled FROM email_notification_config")
email = cursor.fetchone()
if email:
    print(f"\n邮件通知: {'启用' if email[0] else '禁用'}")

cursor.execute("SELECT enabled FROM wechat_notification_config")
wechat = cursor.fetchone()
if wechat:
    print(f"企业微信通知: {'启用' if wechat[0] else '禁用'}")

print("\n" + "=" * 70)
print("查询完成")
print("=" * 70)

conn.close()
EOF
