#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
备份日志记录模块
使用 SQLite 记录备份历史，支持结构化查询和统计
"""

import os
import sys
import sqlite3
import argparse
import json
from datetime import datetime
from pathlib import Path

# 数据库文件路径
DB_FILE = "/backups/users.db"


def get_db_connection():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def log_backup(user_id, db_type, db_name, trigger_type, status, message,
               backup_file=None, file_size=None, duration=None, log_file=None):
    """
    记录备份历史

    Args:
        user_id: 用户 ID
        db_type: 数据库类型 (PostgreSQL/MySQL)
        db_name: 数据库名称
        trigger_type: 触发类型 (自动/手动)
        status: 状态 (成功/失败/跳过)
        message: 消息说明
        backup_file: 备份文件名
        file_size: 文件大小（字节）
        duration: 耗时（秒）
        log_file: 详细日志文件路径

    Returns:
        int: 插入记录的 ID
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO backup_history
            (user_id, db_type, db_name, trigger_type, status, message, backup_file, file_size, duration, log_file)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, db_type, db_name, trigger_type, status, message, backup_file, file_size, duration, log_file))

        conn.commit()
        record_id = cursor.lastrowid
        conn.close()

        return record_id
    except Exception as e:
        print(f"记录备份历史失败: {str(e)}", file=sys.stderr)
        return None


def log_notification(backup_history_id, notification_type, status, error_message=None):
    """
    记录通知历史

    Args:
        backup_history_id: 关联的备份记录 ID
        notification_type: 通知类型 (email/wechat)
        status: 状态 (成功/失败)
        error_message: 错误信息

    Returns:
        int: 插入记录的 ID
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''
            INSERT INTO notification_history
            (backup_history_id, notification_type, status, error_message)
            VALUES (?, ?, ?, ?)
        ''', (backup_history_id, notification_type, status, error_message))

        conn.commit()
        record_id = cursor.lastrowid
        conn.close()

        return record_id
    except Exception as e:
        print(f"记录通知历史失败: {str(e)}", file=sys.stderr)
        return None


def get_backup_history(limit=100, offset=0, user_id=None, db_type=None, status=None, start_date=None, end_date=None):
    """
    查询备份历史

    Args:
        limit: 返回记录数
        offset: 偏移量
        user_id: 用户 ID（用于多用户隔离）
        db_type: 过滤数据库类型
        status: 过滤状态
        start_date: 开始日期
        end_date: 结束日期

    Returns:
        list: 备份历史记录列表
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # 构建查询条件
        where_conditions = []
        params = []

        if user_id is not None:
            where_conditions.append("user_id = ?")
            params.append(user_id)

        if db_type:
            where_conditions.append("db_type = ?")
            params.append(db_type)

        if status:
            where_conditions.append("status = ?")
            params.append(status)

        if start_date:
            where_conditions.append("created_at >= ?")
            params.append(start_date)

        if end_date:
            where_conditions.append("created_at <= ?")
            params.append(end_date)

        where_clause = ""
        if where_conditions:
            where_clause = "WHERE " + " AND ".join(where_conditions)

        query = f'''
            SELECT * FROM backup_history
            {where_clause}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        '''
        params.extend([limit, offset])

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]
    except Exception as e:
        print(f"查询备份历史失败: {str(e)}", file=sys.stderr)
        return []


