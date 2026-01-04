from flask import Flask, render_template, request, redirect, url_for, jsonify, send_from_directory, flash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import json
import os
import subprocess
import uuid
import sqlite3
import hashlib
from datetime import datetime, timedelta

import re

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this-in-production'  # 生产环境请更改此密钥

# 配置Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = '请先登录以访问此页面'

# 获取项目根目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, 'backups', 'config.json')
BACKUP_DIR = os.path.join(BASE_DIR, 'backups')
DB_FILE = os.path.join(BASE_DIR, 'backups', 'users.db')

# --- 用户模型和认证 ---

class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    """加载用户"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('SELECT id, username FROM users WHERE id = ?', (user_id,))
    user_data = cursor.fetchone()
    conn.close()

    if user_data:
        return User(user_data['id'], user_data['username'])
    return None

def get_db_connection():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(password):
    """密码哈希"""
    return hashlib.sha256(password.encode()).hexdigest()

def init_db():
    """初始化数据库"""
    conn = get_db_connection()
    cursor = conn.cursor()
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

# 在应用启动时初始化数据库
init_db()

# --- 辅助函数 ---

def load_config():
    """加载配置文件，如果文件不存在或为空，则返回一个默认结构。"""
    if os.path.exists(CONFIG_FILE) and os.path.getsize(CONFIG_FILE) > 0:
        with open(CONFIG_FILE, 'r') as f:
            try:
                config = json.load(f)
                # 兼容旧版配置，确保 schedules 和 retention_days 字典存在
                config.setdefault('schedules', {})
                config.setdefault('retention_days', {'postgresql': 7, 'mysql': 7})
                # 如果是旧版的单一 retention_days，迁移到新结构
                if isinstance(config.get('retention_days'), int):
                    old_days = config['retention_days']
                    config['retention_days'] = {'postgresql': old_days, 'mysql': old_days}
                return config
            except json.JSONDecodeError:
                pass  # 文件损坏或为空，返回默认值
    # 默认结构
    return {
        "postgresql": [],
        "mysql": [],
        "retention_days": {"postgresql": 7, "mysql": 7},
        "schedules": {}
    }

def save_config(config):
    """将配置保存到文件。"""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

def update_crontab():
    """从 config.json 读取计划并更新系统的 crontab。"""
    config = load_config()
    cron_file_path = "/etc/cron.d/backup-cron"
    
    # 构建 crontab 内容
    content = "SHELL=/bin/bash\n"
    content += "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\n"
    
    pg_schedule = config.get('schedules', {}).get('postgresql', 'disabled')
    if pg_schedule and pg_schedule != 'disabled':
        content += f"{pg_schedule} root /usr/local/bin/backup.sh postgresql 自动 >> /var/log/cron.log 2>&1\n"
        
    mysql_schedule = config.get('schedules', {}).get('mysql', 'disabled')
    if mysql_schedule and mysql_schedule != 'disabled':
        content += f"{mysql_schedule} root /usr/local/bin/backup.sh mysql 自动 >> /var/log/cron.log 2>&1\n"
        
    try:
        # 写入文件
        with open(cron_file_path, 'w') as f:
            f.write(content)
        
        # 设置权限
        os.chmod(cron_file_path, 0o644)
        
        # 应用 crontab
        subprocess.run(['crontab', cron_file_path], check=True)
        print("Crontab updated successfully.")
        return True
    except (IOError, subprocess.CalledProcessError) as e:
        print(f"Error updating crontab: {e}")
        return False

def _parse_cron_for_ui(cron_str):
    """解析cron表达式，返回一个适合UI填充的字典。"""
    if not cron_str or cron_str == 'disabled':
        return {'frequency': 'disabled'}

    parts = cron_str.split()
    if len(parts) != 5:
        return {'frequency': 'disabled'} # 格式不正确

    minute, hour, day_of_month, month, day_of_week = parts

    # 格式化时间
    time_val = f"{int(hour):02d}:{int(minute):02d}"

    # 判断频率
    if day_of_month == '*' and day_of_week != '*':
        return {
            'frequency': 'weekly',
            'time': time_val,
            'weekday': day_of_week
        }
    elif day_of_month != '*' and day_of_week == '*':
        return {
            'frequency': 'monthly',
            'time': time_val,
            'day_of_month': day_of_month
        }
    elif day_of_month == '*' and day_of_week == '*':
        return {
            'frequency': 'daily',
            'time': time_val
        }
    
    return {'frequency': 'disabled'} # 无法识别的格式

def _humanize_cron(cron_str):
    """将cron表达式转换为人类可读的字符串。"""
    if not cron_str or cron_str == 'disabled':
        return "从不 (仅手动)"

    parts = cron_str.split()
    if len(parts) != 5:
        return "无效计划"

    minute, hour, day_of_month, _, day_of_week = parts
    time_str = f"{int(hour):02d}:{int(minute):02d}"

    weekdays = {'0': '周日', '1': '周一', '2': '周二', '3': '周三', '4': '周四', '5': '周五', '6': '周六'}

    if day_of_month == '*' and day_of_week != '*':
        return f"每周{weekdays.get(day_of_week, '')} {time_str}"
    elif day_of_month != '*' and day_of_week == '*':
        return f"每月{day_of_month}号 {time_str}"
    elif day_of_month == '*' and day_of_week == '*':
        return f"每天 {time_str}"
    
    return "自定义计划"


HISTORY_LOG_FILE = os.path.join(BACKUP_DIR, 'backup_history.log')

def load_backup_history():
    """加载并解析备份历史日志，返回最近7天的记录。"""
    if not os.path.exists(HISTORY_LOG_FILE):
        return []

    history = []
    one_week_ago = datetime.now() - timedelta(days=7)

    with open(HISTORY_LOG_FILE, 'r') as f:
        for line in f:
            parts = line.strip().split(' | ')

            if len(parts) == 5:
                # 格式: timestamp | db_type | trigger | status | message
                timestamp, db_type, trigger, status, message = parts
                history.append({
                    'timestamp': timestamp,
                    'db_type': db_type,
                    'trigger': trigger,
                    'status': status,
                    'message': message,
                    'log_file': None
                })
            elif len(parts) == 6:
                # 格式: timestamp | db_type | trigger | status | message | log_file
                timestamp, db_type, trigger, status, message, log_file = parts
                history.append({
                    'timestamp': timestamp,
                    'db_type': db_type,
                    'trigger': trigger,
                    'status': status,
                    'message': message,
                    'log_file': log_file if log_file else None
                })

    # 按时间倒序排序，并只保留最近7天的记录
    filtered_history = []
    for item in history:
        try:
            # 解析时间戳 (格式: 2025-01-04 12:00:00)
            item_time = datetime.strptime(item['timestamp'], '%Y-%m-%d %H:%M:%S')
            if item_time >= one_week_ago:
                filtered_history.append(item)
        except ValueError:
            # 如果时间解析失败，仍然保留该记录
            filtered_history.append(item)

    return sorted(filtered_history, key=lambda x: x['timestamp'], reverse=True)


# --- 路由 ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    """登录页面"""
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if not username or not password:
            flash('请输入用户名和密码', 'danger')
            return render_template('login.html')

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT id, username, password FROM users WHERE username = ?', (username,))
        user = cursor.fetchone()
        conn.close()

        if user and user['password'] == hash_password(password):
            user_obj = User(user['id'], user['username'])
            login_user(user_obj)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('index'))
        else:
            flash('用户名或密码错误', 'danger')

    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    """注册页面"""
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        # 验证输入
        if not username or not password or not confirm_password:
            flash('请填写所有字段', 'danger')
            return render_template('register.html')

        if password != confirm_password:
            flash('两次输入的密码不一致', 'danger')
            return render_template('register.html')

        if len(password) < 6:
            flash('密码长度至少为6位', 'danger')
            return render_template('register.html')

        # 检查用户名是否已存在
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM users WHERE username = ?', (username,))
        if cursor.fetchone():
            conn.close()
            flash('用户名已存在', 'danger')
            return render_template('register.html')

        # 创建新用户
        try:
            cursor.execute('INSERT INTO users (username, password) VALUES (?, ?)',
                         (username, hash_password(password)))
            conn.commit()
            conn.close()
            flash('注册成功！请登录', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            conn.close()
            flash('注册失败，请稍后重试', 'danger')
            return render_template('register.html')

    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    """登出"""
    logout_user()
    flash('已成功登出', 'success')
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    """主页，显示配置、备份列表和备份历史。"""
    config = load_config()
    # 确保关键字段存在
    config.setdefault('postgresql', [])
    config.setdefault('mysql', [])
    config.setdefault('retention_days', {'postgresql': 7, 'mysql': 7})
    config.setdefault('schedules', {})

    # 解析cron表达式以填充UI
    schedules_ui = {
        'postgresql': _parse_cron_for_ui(config['schedules'].get('postgresql')),
        'mysql': _parse_cron_for_ui(config['schedules'].get('mysql'))
    }

    # 为数据库列表生成人类可读的计划描述
    humanized_schedules = {
        'postgresql': _humanize_cron(config['schedules'].get('postgresql')),
        'mysql': _humanize_cron(config['schedules'].get('mysql'))
    }

    backup_files = sorted(
        [f for f in os.listdir(BACKUP_DIR) if f.endswith(('.gz', '.tar.gz'))],
        key=lambda f: os.path.getmtime(os.path.join(BACKUP_DIR, f)),
        reverse=True
    )

    # 分类备份文件
    backups_by_type = {'postgresql': [], 'mysql': []}
    one_week_ago = datetime.now() - timedelta(days=7)
    retention_days_config = config.get('retention_days', {'postgresql': 7, 'mysql': 7})

    for backup_file in backup_files:
        file_path = os.path.join(BACKUP_DIR, backup_file)
        creation_time = datetime.fromtimestamp(os.path.getmtime(file_path))

        # 根据文件名确定数据库类型
        if 'postgresql' in backup_file or 'pg' in backup_file.lower():
            db_type = 'postgresql'
            retention_days = retention_days_config.get('postgresql', 7)
        elif 'mysql' in backup_file.lower():
            db_type = 'mysql'
            retention_days = retention_days_config.get('mysql', 7)
        else:
            # 无法识别类型，归为 postgresql 作为默认
            db_type = 'postgresql'
            retention_days = 7

        # 只显示最近一周的备份
        if creation_time >= one_week_ago:
            deletion_time = creation_time + timedelta(days=retention_days)
            backups_by_type[db_type].append({
                'name': backup_file,
                'delete_time': deletion_time.strftime('%Y-%m-%d %H:%M:%S')
            })

    backup_history = load_backup_history()

    return render_template('index.html', config=config, backups_by_type=backups_by_type, schedules_ui=schedules_ui, humanized_schedules=humanized_schedules, backup_history=backup_history)

@app.route('/add_db', methods=['POST'])
def add_db():
    """添加或更新数据库配置。"""
    config = load_config()
    db_type = request.form.get('type')
    edit_id = request.form.get('edit_id')  # 获取编辑ID

    if db_type in ['postgresql', 'mysql']:
        if edit_id:
            # 编辑模式:更新现有配置
            # edit_id 格式: "postgresql-uuid" 或 "mysql-uuid"
            parts = edit_id.split('-', 1)
            if len(parts) == 2:
                edit_type, actual_id = parts
                if edit_type == db_type:
                    # 查找并更新
                    for i, db in enumerate(config[db_type]):
                        if db.get('id') == actual_id:
                            config[db_type][i] = {
                                "id": actual_id,
                                "host": request.form.get('host'),
                                "port": request.form.get('port'),
                                "user": request.form.get('user'),
                                "password": request.form.get('password'),
                                "db": request.form.get('db')
                            }
                            save_config(config)
                            break
        else:
            # 新增模式
            new_db = {
                "id": str(uuid.uuid4()), # 分配唯一ID
                "host": request.form.get('host'),
                "port": request.form.get('port'),
                "user": request.form.get('user'),
                "password": request.form.get('password'),
                "db": request.form.get('db')
            }
            config[db_type].append(new_db)
            save_config(config)

    return redirect(url_for('index'))

@app.route('/delete_db/<db_type>/<db_id>', methods=['GET', 'POST'])
def delete_db(db_type, db_id):
    """根据ID删除一个数据库配置。"""
    config = load_config()
    if db_type in config and isinstance(config[db_type], list):
        # 通过ID过滤掉要删除的项
        config[db_type] = [db for db in config[db_type] if db.get('id') != db_id]
        save_config(config)
    return redirect(url_for('index'))

@app.route('/get_db/<db_type>/<db_id>')
@login_required
def get_db(db_type, db_id):
    """获取指定数据库配置的详情,用于编辑。"""
    config = load_config()
    if db_type in config and isinstance(config[db_type], list):
        for db in config[db_type]:
            if db.get('id') == db_id:
                return jsonify(db)
    return jsonify({'error': 'Database not found'}), 404

@app.route('/backup_now/<db_type>', methods=['POST'])
def backup_now(db_type):
    """触发一次指定数据库的手动备份。"""
    config = load_config()
    task_status = '未启动 (未配置)'

    try:
        if db_type == 'postgresql' and config.get('postgresql'):
            subprocess.Popen(['/usr/local/bin/backup.sh', 'postgresql', '手动'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            task_status = '启动'
        elif db_type == 'mysql' and config.get('mysql'):
            subprocess.Popen(['/usr/local/bin/backup.sh', 'mysql', '手动'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            task_status = '启动'
        
        return jsonify({'status': 'success', 'task': task_status})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/save_settings', methods=['POST'])
def save_settings():
    """保存单个数据库类型的计划设置。"""
    config = load_config()
    db_type = request.form.get('db_type', '')

    if not db_type or db_type not in ['postgresql', 'mysql']:
        return redirect(url_for('index'))

    try:
        # 确保 retention_days 是字典结构
        if not isinstance(config.get('retention_days'), dict):
            config['retention_days'] = {'postgresql': 7, 'mysql': 7}

        # 保存当前数据库类型的保留天数
        config['retention_days'][db_type] = int(request.form.get('retention_days', 7))

        frequency = request.form.get('frequency', 'disabled')

        if frequency == 'disabled':
            cron_expr = 'disabled'
        elif frequency == 'daily':
            time_str = request.form.get('time', '02:00')
            try:
                hour, minute = time_str.split(':')
            except (ValueError, AttributeError):
                hour, minute = '2', '0'
            cron_expr = f"{minute} {hour} * * *"
        elif frequency == 'weekly':
            time_str = request.form.get('time', '02:00')
            weekday = request.form.get('weekday', '0')
            try:
                hour, minute = time_str.split(':')
            except (ValueError, AttributeError):
                hour, minute = '2', '0'
            cron_expr = f"{minute} {hour} * * {weekday}"
        elif frequency == 'monthly':
            time_str = request.form.get('time', '02:00')
            day_of_month = request.form.get('day_of_month', '1')
            try:
                hour, minute = time_str.split(':')
            except (ValueError, AttributeError):
                hour, minute = '2', '0'
            cron_expr = f"{minute} {hour} {day_of_month} * *"
        else:
            cron_expr = 'disabled'

        if 'schedules' not in config:
            config['schedules'] = {}

        config['schedules'][db_type] = cron_expr
        save_config(config)

        # 更新 crontab
        update_crontab()

    except (ValueError, TypeError) as e:
        print(f"保存设置时出错: {e}")
        pass

    return redirect(url_for('index'))

@app.route('/download/<filename>')
def download_backup(filename):
    """下载指定的备份文件。"""
    # 安全检查，防止路径遍历攻击
    if '..' in filename or filename.startswith('/'):
        return "非法请求", 400
    return send_from_directory(BACKUP_DIR, filename, as_attachment=True)

@app.route('/delete_backup/<filename>', methods=['POST'])
def delete_backup(filename):
    """删除指定的备份文件。"""
    if '..' in filename or filename.startswith('/'):
        return "非法请求", 400
    try:
        os.remove(os.path.join(BACKUP_DIR, filename))
    except OSError:
        pass # 文件可能已被删除
    return redirect(url_for('index'))

@app.route('/download_log/<filename>')
def download_log(filename):
    """提供日志文件下载功能。"""
    # 安全检查：确保文件名不包含路径遍历字符
    if '..' in filename or filename.startswith('/'):
        return "Invalid filename", 400
    
    log_dir = os.path.join(BACKUP_DIR, 'logs', 'details')
    
    # 检查文件是否存在
    if not os.path.exists(os.path.join(log_dir, filename)):
        return "File not found", 404
        
    return send_from_directory(log_dir, filename, as_attachment=True)

@app.route('/api/log/<filename>')
def get_log_content(filename):
    """获取并返回指定日志文件的内容。"""
    if '..' in filename or filename.startswith('/'):
        return jsonify({'error': 'Invalid filename'}), 400

    log_dir = os.path.join(BACKUP_DIR, 'logs', 'details')
    log_file_path = os.path.join(log_dir, filename)

    if not os.path.exists(log_file_path):
        return jsonify({'error': 'File not found'}), 404

    try:
        with open(log_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return jsonify({'content': content})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)
