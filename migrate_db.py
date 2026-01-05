#!/usr/bin/env python3
"""
数据库迁移脚本
用于更新现有的 users.db 文件，添加新表或修改现有表结构
"""

import sqlite3
import os
import sys
import hashlib
from datetime import datetime

# 数据库文件路径（可通过环境变量或命令行参数覆盖）
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backups', 'users.db')


def check_table_exists(conn, table_name):
    """检查表是否存在"""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name=?
    """, (table_name,))
    return cursor.fetchone() is not None


def get_table_columns(conn, table_name):
    """获取表的列信息"""
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = {}
    for row in cursor.fetchall():
        # row: (cid, name, type, notnull, default_value, pk)
        columns[row[1]] = {
            'type': row[2],
            'notnull': row[3],
            'default': row[4],
            'pk': row[5]
        }
    return columns


def tables_match(conn, table_name, expected_columns):
    """检查表的列是否与期望的匹配"""
    if not check_table_exists(conn, table_name):
        return False

    actual_columns = get_table_columns(conn, table_name)

    # 检查所有期望的列是否存在
    for col_name, col_info in expected_columns.items():
        if col_name not in actual_columns:
            return False

    return True


def check_index_exists(conn, index_name):
    """检查索引是否存在"""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='index' AND name=?
    """, (index_name,))
    return cursor.fetchone() is not None


def migrate_to_v2_1():
    """迁移到 v2.1.0 - 添加通知和历史记录表"""
    print(f"正在迁移数据库到 v2.1.0: {DB_FILE}")

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    try:
        # 创建备份历史表
        if not check_table_exists(conn, 'backup_history'):
            print("创建 backup_history 表...")
            cursor.execute('''
                CREATE TABLE backup_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    db_type TEXT NOT NULL,
                    db_name TEXT,
                    trigger_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT,
                    backup_file TEXT,
                    file_size INTEGER,
                    duration REAL,
                    log_file TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            print("✅ backup_history 表创建成功")
        else:
            print("ℹ️  backup_history 表已存在")

        # 创建通知历史表
        if not check_table_exists(conn, 'notification_history'):
            print("创建 notification_history 表...")
            cursor.execute('''
                CREATE TABLE notification_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    backup_history_id INTEGER,
                    notification_type TEXT,
                    status TEXT,
                    error_message TEXT,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (backup_history_id) REFERENCES backup_history(id)
                )
            ''')
            print("✅ notification_history 表创建成功")
        else:
            print("ℹ️  notification_history 表已存在")

        # 创建系统日志表
        if not check_table_exists(conn, 'system_logs'):
            print("创建 system_logs 表...")
            cursor.execute('''
                CREATE TABLE system_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    log_type TEXT NOT NULL,
                    category TEXT,
                    message TEXT,
                    details TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            print("✅ system_logs 表创建成功")
        else:
            print("ℹ️  system_logs 表已存在")

        # 创建索引
        indexes = [
            ('idx_backup_db_type', 'backup_history', 'db_type'),
            ('idx_backup_status', 'backup_history', 'status'),
            ('idx_backup_created_at', 'backup_history', 'created_at'),
            ('idx_notification_backup_id', 'notification_history', 'backup_history_id'),
            ('idx_system_logs_type', 'system_logs', 'log_type'),
            ('idx_system_logs_category', 'system_logs', 'category'),
            ('idx_system_logs_created_at', 'system_logs', 'created_at'),
        ]

        for index_name, table_name, column in indexes:
            if not check_index_exists(conn, index_name):
                print(f"创建索引 {index_name}...")
                cursor.execute(f'CREATE INDEX {index_name} ON {table_name}({column})')
                print(f"✅ 索引 {index_name} 创建成功")
            else:
                print(f"ℹ️  索引 {index_name} 已存在")

        conn.commit()
        print("\n✅ 数据库迁移到 v2.1.0 完成!")
        return True

    except Exception as e:
        print(f"\n❌ 迁移失败: {str(e)}")
        conn.rollback()
        return False
    finally:
        conn.close()


