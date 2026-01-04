import sqlite3
import hashlib
import os

# 将 users.db 放在 backups 文件夹下，确保数据持久化
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backups', 'users.db')

def init_db():
    """初始化数据库"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # 创建用户表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()
    conn.close()
    print(f"数据库初始化完成: {DB_FILE}")

def get_db_connection():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(password):
    """密码哈希"""
    return hashlib.sha256(password.encode()).hexdigest()

if __name__ == '__main__':
    init_db()
