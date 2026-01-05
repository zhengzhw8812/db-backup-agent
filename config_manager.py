#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置管理模块
使用 SQLite 存储和管理所有配置，包括数据库连接、备份计划、通知设置等
"""

import os
import sys
import sqlite3
import json
import uuid
from datetime import datetime

# 数据库文件路径
DB_FILE = "/backups/users.db"


def get_db_connection():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_config_tables():
    """初始化配置表"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 数据库连接配置表
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

    # 备份计划配置表
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

    # 通知配置表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notification_config (
            id INTEGER PRIMARY KEY,
            enabled BOOLEAN DEFAULT 0,
            on_success BOOLEAN DEFAULT 1,
            on_failure BOOLEAN DEFAULT 1,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 邮件通知配置表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS email_notification_config (
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

    # 企业微信通知配置表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS wechat_notification_config (
            id INTEGER PRIMARY KEY,
            enabled BOOLEAN DEFAULT 0,
            corp_id TEXT,
            corp_secret TEXT,
            agent_id TEXT,
            to_users TEXT DEFAULT '@all',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 插入默认通知配置（如果不存在）
    cursor.execute('SELECT COUNT(*) as count FROM notification_config')
    if cursor.fetchone()['count'] == 0:
        cursor.execute('INSERT INTO notification_config (enabled, on_success, on_failure) VALUES (0, 1, 1)')

    cursor.execute('SELECT COUNT(*) as count FROM email_notification_config')
    if cursor.fetchone()['count'] == 0:
        cursor.execute('''
            INSERT INTO email_notification_config
            (enabled, smtp_server, smtp_port, use_tls, recipients)
            VALUES (0, '', 587, 1, '')
        ''')

    cursor.execute('SELECT COUNT(*) as count FROM wechat_notification_config')
    if cursor.fetchone()['count'] == 0:
        cursor.execute('''
            INSERT INTO wechat_notification_config
            (enabled, to_users)
            VALUES (0, '@all')
        ''')

    conn.commit()
    conn.close()
    print("配置表初始化完成")


# ===== 数据库连接管理 =====

def add_database_connection(db_type, host, port, user, password, db_name):
    """添加数据库连接"""
    conn = get_db_connection()
    cursor = conn.cursor()

    conn_id = str(uuid.uuid4())
    cursor.execute('''
        INSERT INTO database_connections (id, db_type, host, port, user, password, db_name)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (conn_id, db_type, host, port, user, password, db_name))

    conn.commit()
    conn.close()
    return conn_id


def update_database_connection(conn_id, db_type, host, port, user, password, db_name):
    """更新数据库连接"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        UPDATE database_connections
        SET db_type=?, host=?, port=?, user=?, password=?, db_name=?, updated_at=?
        WHERE id=?
    ''', (db_type, host, port, user, password, db_name, datetime.now(), conn_id))

    conn.commit()
    conn.close()


def delete_database_connection(conn_id):
    """删除数据库连接"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('DELETE FROM database_connections WHERE id=?', (conn_id,))

    conn.commit()
    conn.close()


def get_database_connections(db_type=None):
    """获取数据库连接列表"""
    conn = get_db_connection()
    cursor = conn.cursor()

    if db_type:
        cursor.execute('SELECT * FROM database_connections WHERE db_type=? ORDER BY created_at DESC', (db_type,))
    else:
        cursor.execute('SELECT * FROM database_connections ORDER BY created_at DESC')

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def get_database_connection(conn_id):
    """获取单个数据库连接"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM database_connections WHERE id=?', (conn_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
        return dict(row)
    return None


# ===== 备份计划管理 =====

def save_backup_schedule(db_type, schedule_type, cron_expression, retention_days):
    """保存备份计划"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        INSERT OR REPLACE INTO backup_schedules
        (db_type, schedule_type, cron_expression, retention_days, updated_at)
        VALUES (?, ?, ?, ?, ?)
    ''', (db_type, schedule_type, cron_expression, retention_days, datetime.now()))

    conn.commit()
    conn.close()


def get_backup_schedules():
    """获取所有备份计划"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM backup_schedules')
    rows = cursor.fetchall()
    conn.close()

    return {row['db_type']: dict(row) for row in rows}


def get_backup_schedule(db_type):
    """获取指定数据库类型的备份计划"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM backup_schedules WHERE db_type=?', (db_type,))
    row = cursor.fetchone()
    conn.close()

    if row:
        return dict(row)
    return None


# ===== 通知配置管理 =====

def get_notification_config():
    """获取通知配置"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 获取主配置
    cursor.execute('SELECT * FROM notification_config ORDER BY id DESC LIMIT 1')
    main_row = cursor.fetchone()
    main_config = dict(main_row) if main_row else {}

    # 获取邮件配置
    cursor.execute('SELECT * FROM email_notification_config ORDER BY id DESC LIMIT 1')
    email_row = cursor.fetchone()
    email_config = dict(email_row) if email_row else {}

    # 获取企业微信配置
    cursor.execute('SELECT * FROM wechat_notification_config ORDER BY id DESC LIMIT 1')
    wechat_row = cursor.fetchone()
    wechat_config = dict(wechat_row) if wechat_row else {}

    conn.close()

    return {
        'enabled': bool(main_config.get('enabled', 0)),
        'on_success': bool(main_config.get('on_success', 1)),
        'on_failure': bool(main_config.get('on_failure', 1)),
        'email': {
            'enabled': bool(email_config.get('enabled', 0)),
            'smtp_server': email_config.get('smtp_server', ''),
            'smtp_port': email_config.get('smtp_port', 587),
            'use_tls': bool(email_config.get('use_tls', 1)),
            'username': email_config.get('username', ''),
            'password': email_config.get('password', ''),
            'from_address': email_config.get('from_address', ''),
            'recipients': email_config.get('recipients', '').split(',') if email_config.get('recipients') else []
        },
        'wechat': {
            'enabled': bool(wechat_config.get('enabled', 0)),
            'corp_id': wechat_config.get('corp_id', ''),
            'corp_secret': wechat_config.get('corp_secret', ''),
            'agent_id': wechat_config.get('agent_id', ''),
            'to_users': wechat_config.get('to_users', '@all')
        }
    }


def save_notification_config(enabled, on_success, on_failure, email_config, wechat_config):
    """保存通知配置"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 更新主配置
    cursor.execute('''
        UPDATE notification_config
        SET enabled=?, on_success=?, on_failure=?, updated_at=?
        WHERE id=1
    ''', (1 if enabled else 0, 1 if on_success else 0, 1 if on_failure else 0, datetime.now()))

    # 更新邮件配置
    cursor.execute('''
        UPDATE email_notification_config
        SET enabled=?, smtp_server=?, smtp_port=?, use_tls=?,
            username=?, password=?, from_address=?, recipients=?, updated_at=?
        WHERE id=1
    ''', (
        1 if email_config.get('enabled', False) else 0,
        email_config.get('smtp_server', ''),
        email_config.get('smtp_port', 587),
        1 if email_config.get('use_tls', True) else 0,
        email_config.get('username', ''),
        email_config.get('password', ''),
        email_config.get('from_address', ''),
        ','.join(email_config.get('recipients', [])),
        datetime.now()
    ))

    # 更新企业微信配置
    cursor.execute('''
        UPDATE wechat_notification_config
        SET enabled=?, corp_id=?, corp_secret=?, agent_id=?, to_users=?, updated_at=?
        WHERE id=1
    ''', (
        1 if wechat_config.get('enabled', False) else 0,
        wechat_config.get('corp_id', ''),
        wechat_config.get('corp_secret', ''),
        wechat_config.get('agent_id', ''),
        wechat_config.get('to_users', '@all'),
        datetime.now()
    ))

    conn.commit()
    conn.close()


def save_global_notification_config(enabled, on_success, on_failure):
    """单独保存全局通知配置"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        UPDATE notification_config
        SET enabled=?, on_success=?, on_failure=?, updated_at=?
        WHERE id=1
    ''', (1 if enabled else 0, 1 if on_success else 0, 1 if on_failure else 0, datetime.now()))

    conn.commit()
    conn.close()


def save_email_notification_config(email_config):
    """单独保存邮件通知配置"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        UPDATE email_notification_config
        SET enabled=?, smtp_server=?, smtp_port=?, use_tls=?,
            username=?, password=?, from_address=?, recipients=?, updated_at=?
        WHERE id=1
    ''', (
        1 if email_config.get('enabled', False) else 0,
        email_config.get('smtp_server', ''),
        email_config.get('smtp_port', 587),
        1 if email_config.get('use_tls', True) else 0,
        email_config.get('username', ''),
        email_config.get('password', ''),
        email_config.get('from_address', ''),
        ','.join(email_config.get('recipients', [])),
        datetime.now()
    ))

    conn.commit()
    conn.close()