def ensure_v22_tables():
    """确保 v2.2.0 所有必需的表都存在（启动时调用）"""
    print(f"检查数据库完整性: {DB_FILE}")

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # 定义 v2.2.0 所有必需的表及其期望的列
    v22_tables = {
        'users': {
            'columns': ['id', 'username', 'password', 'created_at'],
            'sql': '''
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            '''
        },
        'backup_history': {
            'columns': ['id', 'db_type', 'db_name', 'trigger_type', 'status', 'message',
                       'backup_file', 'file_size', 'duration', 'log_file', 'created_at'],
            'sql': '''
                CREATE TABLE backup_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    db_type TEXT NOT NULL,
                    db_name TEXT,
                    trigger_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT,
                    backup_file TEXT,
                    file_size INTEGER,
                    duration REAL,
                    log_file TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            '''
        },
        'notification_history': {
            'columns': ['id', 'backup_history_id', 'notification_type', 'status',
                       'error_message', 'sent_at'],
            'sql': '''
                CREATE TABLE notification_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    backup_history_id INTEGER,
                    notification_type TEXT,
                    status TEXT,
                    error_message TEXT,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (backup_history_id) REFERENCES backup_history(id)
                )
            '''
        },
        'system_logs': {
            'columns': ['id', 'log_type', 'category', 'message', 'details', 'created_at'],
            'sql': '''
                CREATE TABLE system_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    log_type TEXT NOT NULL,
                    category TEXT,
                    message TEXT,
                    details TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            '''
        },
        'database_connections': {
            'columns': ['id', 'db_type', 'host', 'port', 'user', 'password',
                       'db_name', 'created_at', 'updated_at'],
            'sql': '''
                CREATE TABLE database_connections (
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
            '''
        },
        'backup_schedules': {
            'columns': ['db_type', 'schedule_type', 'cron_expression', 'retention_days',
                       'enabled', 'created_at', 'updated_at'],
            'sql': '''
                CREATE TABLE backup_schedules (
                    db_type TEXT PRIMARY KEY,
                    schedule_type TEXT NOT NULL,
                    cron_expression TEXT,
                    retention_days INTEGER DEFAULT 7,
                    enabled BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            '''
        },
        'notification_config': {
            'columns': ['id', 'enabled', 'on_success', 'on_failure', 'updated_at'],
            'sql': '''
                CREATE TABLE notification_config (
                    id INTEGER PRIMARY KEY,
                    enabled BOOLEAN DEFAULT 0,
                    on_success BOOLEAN DEFAULT 1,
                    on_failure BOOLEAN DEFAULT 1,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            '''
        },
        'email_notification_config': {
            'columns': ['id', 'enabled', 'smtp_server', 'smtp_port', 'use_tls',
                       'username', 'password', 'from_address', 'recipients', 'updated_at'],
            'sql': '''
                CREATE TABLE email_notification_config (
                    id INTEGER PRIMARY KEY,
                    enabled BOOLEAN DEFAULT 0,
                    smtp_server TEXT,
                    smtp_port INTEGER DEFAULT 587,
                    use_tls BOOLEAN DEFAULT 1,
                    username TEXT,
                    password TEXT,
                    from_address TEXT,
                    recipients TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            '''
        },
        'wechat_notification_config': {
            'columns': ['id', 'enabled', 'corp_id', 'corp_secret', 'agent_id',
                       'to_users', 'updated_at'],
            'sql': '''
                CREATE TABLE wechat_notification_config (
                    id INTEGER PRIMARY KEY,
                    enabled BOOLEAN DEFAULT 0,
                    corp_id TEXT,
                    corp_secret TEXT,
                    agent_id TEXT,
                    to_users TEXT DEFAULT '@all',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            '''
        }
    }

    # 定义所有必需的索引
    v22_indexes = [
        ('idx_backup_db_type', 'backup_history', 'db_type'),
        ('idx_backup_status', 'backup_history', 'status'),
        ('idx_backup_created_at', 'backup_history', 'created_at'),
        ('idx_notification_backup_id', 'notification_history', 'backup_history_id'),
        ('idx_system_logs_type', 'system_logs', 'log_type'),
        ('idx_system_logs_category', 'system_logs', 'category'),
        ('idx_system_logs_created_at', 'system_logs', 'created_at'),
    ]

    def check_table_structure(conn, table_name, expected_columns):
        """检查表结构是否完整"""
        if not check_table_exists(conn, table_name):
            return False

        cursor = conn.cursor()
        cursor.execute(f'PRAGMA table_info({table_name})')
        actual_columns = [row[1] for row in cursor.fetchall()]

        # 检查所有期望的列是否存在
        return all(col in actual_columns for col in expected_columns)

    try:
        missing_tables = []
        created_tables = []
        rebuilt_tables = []
        existing_tables = []

        # 检查并创建或重建表
        for table_name, table_info in v22_tables.items():
            expected_columns = table_info['columns']
            create_sql = table_info['sql']

            if not check_table_exists(conn, table_name):
                # 表不存在，创建新表
                missing_tables.append(table_name)
                print(f"  创建缺失的表: {table_name}")
                cursor.execute(create_sql)
                created_tables.append(table_name)
            elif not check_table_structure(conn, table_name, expected_columns):
                # 表存在但结构不完整，需要重建
                print(f"  ⚠️  表 {table_name} 结构不完整，正在重建...")
                # 备份数据（如果有）
                backup_data = None
                try:
                    cursor.execute(f'SELECT * FROM {table_name}')
                    backup_data = cursor.fetchall()
                    cursor.execute(f'PRAGMA table_info({table_name})')
                    columns = [row[1] for row in cursor.fetchall()]
                    print(f"    备份了 {len(backup_data)} 行数据")
                except:
                    pass

                # 删除旧表
                cursor.execute(f'DROP TABLE {table_name}')

                # 创建新表
                cursor.execute(create_sql)

                # 尝试恢复数据（如果列名匹配）
                if backup_data and len(backup_data) > 0:
                    try:
                        # 获取新表的列
                        cursor.execute(f'PRAGMA table_info({table_name})')
                        new_columns = [row[1] for row in cursor.fetchall()]

                        # 只恢复列名匹配的数据
                        cols_to_restore = [col for col in columns if col in new_columns]
                        if cols_to_restore:
                            placeholders = ','.join(['?' for _ in cols_to_restore])
                            col_names = ','.join(cols_to_restore)
                            for row in backup_data:
                                # 创建列名到值的映射
                                col_value_map = dict(zip(columns, row))
                                values = [col_value_map[col] for col in cols_to_restore]
                                cursor.execute(f'INSERT INTO {table_name} ({col_names}) VALUES ({placeholders})', values)
                            print(f"    恢复了 {len(backup_data)} 行数据")
                    except Exception as e:
                        print(f"    ⚠️  数据恢复失败: {e}")

                rebuilt_tables.append(table_name)
                print(f"  ✅ 表 {table_name} 重建完成")
            else:
                existing_tables.append(table_name)

        # 插入默认数据（如果表是新创建的）
        if 'users' in created_tables or 'users' in rebuilt_tables:
            # 创建默认用户 (密码: admin123)
            cursor.execute("SELECT COUNT(*) FROM users")
            if cursor.fetchone()[0] == 0:
                cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)",
                              ('admin', hashlib.sha256('admin123'.encode()).hexdigest()))
                print("  ✅ 创建默认用户: admin/admin123")

        if 'notification_config' in created_tables or 'notification_config' in rebuilt_tables:
            cursor.execute("SELECT COUNT(*) FROM notification_config")
            if cursor.fetchone()[0] == 0:
                cursor.execute('INSERT INTO notification_config (enabled, on_success, on_failure) VALUES (0, 1, 1)')
                print("  ✅ 创建默认通知配置")

        if 'email_notification_config' in created_tables or 'email_notification_config' in rebuilt_tables:
            cursor.execute("SELECT COUNT(*) FROM email_notification_config")
            if cursor.fetchone()[0] == 0:
                cursor.execute('INSERT INTO email_notification_config (enabled, smtp_server, smtp_port, use_tls, recipients) VALUES (0, "", 587, 1, "")')
                print("  ✅ 创建默认邮件通知配置")

        if 'wechat_notification_config' in created_tables or 'wechat_notification_config' in rebuilt_tables:
            cursor.execute("SELECT COUNT(*) FROM wechat_notification_config")
            if cursor.fetchone()[0] == 0:
                cursor.execute('INSERT INTO wechat_notification_config (enabled, to_users) VALUES (0, "@all")')
                print("  ✅ 创建默认微信通知配置")

        # 创建缺失的索引
        created_indexes = []
        for index_name, table_name, column in v22_indexes:
            if not check_index_exists(conn, index_name):
                # 确保表存在才创建索引
                if check_table_exists(conn, table_name):
                    print(f"  创建索引: {index_name}")
                    cursor.execute(f'CREATE INDEX {index_name} ON {table_name}({column})')
                    created_indexes.append(index_name)

        conn.commit()

        # 输出摘要
        print(f"\n✅ 数据库完整性检查完成!")
        print(f"  现有表: {len(existing_tables)} 个")
        if created_tables:
            print(f"  新建表: {len(created_tables)} 个 - {', '.join(created_tables)}")
        if rebuilt_tables:
            print(f"  重建表: {len(rebuilt_tables)} 个 - {', '.join(rebuilt_tables)}")
        if created_indexes:
            print(f"  新建索引: {len(created_indexes)} 个 - {', '.join(created_indexes)}")
        if not created_tables and not rebuilt_tables and not created_indexes:
            print(f"  所有表和索引都已存在且结构正确，无需修改")

        return True

    except Exception as e:
        print(f"\n❌ 数据库完整性检查失败: {str(e)}")
        import traceback
        traceback.print_exc()
        conn.rollback()
        return False
    finally:
        conn.close()


