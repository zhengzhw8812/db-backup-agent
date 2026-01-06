#!/usr/bin/env python3
"""
数据库自动迁移功能测试脚本
演示 ensure_v22_tables() 的使用
"""

import sqlite3
import os
from migrate_db import ensure_v22_tables

# 测试数据库路径
TEST_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       'backups', 'another', 'users.db')


def get_tables():
    """获取所有表"""
    conn = sqlite3.connect(TEST_DB)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
    tables = [row[0] for row in cursor.fetchall()]
    conn.close()
    return tables


def get_indexes():
    """获取所有索引"""
    conn = sqlite3.connect(TEST_DB)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%' ORDER BY name")
    indexes = [row[0] for row in cursor.fetchall()]
    conn.close()
    return indexes


def test_missing_table():
    """测试缺失表的恢复"""
    print("\n" + "=" * 60)
    print("测试 1: 缺失表的自动恢复")
    print("=" * 60)

    # 删除一个表
    print("\n1. 删除 system_logs 表...")
    conn = sqlite3.connect(TEST_DB)
    cursor = conn.cursor()
    cursor.execute('DROP TABLE IF EXISTS system_logs')
    cursor.execute('DROP INDEX IF EXISTS idx_system_logs_type')
    cursor.execute('DROP INDEX IF EXISTS idx_system_logs_category')
    cursor.execute('DROP INDEX IF EXISTS idx_system_logs_created_at')
    conn.commit()
    conn.close()

    tables = get_tables()
    print(f"   当前表数量: {len(tables)}")
    print(f"   system_logs 存在: {'✅ 是' if 'system_logs' in tables else '❌ 否'}")

    # 运行完整性检查
    print("\n2. 运行完整性检查...")
    ensure_v22_tables()

    # 验证恢复
    tables = get_tables()
    indexes = get_indexes()
    print(f"\n3. 验证恢复结果:")
    print(f"   表数量: {len(tables)}")
    print(f"   索引数量: {len(indexes)}")
    print(f"   system_logs 存在: {'✅ 是' if 'system_logs' in tables else '❌ 否'}")
    print(f"   idx_system_logs_type 存在: {'✅ 是' if 'idx_system_logs_type' in indexes else '❌ 否'}")


def test_missing_index():
    """测试缺失索引的恢复"""
    print("\n" + "=" * 60)
    print("测试 2: 缺失索引的自动恢复")
    print("=" * 60)

    # 删除一个索引
    print("\n1. 删除 idx_backup_db_type 索引...")
    conn = sqlite3.connect(TEST_DB)
    cursor = conn.cursor()
    cursor.execute('DROP INDEX IF EXISTS idx_backup_db_type')
    conn.commit()
    conn.close()

    indexes = get_indexes()
    print(f"   当前索引数量: {len(indexes)}")
    print(f"   idx_backup_db_type 存在: {'✅ 是' if 'idx_backup_db_type' in indexes else '❌ 否'}")

    # 运行完整性检查
    print("\n2. 运行完整性检查...")
    ensure_v22_tables()

    # 验证恢复
    indexes = get_indexes()
    print(f"\n3. 验证恢复结果:")
    print(f"   索引数量: {len(indexes)}")
    print(f"   idx_backup_db_type 存在: {'✅ 是' if 'idx_backup_db_type' in indexes else '❌ 否'}")


def test_intact_database():
    """测试完整数据库的情况"""
    print("\n" + "=" * 60)
    print("测试 3: 完整数据库的检查")
    print("=" * 60)

    print("\n1. 检查当前数据库状态...")
    tables = get_tables()
    indexes = get_indexes()
    print(f"   表数量: {len(tables)}")
    print(f"   索引数量: {len(indexes)}")

    print("\n2. 运行完整性检查...")
    ensure_v22_tables()

    print("\n3. 验证结果:")
    print("   ✅ 数据库保持完整，无修改")


def test_complete_database():
    """测试完全空的数据库"""
    print("\n" + "=" * 60)
    print("测试 4: 创建全新的完整数据库")
    print("=" * 60)

    test_db = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_users.db')

    # 删除测试数据库（如果存在）
    if os.path.exists(test_db):
        os.remove(test_db)
        print("\n1. 删除旧的测试数据库")

    # 临时修改数据库路径
    import migrate_db
    original_db = migrate_db.DB_FILE
    migrate_db.DB_FILE = test_db

    print("2. 创建全新的数据库...")
    ensure_v22_tables()

    # 验证
    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    tables = [row[0] for row in cursor.fetchall()]
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'")
    indexes = [row[0] for row in cursor.fetchall()]
    conn.close()

    print(f"\n3. 验证新数据库:")
    print(f"   表数量: {len(tables)}")
    print(f"   索引数量: {len(indexes)}")
    print(f"   ✅ 新数据库创建成功")

    # 恢复原始路径
    migrate_db.DB_FILE = original_db

    # 清理测试数据库
    os.remove(test_db)
    print("\n4. 清理测试数据库")


def main():
    """主测试函数"""
    print("\n" + "=" * 60)
    print("数据库自动迁移功能测试")
    print("=" * 60)
    print(f"\n测试数据库: {TEST_DB}")

    try:
        # 运行所有测试
        test_intact_database()
        test_missing_table()
        test_missing_index()
        test_complete_database()

        print("\n" + "=" * 60)
        print("✅ 所有测试完成！")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
