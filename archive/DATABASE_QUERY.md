# 数据库查询指南

## users.db 数据库结构

### 位置
- 容器内: `/backups/users.db`

### 数据库表

| 表名 | 说明 | 记录数 |
|------|------|--------|
| `users` | 用户表 | 1 |
| `backup_history` | 备份历史记录 | 0 |
| `database_connections` | 数据库连接配置 | 0 |
| `backup_schedules` | 备份计划配置 | 0 |
| `notification_config` | 通知总配置 | 1 |
| `email_notification_config` | 邮件通知配置 | 1 |
| `wechat_notification_config` | 企业微信通知配置 | 1 |

## 查询方法

### 方法 1: 使用 Docker exec（推荐）

```bash
# 查看所有表
docker exec db-backup-test python3 -c "
import sqlite3
conn = sqlite3.connect('/backups/users.db')
cursor = conn.cursor()
cursor.execute(\"SELECT name FROM sqlite_master WHERE type='table'\")
for t in cursor.fetchall():
    print(t[0])
conn.close()
"

# 查看用户表
docker exec db-backup-test python3 -c "
import sqlite3
conn = sqlite3.connect('/backups/users.db')
cursor = conn.cursor()
cursor.execute('SELECT * FROM users')
for row in cursor.fetchall():
    print(row)
conn.close()
"

# 查看备份历史
docker exec db-backup-test python3 -c "
import sqlite3
conn = sqlite3.connect('/backups/users.db')
cursor = conn.cursor()
cursor.execute('SELECT COUNT(*) FROM backup_history')
print('总记录数:', cursor.fetchone()[0])
conn.close()
"
```

### 方法 2: 使用查询脚本

```bash
# 运行查询脚本
bash /root/db-backup-agent/query_db.sh
```

### 方法 3: 进入容器交互式查询

```bash
# 进入容器
docker exec -it db-backup-test bash

# 启动 Python
python3

# 执行查询
import sqlite3
conn = sqlite3.connect('/backups/users.db')
cursor = conn.cursor()

# 查询示例
cursor.execute("SELECT * FROM users")
print(cursor.fetchall())

conn.close()
exit()  # 退出 Python
exit()  # 退出容器
```

## 常用查询语句

### 查看所有表
```sql
SELECT name FROM sqlite_master WHERE type='table';
```

### 查看表结构
```sql
PRAGMA table_info(users);
PRAGMA table_info(backup_history);
```

### 查看用户
```sql
SELECT id, username, created_at FROM users;
```

### 查看备份历史
```sql
-- 所有记录
SELECT * FROM backup_history;

-- 最近10条
SELECT * FROM backup_history ORDER BY created_at DESC LIMIT 10;

-- 按状态统计
SELECT status, COUNT(*) as count
FROM backup_history
GROUP BY status;
```

### 查看数据库连接
```sql
SELECT * FROM database_connections;
```

### 查看通知配置
```sql
-- 总配置
SELECT * FROM notification_config;

-- 邮件配置
SELECT * FROM email_notification_config;

-- 企业微信配置
SELECT * FROM wechat_notification_config;
```

## backup_history 表结构

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| db_type | TEXT | 数据库类型 (PostgreSQL/MySQL) |
| db_name | TEXT | 数据库名称 |
| trigger_type | TEXT | 触发类型 (自动/手动) |
| status | TEXT | 状态 (成功/失败/跳过) |
| message | TEXT | 消息说明 |
| backup_file | TEXT | 备份文件名 |
| file_size | INTEGER | 文件大小（字节） |
| duration | REAL | 耗时（秒） |
| log_file | TEXT | 详细日志文件路径 |
| created_at | TIMESTAMP | 创建时间 |

## 注意事项

1. **数据持久化**: `/backups` 目录挂载到宿主机，数据会保留
2. **备份前先停止**: 修改数据库前建议先停止容器
3. **权限**: 容器内的数据库文件权限为 644
4. **索引**: backup_history 表有多个索引提高查询性能
