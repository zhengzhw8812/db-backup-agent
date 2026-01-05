#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
系统日志记录模块
将各种系统日志记录到数据库
"""

import sys
import os
import argparse
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB_FILE = "/backups/users.db"


def get_db_connection():
    """获取数据库连接"""
    import sqlite3
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def log_to_db(log_type, category, message, details=None):
    """
    记录日志到数据库

    Args:
        log_type: 日志类型 (info/warning/error/debug)
        category: 日志分类 (backup/notify/system/cron等)
        message: 日志消息
        details: 详细信息（可选，可以是长文本）
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO system_logs (log_type, category, message, details)
            VALUES (?, ?, ?, ?)
        ''', (log_type, category, message, details))

        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"记录日志到数据库失败: {str(e)}", file=sys.stderr)
        return False


def get_logs(limit=100, log_type=None, category=None):
    """
    获取日志列表

    Args:
        limit: 返回的记录数
        log_type: 过滤日志类型
        category: 过滤分类

    Returns:
        日志记录列表
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        query = "SELECT * FROM system_logs WHERE 1=1"
        params = []

        if log_type:
            query += " AND log_type = ?"
            params.append(log_type)

        if category:
            query += " AND category = ?"
            params.append(category)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]
    except Exception as e:
        print(f"获取日志失败: {str(e)}", file=sys.stderr)
        return []


def clear_old_logs(days=30):
    """
    清理旧日志

    Args:
        days: 保留最近多少天的日志
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''
            DELETE FROM system_logs
            WHERE created_at < datetime('now', '-' || ? || ' days')
        ''', (days,))

        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()

        return deleted_count
    except Exception as e:
        print(f"清理旧日志失败: {str(e)}", file=sys.stderr)
        return 0


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(description='系统日志管理工具')
    subparsers = parser.add_subparsers(dest='command', help='子命令')

    # log 命令
    log_parser = subparsers.add_parser('log', help='记录日志')
    log_parser.add_argument('--type', required=True, choices=['info', 'warning', 'error', 'debug'], help='日志类型')
    log_parser.add_argument('--category', required=True, help='日志分类')
    log_parser.add_argument('--message', required=True, help='日志消息')
    log_parser.add_argument('--details', help='详细信息')

    # get 命令
    get_parser = subparsers.add_parser('get', help='获取日志')
    get_parser.add_argument('--limit', type=int, default=100, help='返回记录数')
    get_parser.add_argument('--type', help='过滤日志类型')
    get_parser.add_argument('--category', help='过滤分类')

    # clear 命令
    clear_parser = subparsers.add_parser('clear', help='清理旧日志')
    clear_parser.add_argument('--days', type=int, default=30, help='保留最近多少天的日志')

    args = parser.parse_args()

    if args.command == 'log':
        success = log_to_db(args.type, args.category, args.message, args.details)
        if success:
            print("日志记录成功")
            sys.exit(0)
        else:
            print("日志记录失败", file=sys.stderr)
            sys.exit(1)

    elif args.command == 'get':
        import json
        logs = get_logs(limit=args.limit, log_type=args.type, category=args.category)
        print(json.dumps(logs, indent=2, ensure_ascii=False))

    elif args.command == 'clear':
        deleted_count = clear_old_logs(days=args.days)
        print(f"已清理 {deleted_count} 条旧日志")

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
