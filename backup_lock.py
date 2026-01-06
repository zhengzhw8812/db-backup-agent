#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
备份锁管理模块
用于防止同一类型的备份任务同时执行
"""

import os
import sqlite3
import threading
from datetime import datetime, timedelta

# 数据库文件路径
DB_FILE = "/backups/users.db"

# 内存缓存，用于快速检查锁状态
_lock_cache = {}
_lock_cache_lock = threading.Lock()


def get_db_connection():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_backup_lock_table():
    """初始化备份锁表"""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS backup_locks (
            db_type TEXT PRIMARY KEY,
            is_locked BOOLEAN DEFAULT 0,
            locked_at TIMESTAMP,
            locked_by TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 清理过期的锁（超过2小时的锁自动释放）
    expire_time = datetime.now() - timedelta(hours=2)
    cursor.execute('DELETE FROM backup_locks WHERE locked_at < ?', (expire_time,))

    conn.commit()
    conn.close()


def acquire_backup_lock(db_type, lock_id="manual"):
    """
    获取备份锁

    Args:
        db_type: 数据库类型 ('postgresql' 或 'mysql')
        lock_id: 锁标识（默认为 'manual'，自动备份可以用 'auto'）

    Returns:
        bool: 成功获取锁返回 True，否则返回 False
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # 检查是否已存在锁
        cursor.execute('SELECT is_locked, locked_at FROM backup_locks WHERE db_type=?', (db_type,))
        row = cursor.fetchone()

        current_time = datetime.now()

        if row and row['is_locked']:
            # 检查锁是否过期（超过2小时自动释放）
            if row['locked_at']:
                locked_at = datetime.fromisoformat(row['locked_at'])
                if current_time - locked_at < timedelta(hours=2):
                    # 锁仍然有效
                    conn.close()
                    return False
                else:
                    # 锁已过期，释放它
                    cursor.execute('''
                        UPDATE backup_locks
                        SET is_locked=?, locked_at=?, locked_by=?, updated_at=?
                        WHERE db_type=?
                    ''', (1, current_time, lock_id, current_time, db_type))
            else:
                # 没有锁定时间，视为已过期
                cursor.execute('''
                    UPDATE backup_locks
                    SET is_locked=?, locked_at=?, locked_by=?, updated_at=?
                    WHERE db_type=?
                ''', (1, current_time, lock_id, current_time, db_type))
        else:
            # 没有锁或锁已释放，创建新锁
            if row:
                cursor.execute('''
                    UPDATE backup_locks
                    SET is_locked=?, locked_at=?, locked_by=?, updated_at=?
                    WHERE db_type=?
                ''', (1, current_time, lock_id, current_time, db_type))
            else:
                cursor.execute('''
                    INSERT INTO backup_locks (db_type, is_locked, locked_at, locked_by)
                    VALUES (?, ?, ?, ?)
                ''', (db_type, 1, current_time, lock_id))

        conn.commit()

        # 更新内存缓存
        with _lock_cache_lock:
            _lock_cache[db_type] = {
                'is_locked': True,
                'locked_at': current_time,
                'locked_by': lock_id
            }

        return True

    except Exception as e:
        print(f"获取备份锁时出错: {str(e)}")
        conn.rollback()
        return False
    finally:
        conn.close()


