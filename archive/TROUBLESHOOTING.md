# 数据库迁移问题排查指南

## 问题描述
升级 Docker 镜像后，数据库表缺失或未自动创建。

## 排查步骤

### 1. 检查容器日志

查看容器启动时的迁移日志：

```bash
docker-compose logs --tail=100 | grep -E "(迁移|migrate|表)"
```

应该看到类似输出：
```
检查数据库迁移...
============================================================
数据库备份管理器 - 数据库迁移工具
...
需要执行 1 个迁移:
  - v2.2.0
```

### 2. 验证迁移脚本存在

```bash
docker exec <container_name> ls -lh /migrate_db.py
```

应该显示文件存在且大小约 19KB。

### 3. 手动运行迁移

```bash
docker exec <container_name> python3 /migrate_db.py
```

### 4. 检查数据库表

```bash
docker exec <container_name> python3 -c "
import sqlite3
conn = sqlite3.connect('/backups/users.db')
cursor = conn.cursor()
cursor.execute(\"SELECT name FROM sqlite_master WHERE type='table'\")
tables = [row[0] for row in cursor.fetchall()]
print('数据库表:', tables)
conn.close()
"
```

期望输出应包含所有 v2.2.0 的表：
- users
- backup_history
- notification_history
- system_logs
- database_connections
- backup_schedules
- notification_config
- email_notification_config
- wechat_notification_config

### 5. 检查 entrypoint.sh

确认 entrypoint.sh 包含迁移调用：

```bash
docker exec <container_name> cat /usr/local/bin/entrypoint.sh | grep -A 5 "检查数据库迁移"
```

应该看到：
```bash
# 2. 检查并执行数据库迁移
echo "检查数据库迁移..."
if [ -f "/migrate_db.py" ]; then
    python3 /migrate_db.py
else
    echo "未找到迁移脚本，跳过迁移"
fi
```

## 常见问题和解决方案

### 问题 1: 旧镜像缓存

**症状**: 迁移脚本没执行，表缺失

**原因**: Docker 使用了旧的镜像层缓存

**解决方案**:
```bash
# 1. 完全删除容器和镜像
docker-compose down
docker rmi <image_name>

# 2. 重新构建镜像（不使用缓存）
docker build --no-cache -t <image_name> .

# 3. 重新启动容器
docker-compose up -d
```

### 问题 2: 数据库文件权限问题

**症状**: 迁移脚本报错 "Permission denied"

**解决方案**:
```bash
docker exec <container_name> chmod 644 /backups/users.db
docker exec <container_name> chown root:root /backups/users.db
```

### 问题 3: 数据库文件损坏

**症状**: 迁移脚本无法读取数据库

**解决方案**:
```bash
# 备份旧数据库
docker exec <container_name> cp /backups/users.db /backups/users.db.corrupted

# 删除旧数据库
docker exec <container_name> rm /backups/users.db

# 重启容器（会自动创建新数据库）
docker-compose restart
```

### 问题 4: 迁移脚本执行失败

**症状**: 日志显示迁移脚本执行但表未创建

**解决方案**: 查看详细错误信息
```bash
docker exec <container_name> python3 /migrate_db.py 2>&1 | tee /tmp/migrate.log
```

### 问题 5: 数据库版本检测错误

**症状**: 检测到是 v2.2.0 但实际表结构不对

**解决方案**: 强制重新迁移
```bash
docker exec <container_name> python3 << 'EOF'
import sqlite3
conn = sqlite3.connect('/backups/users.db')
cursor = conn.cursor()

# 删除所有 v2.2.0 的表（除了 users）
tables_to_drop = [
    'database_connections', 'backup_schedules', 'notification_config',
    'email_notification_config', 'wechat_notification_config',
    'backup_history', 'notification_history', 'system_logs'
]

for table in tables_to_drop:
    try:
        cursor.execute(f"DROP TABLE IF EXISTS {table}")
        print(f"已删除表: {table}")
    except Exception as e:
        print(f"删除表 {table} 失败: {e}")

conn.commit()
conn.close()
print("旧表已清理，请重启容器")
EOF

docker-compose restart
```

## 手动修复数据库

如果自动迁移失败，可以手动创建缺失的表：

```bash
docker exec <container_name> python3 << 'EOF'
import sqlite3

conn = sqlite3.connect('/backups/users.db')
cursor = conn.cursor()

# 创建缺失的表（根据实际情况调整）
cursor.execute('''
    CREATE TABLE IF NOT EXISTS database_connections (
        id TEXT PRIMARY KEY,
        db_type TEXT NOT NULL,
        host TEXT NOT NULL,
        port TEXT NOT NULL,
        user TEXT NOT NULL,
        password TEXT NOT NULL,
        db_name TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')

cursor.execute('''
    CREATE TABLE IF NOT EXISTS backup_schedules (
        db_type TEXT PRIMARY KEY,
        schedule_type TEXT NOT NULL,
        cron_expression TEXT,
        retention_days INTEGER DEFAULT 7,
        enabled BOOLEAN DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')

cursor.execute('''
    CREATE TABLE IF NOT EXISTS notification_config (
        id INTEGER PRIMARY KEY,
        enabled BOOLEAN DEFAULT 0,
        on_success BOOLEAN DEFAULT 1,
        on_failure BOOLEAN DEFAULT 1,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')

# 插入默认配置
cursor.execute("INSERT OR IGNORE INTO notification_config (enabled, on_success, on_failure) VALUES (0, 1, 1)")

conn.commit()
conn.close()
print("手动创建表完成")
EOF
```

## 完全重置数据库

如果所有方法都失败，可以完全重置数据库：

```bash
# 1. 停止容器
docker-compose down

# 2. 备份旧数据库（可选）
mv backups/users.db backups/users.db.old

# 3. 启动容器（会自动创建新的数据库）
docker-compose up -d

# 4. 查看日志确认初始化成功
docker-compose logs --tail=50
```

## 联系支持

如果以上方法都无法解决问题，请提供以下信息：

1. Docker 镜像版本标签
2. 容器启动日志（docker-compose logs）
3. 数据库表列表（运行诊断脚本）
4. 迁移脚本执行结果（手动运行 migrate_db.py 的输出）