def get_backup_statistics(days=7):
    """
    获取备份统计信息

    Args:
        days: 统计最近几天的数据

    Returns:
        dict: 统计信息
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # 总备份次数
        cursor.execute('''
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN status = '成功' THEN 1 ELSE 0 END) as success,
                   SUM(CASE WHEN status = '失败' THEN 1 ELSE 0 END) as failed
            FROM backup_history
            WHERE created_at >= datetime('now', '-' || ? || ' days')
        ''', (days,))
        stats = dict(cursor.fetchone())

        # 按数据库类型统计
        cursor.execute('''
            SELECT db_type,
                   COUNT(*) as count,
                   SUM(CASE WHEN status = '成功' THEN 1 ELSE 0 END) as success
            FROM backup_history
            WHERE created_at >= datetime('now', '-' || ? || ' days')
            GROUP BY db_type
        ''', (days,))
        by_type = [dict(row) for row in cursor.fetchall()]

        # 按触发类型统计
        cursor.execute('''
            SELECT trigger_type,
                   COUNT(*) as count
            FROM backup_history
            WHERE created_at >= datetime('now', '-' || ? || ' days')
            GROUP BY trigger_type
        ''', (days,))
        by_trigger = [dict(row) for row in cursor.fetchall()]

        conn.close()

        return {
            'total': stats['total'] or 0,
            'success': stats['success'] or 0,
            'failed': stats['failed'] or 0,
            'success_rate': round((stats['success'] or 0) / max(stats['total'] or 1, 1) * 100, 2),
            'by_type': by_type,
            'by_trigger': by_trigger
        }
    except Exception as e:
        print(f"获取统计信息失败: {str(e)}", file=sys.stderr)
        return {}


def get_recent_backups(limit=10, user_id=None):
    """
    获取最近的备份记录

    Args:
        limit: 返回记录数
        user_id: 用户 ID（用于多用户隔离）

    Returns:
        list: 最近的备份记录
    """
    return get_backup_history(limit=limit, user_id=user_id)


def clear_old_history(days=30):
    """
    清理旧的备份历史记录

    Args:
        days: 保留最近多少天的记录

    Returns:
        int: 删除的记录数
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''
            DELETE FROM backup_history
            WHERE created_at < datetime('now', '-' || ? || ' days')
        ''', (days,))

        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()

        return deleted_count
    except Exception as e:
        print(f"清理旧记录失败: {str(e)}", file=sys.stderr)
        return 0


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(description='备份日志记录工具')
    subparsers = parser.add_subparsers(dest='command', help='可用命令')

    # 记录备份命令
    log_parser = subparsers.add_parser('log', help='记录备份')
    log_parser.add_argument('--type', required=True, help='数据库类型 (PostgreSQL/MySQL)')
    log_parser.add_argument('--name', help='数据库名称')
    log_parser.add_argument('--trigger', required=True, help='触发类型 (自动/手动)')
    log_parser.add_argument('--status', required=True, choices=['成功', '失败', '跳过'], help='备份状态')
    log_parser.add_argument('--message', required=True, help='消息说明')
    log_parser.add_argument('--file', help='备份文件名')
    log_parser.add_argument('--size', type=int, help='文件大小（字节）')
    log_parser.add_argument('--duration', type=float, help='耗时（秒）')
    log_parser.add_argument('--log', help='详细日志文件路径')
    log_parser.add_argument('--user-id', type=int, help='用户 ID（用于多用户隔离）')

    # 查询历史命令
    query_parser = subparsers.add_parser('query', help='查询备份历史')
    query_parser.add_argument('--limit', type=int, default=50, help='返回记录数')
    query_parser.add_argument('--db-type', help='过滤数据库类型')
    query_parser.add_argument('--status', help='过滤状态')
    query_parser.add_argument('--json', action='store_true', help='以 JSON 格式输出')

    # 统计命令
    stats_parser = subparsers.add_parser('stats', help='获取统计信息')
    stats_parser.add_argument('--days', type=int, default=7, help='统计最近几天的数据')

    # 清理命令
    clear_parser = subparsers.add_parser('clear', help='清理旧记录')
    clear_parser.add_argument('--days', type=int, default=30, help='保留最近多少天的记录')

    args = parser.parse_args()

    if args.command == 'log':
        # 记录备份
        record_id = log_backup(
            user_id=getattr(args, 'user_id', None),
            db_type=args.type,
            db_name=args.name,
            trigger_type=args.trigger,
            status=args.status,
            message=args.message,
            backup_file=args.file,
            file_size=args.size,
            duration=args.duration,
            log_file=args.log
        )

        if record_id:
            print(f"备份记录已保存，ID: {record_id}")
            sys.exit(0)
        else:
            print("记录备份失败")
            sys.exit(1)

    elif args.command == 'query':
        # 查询历史
        records = get_backup_history(
            limit=args.limit,
            db_type=args.db_type,
            status=args.status
        )

        if args.json:
            print(json.dumps(records, indent=2, ensure_ascii=False))
        else:
            if not records:
                print("没有找到匹配的记录")
            else:
                print(f"找到 {len(records)} 条记录:\n")
                for record in records:
                    print(f"[{record['created_at']}] {record['db_type']} - {record['status']}")
                    print(f"  触发方式: {record['trigger_type']}")
                    print(f"  消息: {record['message']}")
                    if record['backup_file']:
                        print(f"  文件: {record['backup_file']}")
                    print()

    elif args.command == 'stats':
        # 统计信息
        stats = get_backup_statistics(days=args.days)
        print(f"最近 {args.days} 天的备份统计:")
        print(f"  总备份次数: {stats['total']}")
        print(f"  成功: {stats['success']}")
        print(f"  失败: {stats['failed']}")
        print(f"  成功率: {stats['success_rate']}%")

        if stats.get('by_type'):
            print("\n按数据库类型:")
            for item in stats['by_type']:
                print(f"  {item['db_type']}: {item['count']} 次 (成功: {item['success']})")

        if stats.get('by_trigger'):
            print("\n按触发方式:")
            for item in stats['by_trigger']:
                print(f"  {item['trigger_type']}: {item['count']} 次")

    elif args.command == 'clear':
        # 清理旧记录
        deleted_count = clear_old_history(days=args.days)
        print(f"已清理 {deleted_count} 条旧备份记录（保留最近 {args.days} 天）")

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