def release_backup_lock(db_type):
    """
    释放备份锁

    Args:
        db_type: 数据库类型 ('postgresql' 或 'mysql')

    Returns:
        bool: 成功释放返回 True，否则返回 False
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('''
            UPDATE backup_locks
            SET is_locked=?, locked_at=NULL, locked_by=NULL, updated_at=?
            WHERE db_type=?
        ''', (0, datetime.now(), db_type))

        conn.commit()

        # 更新内存缓存
        with _lock_cache_lock:
            if db_type in _lock_cache:
                _lock_cache[db_type]['is_locked'] = False

        return True

    except Exception as e:
        print(f"释放备份锁时出错: {str(e)}")
        conn.rollback()
        return False
    finally:
        conn.close()


def is_backup_locked(db_type):
    """
    检查备份是否被锁定

    Args:
        db_type: 数据库类型 ('postgresql' 或 'mysql')

    Returns:
        bool: 如果被锁定返回 True，否则返回 False
    """
    # 先检查内存缓存
    with _lock_cache_lock:
        if db_type in _lock_cache:
            lock_info = _lock_cache[db_type]
            if lock_info['is_locked']:
                # 检查是否过期
                if lock_info['locked_at']:
                    if datetime.now() - lock_info['locked_at'] < timedelta(hours=2):
                        return True
                    else:
                        # 缓存中的锁已过期，删除它
                        del _lock_cache[db_type]

    # 检查数据库
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('SELECT is_locked, locked_at, locked_by FROM backup_locks WHERE db_type=?', (db_type,))
        row = cursor.fetchone()

        if row and row['is_locked']:
            # 检查锁是否过期
            if row['locked_at']:
                locked_at = datetime.fromisoformat(row['locked_at'])
                if datetime.now() - locked_at < timedelta(hours=2):
                    # 更新内存缓存
                    with _lock_cache_lock:
                        _lock_cache[db_type] = {
                            'is_locked': True,
                            'locked_at': locked_at,
                            'locked_by': row['locked_by'] if row['locked_by'] else 'unknown'
                        }
                    return True

        return False

    except Exception as e:
        print(f"检查备份锁时出错: {str(e)}")
        return False
    finally:
        conn.close()


def get_backup_lock_info(db_type):
    """
    获取备份锁的详细信息

    Args:
        db_type: 数据库类型 ('postgresql' 或 'mysql')

    Returns:
        dict: 锁信息，如果不存在则返回 None
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('SELECT * FROM backup_locks WHERE db_type=?', (db_type,))
        row = cursor.fetchone()

        if row:
            return dict(row)
        return None

    except Exception as e:
        print(f"获取备份锁信息时出错: {str(e)}")
        return None
    finally:
        conn.close()


def get_all_backup_locks():
    """
    获取所有备份锁的状态

    Returns:
        dict: 键为 db_type，值为锁信息
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute('SELECT * FROM backup_locks')
        rows = cursor.fetchall()

        result = {}
        for row in rows:
            db_type = row['db_type']
            lock_info = dict(row)

            # 检查是否过期
            if lock_info['is_locked'] and lock_info['locked_at']:
                locked_at = datetime.fromisoformat(lock_info['locked_at'])
                if datetime.now() - locked_at >= timedelta(hours=2):
                    # 锁已过期，标记为未锁定
                    lock_info['is_locked'] = False
                    lock_info['expired'] = True

            result[db_type] = lock_info

        return result

    except Exception as e:
        print(f"获取所有备份锁时出错: {str(e)}")
        return {}
    finally:
        conn.close()


# ===== 命令行工具 =====

def main():
    """命令行入口"""
    import argparse
    import json

    parser = argparse.ArgumentParser(description='备份锁管理工具')
    parser.add_argument('action', choices=['acquire', 'release', 'check', 'list', 'init'],
                       help='操作类型')
    parser.add_argument('--db_type', help='数据库类型 (postgresql/mysql)')
    parser.add_argument('--lock_id', default='manual', help='锁标识（默认: manual）')

    args = parser.parse_args()

    if args.action == 'init':
        init_backup_lock_table()
        print("备份锁表初始化完成")

    elif args.action == 'acquire':
        if not args.db_type or args.db_type not in ['postgresql', 'mysql']:
            print("错误: 必须指定 --db_type (postgresql 或 mysql)")
            return

        if acquire_backup_lock(args.db_type, args.lock_id):
            print(f"成功获取 {args.db_type} 备份锁")
        else:
            print(f"无法获取 {args.db_type} 备份锁（可能已被锁定）")
            exit(1)

    elif args.action == 'release':
        if not args.db_type or args.db_type not in ['postgresql', 'mysql']:
            print("错误: 必须指定 --db_type (postgresql 或 mysql)")
            return

        if release_backup_lock(args.db_type):
            print(f"成功释放 {args.db_type} 备份锁")
        else:
            print(f"释放 {args.db_type} 备份锁失败")
            exit(1)

    elif args.action == 'check':
        if not args.db_type or args.db_type not in ['postgresql', 'mysql']:
            print("错误: 必须指定 --db_type (postgresql 或 mysql)")
            return

        if is_backup_locked(args.db_type):
            lock_info = get_backup_lock_info(args.db_type)
            print(f"{args.db_type} 备份已被锁定")
            if lock_info:
                print(f"  锁定时间: {lock_info['locked_at']}")
                print(f"  锁定者: {lock_info['locked_by']}")
            exit(1)
        else:
            print(f"{args.db_type} 备份未被锁定")

    elif args.action == 'list':
        locks = get_all_backup_locks()
        if locks:
            print(json.dumps(locks, indent=2, ensure_ascii=False, default=str))
        else:
            print("没有备份锁记录")


if __name__ == '__main__':
    main()