def migrate_to_v2_2():
    """迁移到 v2.2.0 - 添加配置管理表"""
    print(f"正在迁移数据库到 v2.2.0: {DB_FILE}")
    print("检查并更新表结构...")

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    try:
        # 定义 v2.2.0 期望的表结构
        v22_tables = {
            'database_connections': {
                'id': {}, 'db_type': {}, 'host': {}, 'port': {}, 'user': {},
                'password': {}, 'db_name': {}, 'created_at': {}, 'updated_at': {}
            },
            'backup_schedules': {
                'db_type': {}, 'schedule_type': {}, 'cron_expression': {},
                'retention_days': {}, 'enabled': {}, 'created_at': {}, 'updated_at': {}
            },
            'notification_config': {
                'id': {}, 'enabled': {}, 'on_success': {}, 'on_failure': {}, 'updated_at': {}
            },
            'email_notification_config': {
                'id': {}, 'enabled': {}, 'smtp_server': {}, 'smtp_port': {},
                'use_tls': {}, 'username': {}, 'password': {}, 'from_address': {},
                'recipients': {}, 'updated_at': {}
            },
            'wechat_notification_config': {
                'id': {}, 'enabled': {}, 'corp_id': {}, 'corp_secret': {},
                'agent_id': {}, 'to_users': {}, 'updated_at': {}
            }
        }

        # 处理 database_connections 表
        if not tables_match(conn, 'database_connections', v22_tables['database_connections']):
            print("检查 database_connections 表...")
            if check_table_exists(conn, 'database_connections'):
                print("  ⚠️  表结构不匹配，删除旧表并重建")
                cursor.execute("DROP TABLE database_connections")

            print("创建 database_connections 表...")
            cursor.execute('''
                CREATE TABLE database_connections (
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
            print("✅ database_connections 表创建成功")
        else:
            print("ℹ️  database_connections 表结构已正确")

        # 处理 backup_schedules 表
        if not tables_match(conn, 'backup_schedules', v22_tables['backup_schedules']):
            print("检查 backup_schedules 表...")
            if check_table_exists(conn, 'backup_schedules'):
                print("  ⚠️  表结构不匹配，删除旧表并重建")
                # 备份旧数据
                cursor.execute("CREATE TEMPORARY TABLE backup_schedules_backup AS SELECT * FROM backup_schedules")
                cursor.execute("DROP TABLE backup_schedules")

            print("创建 backup_schedules 表...")
            cursor.execute('''
                CREATE TABLE backup_schedules (
                    db_type TEXT PRIMARY KEY,
                    schedule_type TEXT NOT NULL,
                    cron_expression TEXT,
                    retention_days INTEGER DEFAULT 7,
                    enabled BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 尝试恢复旧数据（如果有的话）
            try:
                cursor.execute("SELECT COUNT(*) FROM backup_schedules_backup")
                if cursor.fetchone()[0] > 0:
                    print("  尝试恢复旧数据...")
                    cursor.execute('''
                        INSERT INTO backup_schedules (db_type, schedule_type, cron_expression, retention_days, enabled, created_at, updated_at)
                        SELECT db_type, schedule_type, cron_expression, retention_days, enabled, created_at, updated_at
                        FROM backup_schedules_backup
                    ''')
                    cursor.execute("DROP TABLE backup_schedules_backup")
                    print("  ✅ 旧数据已恢复")
            except:
                pass

            print("✅ backup_schedules 表创建成功")
        else:
            print("ℹ️  backup_schedules 表结构已正确")

        # 处理 notification_config 表
        if not tables_match(conn, 'notification_config', v22_tables['notification_config']):
            print("检查 notification_config 表...")
            if check_table_exists(conn, 'notification_config'):
                print("  ⚠️  表结构不匹配，删除旧表并重建")
                cursor.execute("DROP TABLE notification_config")

            print("创建 notification_config 表...")
            cursor.execute('''
                CREATE TABLE notification_config (
                    id INTEGER PRIMARY KEY,
                    enabled BOOLEAN DEFAULT 0,
                    on_success BOOLEAN DEFAULT 1,
                    on_failure BOOLEAN DEFAULT 1,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 插入默认配置
            cursor.execute('SELECT COUNT(*) FROM notification_config')
            if cursor.fetchone()[0] == 0:
                cursor.execute('''
                    INSERT INTO notification_config (enabled, on_success, on_failure)
                    VALUES (0, 1, 1)
                ''')
            print("✅ notification_config 表创建成功")
        else:
            print("ℹ️  notification_config 表结构已正确")

        # 处理 email_notification_config 表
        if not tables_match(conn, 'email_notification_config', v22_tables['email_notification_config']):
            print("检查 email_notification_config 表...")
            if check_table_exists(conn, 'email_notification_config'):
                print("  ⚠️  表结构不匹配，删除旧表并重建")
                cursor.execute("DROP TABLE email_notification_config")

            print("创建 email_notification_config 表...")
            cursor.execute('''
                CREATE TABLE email_notification_config (
                    id INTEGER PRIMARY KEY,
                    enabled BOOLEAN DEFAULT 0,
                    smtp_server TEXT,
                    smtp_port INTEGER DEFAULT 587,
                    use_tls BOOLEAN DEFAULT 1,
                    username TEXT,
                    password TEXT,
                    from_address TEXT,
                    recipients TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 插入默认配置
            cursor.execute('SELECT COUNT(*) FROM email_notification_config')
            if cursor.fetchone()[0] == 0:
                cursor.execute('''
                    INSERT INTO email_notification_config
                    (enabled, smtp_server, smtp_port, use_tls, recipients)
                    VALUES (0, '', 587, 1, '')
                ''')
            print("✅ email_notification_config 表创建成功")
        else:
            print("ℹ️  email_notification_config 表结构已正确")

        # 处理 wechat_notification_config 表
        if not tables_match(conn, 'wechat_notification_config', v22_tables['wechat_notification_config']):
            print("检查 wechat_notification_config 表...")
            if check_table_exists(conn, 'wechat_notification_config'):
                print("  ⚠️  表结构不匹配，删除旧表并重建")
                cursor.execute("DROP TABLE wechat_notification_config")

            print("创建 wechat_notification_config 表...")
            cursor.execute('''
                CREATE TABLE wechat_notification_config (
                    id INTEGER PRIMARY KEY,
                    enabled BOOLEAN DEFAULT 0,
                    corp_id TEXT,
                    corp_secret TEXT,
                    agent_id TEXT,
                    to_users TEXT DEFAULT '@all',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 插入默认配置
            cursor.execute('SELECT COUNT(*) FROM wechat_notification_config')
            if cursor.fetchone()[0] == 0:
                cursor.execute('''
                    INSERT INTO wechat_notification_config
                    (enabled, to_users)
                    VALUES (0, '@all')
                ''')
            print("✅ wechat_notification_config 表创建成功")
        else:
            print("ℹ️  wechat_notification_config 表结构已正确")

        conn.commit()
        print("\n✅ 数据库迁移到 v2.2.0 完成!")
        return True

    except Exception as e:
        print(f"\n❌ 迁移失败: {str(e)}")
        conn.rollback()
        return False
    finally:
        conn.close()


def get_current_version():
    """获取当前数据库版本"""
    if not os.path.exists(DB_FILE):
        return None

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # 定义 v2.2.0 期望的表结构
    v22_email_cols = {
        'id', 'enabled', 'smtp_server', 'smtp_port', 'use_tls',
        'username', 'password', 'from_address', 'recipients', 'updated_at'
    }

    # 通过检查表和表结构来判断版本
    if check_table_exists(conn, 'wechat_notification_config'):
        # 进一步检查 v2.2.0 的表结构是否正确
        if check_table_exists(conn, 'email_notification_config'):
            actual_cols = set(get_table_columns(conn, 'email_notification_config').keys())
            if actual_cols == v22_email_cols:
                version = "2.2.0"
            else:
                # 表存在但结构不对，需要迁移
                version = "2.1.0"
        else:
            version = "2.2.0"
    elif check_table_exists(conn, 'backup_history'):
        version = "2.1.0"
    elif check_table_exists(conn, 'users'):
        version = "2.0.0"
    else:
        version = "未初始化"

    conn.close()
    return version


def init_v20_database():
    """初始化 v2.0.0 版本数据库（基础表结构）"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    try:
        # 创建用户表
        cursor.execute('''
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # 创建默认用户 (密码: admin123)
        cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)",
                      ('admin', hashlib.sha256('admin123'.encode()).hexdigest()))

        conn.commit()
        print("✅ v2.0.0 基础表创建成功")
        return True
    except Exception as e:
        conn.rollback()
        print(f"❌ v2.0.0 基础表创建失败: {str(e)}")
        return False
    finally:
        conn.close()


def main(use_auto_ensure=False):
    """主函数

    Args:
        use_auto_ensure: 是否使用自动完整性检查模式（启动时调用）
    """
    print("=" * 60)
    print("数据库备份管理器 - 数据库迁移工具")
    print("=" * 60)
    print(f"\n数据库文件: {DB_FILE}")

    # 如果数据库文件不存在，先创建基础结构
    if not os.path.exists(DB_FILE):
        print("\n数据库文件不存在，创建新数据库...")
        if not init_v20_database():
            print("\n❌ 数据库初始化失败")
            return
        print("✅ 数据库初始化完成")

    # 如果是自动模式，直接确保所有表存在
    if use_auto_ensure:
        print("\n" + "=" * 60)
        ensure_v22_tables()
        print("=" * 60)
        return

    # 获取当前版本
    current_version = get_current_version()
    print(f"当前版本: {current_version}")

    # 根据当前版本决定需要执行的迁移
    migrations = []

    # 从未初始化（只有 users 表）开始
    if current_version == "未初始化":
        migrations.append(("2.1.0", migrate_to_v2_1))
        migrations.append(("2.2.0", migrate_to_v2_2))
    # 从 v2.0.0 开始
    elif current_version == "2.0.0":
        migrations.append(("2.1.0", migrate_to_v2_1))
        migrations.append(("2.2.0", migrate_to_v2_2))
    # 从 v2.1.0 开始
    elif current_version == "2.1.0":
        migrations.append(("2.2.0", migrate_to_v2_2))
    # 从 v2.2.0 开始 - 仍然需要执行表结构比对
    elif current_version == "2.2.0":
        migrations.append(("2.2.0", migrate_to_v2_2))

    if not migrations:
        print("\n✅ 数据库已是最新版本，无需迁移")
        return

    # 执行迁移
    print(f"\n需要执行 {len(migrations)} 个迁移:")
    for version, _ in migrations:
        print(f"  - v{version}")

    print("\n开始迁移...\n")

    success_count = 0
    for version, migrate_func in migrations:
        print(f"\n{'=' * 60}")
        if migrate_func():
            success_count += 1
        else:
            print(f"\n❌ 迁移到 v{version} 失败，已停止后续迁移")
            break

    print(f"\n{'=' * 60}")
    print(f"\n迁移完成! 成功: {success_count}/{len(migrations)}")
    print(f"最新版本: {get_current_version()}")


if __name__ == '__main__':
    main()