def save_wechat_notification_config(wechat_config):
    """单独保存企业微信通知配置"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        UPDATE wechat_notification_config
        SET enabled=?, corp_id=?, corp_secret=?, agent_id=?, to_users=?, updated_at=?
        WHERE id=1
    ''', (
        1 if wechat_config.get('enabled', False) else 0,
        wechat_config.get('corp_id', ''),
        wechat_config.get('corp_secret', ''),
        wechat_config.get('agent_id', ''),
        wechat_config.get('to_users', '@all'),
        datetime.now()
    ))

    conn.commit()
    conn.close()


def get_all_config():
    """获取所有配置（用于备份脚本）"""
    return {
        'postgresql': [dict(row) for row in get_database_connections('postgresql')],
        'mysql': [dict(row) for row in get_database_connections('mysql')],
        'schedules': {k: v['cron_expression'] for k, v in get_backup_schedules().items() if v},
        'retention_days': {k: v['retention_days'] for k, v in get_backup_schedules().items()},
        'notifications': get_notification_config()
    }


# ===== 命令行工具 =====

def get_db_config_for_shell(db_type):
    """为 Shell 脚本获取数据库连接配置"""
    connections = get_database_connections(db_type)
    output = []
    for conn in connections:
        # 输出格式: host;port;user;password;db_name;id
        output.append(f"{conn['host']};{conn['port']};{conn['user']};{conn['password']};{conn['db_name']};{conn['id']}")
    return '\n'.join(output)


def get_retention_days_for_shell(db_type):
    """为 Shell 脚本获取保留天数"""
    schedule = get_backup_schedule(db_type)
    if schedule:
        return schedule.get('retention_days', 7)
    return 7


def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(description='配置管理工具')
    parser.add_argument('action', choices=['init', 'get', 'export', 'get_dbs', 'get_retention'], help='操作类型')
    parser.add_argument('--format', choices=['json', 'env'], default='json', help='输出格式')
    parser.add_argument('--db_type', help='数据库类型 (postgresql/mysql)')

    args = parser.parse_args()

    if args.action == 'init':
        init_config_tables()
    elif args.action == 'get':
        config = get_all_config()
        if args.format == 'json':
            print(json.dumps(config, indent=2, ensure_ascii=False))
        else:
            # 导出为环境变量格式（用于 bash）
            print("# 配置导出")
            for db_type in ['postgresql', 'mysql']:
                for db in config.get(db_type, []):
                    print(f"export DB_{db_type.upper()}_HOST={db['host']}")
                    print(f"export DB_{db_type.upper()}_PORT={db['port']}")
    elif args.action == 'export':
        config = get_all_config()
        print(json.dumps(config, indent=2, ensure_ascii=False))
    elif args.action == 'get_dbs':
        # 获取数据库连接列表，用于 backup.sh
        if not args.db_type or args.db_type not in ['postgresql', 'mysql']:
            print("错误: 必须指定 --db_type (postgresql 或 mysql)", file=sys.stderr)
            sys.exit(1)
        print(get_db_config_for_shell(args.db_type))
    elif args.action == 'get_retention':
        # 获取保留天数，用于 cleanup
        if not args.db_type or args.db_type not in ['postgresql', 'mysql']:
            print("错误: 必须指定 --db_type (postgresql 或 mysql)", file=sys.stderr)
            sys.exit(1)
        print(get_retention_days_for_shell(args.db_type))


if __name__ == '__main__':
    main()
