# 数据库自动迁移功能说明

## 概述

从 v2.2.0 开始，数据库备份管理器添加了自动数据库完整性检查和修复功能。该功能确保在应用启动时，所有必需的数据库表和索引都存在，如果缺失会自动创建。

## 功能特点

1. **启动时自动检查**：应用启动时自动检查数据库完整性
2. **自动修复缺失表**：如果发现表缺失，自动创建相应的表结构
3. **自动修复缺失索引**：如果发现索引缺失，自动创建相应的索引
4. **初始化默认数据**：对于新创建的表，自动插入必要的默认数据
5. **非侵入式**：已存在的表和数据不会被修改

## v2.2.0 完整表列表

以下是 v2.2.0 版本的所有必需表：

### 基础表（v2.0.0）
- `users` - 用户认证表

### 历史记录表（v2.1.0）
- `backup_history` - 备份历史记录
- `notification_history` - 通知历史记录
- `system_logs` - 系统日志

### 配置管理表（v2.2.0）
- `database_connections` - 数据库连接配置
- `backup_schedules` - 备份计划配置
- `notification_config` - 通知总配置
- `email_notification_config` - 邮件通知配置
- `wechat_notification_config` - 微信通知配置

## 使用方式

### 方式一：自动检查（推荐）

应用启动时自动执行数据库完整性检查：

```bash
python3 app.py
```

启动时会看到类似输出：

```
============================================================
应用启动 - 检查数据库完整性
============================================================
检查数据库完整性: /root/db-backup-agent/backups/users.db

✅ 数据库完整性检查完成!
  现有表: 9 个
  所有表和索引都已存在，无需创建
============================================================
```

### 方式二：手动调用

如果需要手动检查和修复数据库：

```bash
python3 migrate_db.py
```

或者使用 Python 代码：

```python
from migrate_db import ensure_v22_tables

# 执行完整性检查
ensure_v22_tables()
```

## 工作原理

### 1. 表检查

`ensure_v22_tables()` 函数会：

1. 遍历 v2.2.0 的所有必需表
2. 检查每个表是否存在
3. 对于不存在的表，使用 `CREATE TABLE IF NOT EXISTS` 创建
4. 验证表是否创建成功

### 2. 索引检查

对以下索引进行检查和创建：

- `idx_backup_db_type` - backup_history 表
- `idx_backup_status` - backup_history 表
- `idx_backup_created_at` - backup_history 表
- `idx_notification_backup_id` - notification_history 表
- `idx_system_logs_type` - system_logs 表
- `idx_system_logs_category` - system_logs 表
- `idx_system_logs_created_at` - system_logs 表

### 3. 默认数据初始化

对于新创建的表，自动插入默认数据：

- **users 表**：创建默认用户 `admin/admin123`
- **notification_config 表**：默认禁用通知，成功和失败都发送
- **email_notification_config 表**：默认禁用，空配置
- **wechat_notification_config 表**：默认禁用，发送给所有人

### 4. 输出信息

函数会输出详细的检查结果：

```
检查数据库完整性: [数据库路径]
  创建缺失的表: [表名]
  创建索引: [索引名]
  ✅ 创建默认用户: admin/admin123

✅ 数据库完整性检查完成!
  现有表: 9 个
  新建表: 2 个 - backup_history, system_logs
  新建索引: 5 个 - idx_backup_db_type, idx_backup_status, ...
```

## 适用场景

### 场景一：版本升级

从旧版本升级到 v2.2.0 时，自动创建缺失的新表：

```bash
# 直接启动应用，自动完成表创建
python3 app.py
```

### 场景二：数据库修复

如果数据库因意外原因缺少表或索引：

```python
from migrate_db import ensure_v22_tables
ensure_v22_tables()  # 自动修复
```

### 场景三：全新部署

全新部署时，自动创建完整的数据库结构：

```bash
# 第一次启动会创建所有必需的表
python3 app.py
```

## 配置

### 数据库路径

默认数据库路径在 `migrate_db.py` 中配置：

```python
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       'backups', 'another', 'users.db')
```

如需修改，请编辑此路径。

### 禁用自动检查

如果不需要启动时自动检查，可以在 `app.py` 中注释掉相关代码：

```python
if __name__ == '__main__':
    # 注释掉这部分代码
    # try:
    #     ensure_v22_tables()
    # except Exception as e:
    #     print(f"⚠️  数据库完整性检查失败: {str(e)}")

    app.run(host='0.0.0.0', port=5001, debug=True)
```

## 错误处理

### 常见错误

1. **权限错误**
   ```
   ❌ 数据库完整性检查失败: unable to open database file
   ```
   解决：检查文件权限，确保应用有读写权限

2. **磁盘空间不足**
   ```
   ❌ 数据库完整性检查失败: database disk image is malformed
   ```
   解决：检查磁盘空间，必要时清理或恢复数据库

3. **表结构错误**
   ```
   ⚠️  表已存在但结构不匹配
   ```
   解决：使用 `python3 migrate_db.py` 进行完整迁移

## 与传统迁移的区别

| 特性 | 传统迁移 (migrate_to_v2_2) | 自动完整性检查 (ensure_v22_tables) |
|------|---------------------------|----------------------------------|
| 触发时机 | 手动执行 | 应用启动时自动执行 |
| 表结构修改 | 是（删除并重建） | 否（只创建缺失） |
| 数据保留 | 尝试保留 | 完全保留 |
| 适用场景 | 版本升级 | 启动检查 |
| 执行速度 | 较慢 | 较快 |

## 最佳实践

1. **生产环境**：保留自动检查功能，确保数据库完整性
2. **开发环境**：可以手动执行迁移脚本，进行完整的版本升级
3. **定期检查**：建议定期备份数据库，防止数据丢失
4. **监控日志**：关注启动日志，确保完整性检查正常执行

## 示例代码

### 在自定义脚本中使用

```python
#!/usr/bin/env python3
"""
自定义启动脚本
"""
from migrate_db import ensure_v22_tables
from app import app

def main():
    # 检查数据库
    print("检查数据库完整性...")
    if not ensure_v22_tables():
        print("❌ 数据库检查失败")
        return

    # 启动应用
    print("✅ 数据库正常，启动应用...")
    app.run(host='0.0.0.0', port=5001, debug=True)

if __name__ == '__main__':
    main()
```

### 批量检查多个数据库

```python
from migrate_db import ensure_v22_tables
import os

# 检查多个环境
db_paths = [
    '/path/to/prod/users.db',
    '/path/to/staging/users.db',
    '/path/to/dev/users.db'
]

for db_path in db_paths:
    if os.path.exists(db_path):
        # 临时修改 DB_FILE
        import migrate_db
        migrate_db.DB_FILE = db_path
        print(f"\n检查: {db_path}")
        ensure_v22_tables()
```

## 总结

自动数据库完整性检查功能确保了：

✅ 应用启动时数据库总是完整的
✅ 缺失的表和索引能自动恢复
✅ 新版本部署时无需手动执行迁移
✅ 数据库损坏或丢失表时能自动修复

这使得应用的维护更加简单，降低了运维成本。
