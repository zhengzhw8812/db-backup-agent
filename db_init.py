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

    # 创建备份历史表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS backup_history (
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

    # 创建通知历史表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notification_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            backup_history_id INTEGER,
            notification_type TEXT,
            status TEXT,
            error_message TEXT,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (backup_history_id) REFERENCES backup_history(id)
        )
    ''')

    # 创建系统日志表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS system_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            log_type TEXT NOT NULL,
            category TEXT,
            message TEXT,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 创建索引以提高查询性能
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_backup_db_type ON backup_history(db_type)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_backup_status ON backup_history(status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_backup_created_at ON backup_history(created_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_notification_backup_id ON notification_history(backup_history_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_system_logs_type ON system_logs(log_type)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_system_logs_category ON system_logs(category)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_system_logs_created_at ON system_logs(created_at)')

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
