from flask import Flask, render_template, request, redirect, url_for, jsonify, send_from_directory, flash, make_response
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import sys
import json
import os
import subprocess
import uuid
import sqlite3
import hashlib
from datetime import datetime, timedelta

import re

# 导入数据库迁移模块
from migrate_db import ensure_v22_tables

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this-in-production'  # 生产环境请更改此密钥

# 配置Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = '请先登录以访问此页面'

# 获取项目根目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
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

# 在应用启动时初始化数据库和配置表
init_db()
sys.path.insert(0, BASE_DIR)
from config_manager import init_config_tables
init_config_tables()

# 初始化备份锁表
from backup_lock import init_backup_lock_table
init_backup_lock_table()

# --- 辅助函数 ---

def load_config():
    """从数据库加载配置"""
    try:
        sys.path.insert(0, BASE_DIR)
        from config_manager import get_all_config
        return get_all_config()
    except Exception as e:
        print(f"从数据库加载配置失败: {str(e)}")
        # 返回默认配置
        return {
            "postgresql": [],
            "mysql": [],
            "retention_days": {"postgresql": 7, "mysql": 7},
            "schedules": {},
            "notifications": {
                'enabled': False,
                'on_success': True,
                'on_failure': True,
                'email': {
                    'enabled': False,
                    'smtp_server': '',
                    'smtp_port': 587,
                    'use_tls': True,
                    'username': '',
                    'password': '',
                    'from_address': '',
                    'recipients': []
                },
                'wechat': {
                    'enabled': False,
                    'corp_id': '',
                    'corp_secret': '',
                    'agent_id': '',
                    'to_users': '@all'
                }
            }
        }

def save_config(config):
    """保存配置到数据库（已废弃，保留向后兼容）"""
    # 不再保存到文件，所有配置通过数据库管理
    pass

def update_crontab():
    """从数据库读取计划并更新系统的 crontab。"""
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


def load_backup_history():
    """从数据库加载备份历史日志。"""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("backup_logger", "/app/backup_logger.py")
        backup_logger = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backup_logger)

        db_history = backup_logger.get_recent_backups(limit=50)

        # 转换数据库格式为前端需要的格式
        formatted_history = []
        for record in db_history:
            formatted_history.append({
                'timestamp': record['created_at'],
                'db_type': record['db_type'],
                'trigger': record['trigger_type'],
                'status': record['status'],
                'message': record['message'],
                'log_file': record.get('log_file')
            })
        return formatted_history
    except Exception as e:
        print(f"从数据库加载备份历史失败: {str(e)}")
        return []


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
    db_type = request.form.get('type')
    edit_id = request.form.get('edit_id')  # 获取编辑ID

    if db_type in ['postgresql', 'mysql']:
        sys.path.insert(0, BASE_DIR)
        from config_manager import add_database_connection, update_database_connection

        host = request.form.get('host')
        port = request.form.get('port')
        user = request.form.get('user')
        password = request.form.get('password')
        db_name = request.form.get('db')

        if edit_id:
            # 编辑模式:更新现有配置
            # edit_id 格式: "postgresql-uuid" 或 "mysql-uuid"
            parts = edit_id.split('-', 1)
            if len(parts) == 2:
                edit_type, actual_id = parts
                if edit_type == db_type:
                    update_database_connection(actual_id, db_type, host, port, user, password, db_name)
        else:
            # 新增模式
            add_database_connection(db_type, host, port, user, password, db_name)

    return redirect(url_for('index'))

@app.route('/delete_db/<db_type>/<db_id>', methods=['GET', 'POST'])
def delete_db(db_type, db_id):
    """根据ID删除一个数据库配置。"""
    sys.path.insert(0, BASE_DIR)
    from config_manager import delete_database_connection
    delete_database_connection(db_id)
    return redirect(url_for('index'))

@app.route('/get_db/<db_type>/<db_id>')
@login_required
def get_db(db_type, db_id):
    """获取指定数据库配置的详情,用于编辑。"""
    sys.path.insert(0, BASE_DIR)
    from config_manager import get_database_connection
    db = get_database_connection(db_id)
    if db:
        return jsonify(db)
    return jsonify({'error': 'Database not found'}), 404

@app.route('/backup_now/<db_type>', methods=['POST'])
def backup_now(db_type):
    """触发一次指定数据库类型的手动备份（备份所有数据库）。"""
    config = load_config()
    task_status = '未启动 (未配置)'

    try:
        # 检查备份锁
        sys.path.insert(0, BASE_DIR)
        from backup_lock import is_backup_locked

        if is_backup_locked(db_type):
            lock_info = None
            try:
                from backup_lock import get_backup_lock_info
                lock_info = get_backup_lock_info(db_type)
            except:
                pass

            if lock_info and lock_info.get('locked_at'):
                locked_time = lock_info['locked_at']
                if isinstance(locked_time, str):
                    locked_time = locked_time.split('.')[0]  # 去掉微秒
                return jsonify({
                    'status': 'error',
                    'message': f'{db_type} 备份任务正在运行中，请等待完成后再试',
                    'locked_at': locked_time
                }), 409  # 409 Conflict
            else:
                return jsonify({
                    'status': 'error',
                    'message': f'{db_type} 备份任务正在运行中，请等待完成后再试'
                }), 409

        if db_type == 'postgresql' and config.get('postgresql') and len(config.get('postgresql', [])) > 0:
            # 使用 shell 在后台运行
            subprocess.Popen(
                '/usr/local/bin/backup.sh postgresql 手动 >/dev/null 2>&1 &',
                shell=True,
                start_new_session=True
            )
            task_status = '已启动'
        elif db_type == 'mysql' and config.get('mysql') and len(config.get('mysql', [])) > 0:
            subprocess.Popen(
                '/usr/local/bin/backup.sh mysql 手动 >/dev/null 2>&1 &',
                shell=True,
                start_new_session=True
            )
            task_status = '已启动'

        return jsonify({'status': 'success', 'task': task_status})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/backup_single/<db_type>/<db_id>', methods=['POST'])
def backup_single(db_type, db_id):
    """触发单个数据库的手动备份。"""
    config = load_config()
    task_status = '未启动 (未配置)'

    try:
        # 检查备份锁
        sys.path.insert(0, BASE_DIR)
        from backup_lock import is_backup_locked

        if is_backup_locked(db_type):
            lock_info = None
            try:
                from backup_lock import get_backup_lock_info
                lock_info = get_backup_lock_info(db_type)
            except:
                pass

            if lock_info and lock_info.get('locked_at'):
                locked_time = lock_info['locked_at']
                if isinstance(locked_time, str):
                    locked_time = locked_time.split('.')[0]  # 去掉微秒
                return jsonify({
                    'status': 'error',
                    'message': f'{db_type} 备份任务正在运行中，请等待完成后再试',
                    'locked_at': locked_time
                }), 409
            else:
                return jsonify({
                    'status': 'error',
                    'message': f'{db_type} 备份任务正在运行中，请等待完成后再试'
                }), 409

        if db_type == 'postgresql':
            # 检查是否配置了该数据库
            if config.get('postgresql'):
                db_exists = any(db.get('id') == db_id for db in config['postgresql'])
                if db_exists:
                    subprocess.Popen(
                        f'/usr/local/bin/backup.sh postgresql 手动 {db_id} >/dev/null 2>&1 &',
                        shell=True,
                        start_new_session=True
                    )
                    task_status = '已启动'
                else:
                    task_status = '数据库不存在'
        elif db_type == 'mysql':
            if config.get('mysql'):
                db_exists = any(db.get('id') == db_id for db in config['mysql'])
                if db_exists:
                    subprocess.Popen(
                        f'/usr/local/bin/backup.sh mysql 手动 {db_id} >/dev/null 2>&1 &',
                        shell=True,
                        start_new_session=True
                    )
                    task_status = '已启动'
                else:
                    task_status = '数据库不存在'

        return jsonify({'status': 'success', 'task': task_status})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/save_settings', methods=['POST'])
def save_settings():
    """保存单个数据库类型的计划设置。"""
    db_type = request.form.get('db_type', '')

    if not db_type or db_type not in ['postgresql', 'mysql']:
        return redirect(url_for('index'))

    try:
        sys.path.insert(0, BASE_DIR)
        from config_manager import save_backup_schedule

        # 保存当前数据库类型的保留天数
        retention_days = int(request.form.get('retention_days', 7))

        frequency = request.form.get('frequency', 'disabled')

        if frequency == 'disabled':
            schedule_type = 'disabled'
            cron_expr = ''
        elif frequency == 'daily':
            schedule_type = 'daily'
            time_str = request.form.get('time', '02:00')
            try:
                hour, minute = time_str.split(':')
            except (ValueError, AttributeError):
                hour, minute = '2', '0'
            cron_expr = f"{minute} {hour} * * *"
        elif frequency == 'weekly':
            schedule_type = 'weekly'
            time_str = request.form.get('time', '02:00')
            weekday = request.form.get('weekday', '0')
            try:
                hour, minute = time_str.split(':')
            except (ValueError, AttributeError):
                hour, minute = '2', '0'
            cron_expr = f"{minute} {hour} * * {weekday}"
        elif frequency == 'monthly':
            schedule_type = 'monthly'
            time_str = request.form.get('time', '02:00')
            day_of_month = request.form.get('day_of_month', '1')
            try:
                hour, minute = time_str.split(':')
            except (ValueError, AttributeError):
                hour, minute = '2', '0'
            cron_expr = f"{minute} {hour} {day_of_month} * *"
        else:
            schedule_type = 'disabled'
            cron_expr = ''

        # 保存到数据库
        save_backup_schedule(db_type, schedule_type, cron_expr, retention_days)

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


# --- 通知配置路由 ---

@app.route('/notifications')
@login_required
def notifications():
    """通知配置页面"""
    config = load_config()
    notifications_config = config.get('notifications', {})

    # DEBUG: 记录实际传递给模板的值
    app.logger.info(f"DEBUG notifications route: enabled={notifications_config.get('enabled')}, type={type(notifications_config.get('enabled'))}")
    app.logger.info(f"DEBUG notifications route: on_success={notifications_config.get('on_success')}, on_failure={notifications_config.get('on_failure')}")

    # 禁用浏览器缓存
    response = make_response(render_template('notifications.html', notifications=notifications_config))
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'

    return response


@app.route('/notifications/debug')
@login_required
def debug_notifications():
    """通知配置调试页面"""
    sys.path.insert(0, BASE_DIR)
    from config_manager import get_notification_config, get_db_connection

    # 获取数据库原始值
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id, enabled, on_success, on_failure FROM notification_config ORDER BY id DESC LIMIT 1')
    row = cursor.fetchone()
    db_raw = dict(row) if row else {'enabled': 0, 'on_success': 0, 'on_failure': 0, 'enabled_type': 'int'}
    db_raw['enabled_type'] = type(db_raw['enabled']).__name__
    conn.close()

    # 获取配置
    config = get_notification_config()
    config['enabled_type'] = type(config['enabled']).__name__

    return render_template('debug_notifications.html', db_raw=db_raw, config=config)

@app.route('/changelog')
@login_required
def changelog():
    """版本更新说明页面"""
    return render_template('changelog.html')


@app.route('/notifications/save', methods=['POST'])
def save_notifications():
    """保存通知配置（保留以兼容旧版本）"""
    return save_notifications_all()


@app.route('/notifications/save/global', methods=['POST'])
def save_global_notification():
    """保存全局通知配置"""
    try:
        sys.path.insert(0, BASE_DIR)
        from config_manager import save_global_notification_config

        # 获取表单数据（checkbox 选中时为 'on'，未选中时不存在）
        enabled = request.form.get('enabled') is not None
        on_success = request.form.get('on_success') is not None
        on_failure = request.form.get('on_failure') is not None

        # DEBUG: 记录接收到的表单数据
        app.logger.info(f"DEBUG save_global_notification: form.keys() = {list(request.form.keys())}")
        app.logger.info(f"DEBUG save_global_notification: enabled={enabled}, on_success={on_success}, on_failure={on_failure}")
        app.logger.info(f"DEBUG save_global_notification: request.form.get('enabled') = {request.form.get('enabled')}")

        # 保存到数据库
        save_global_notification_config(enabled, on_success, on_failure)

        flash('全局通知设置已保存', 'success')
        return redirect(url_for('notifications'))

    except Exception as e:
        app.logger.error(f"ERROR save_global_notification: {str(e)}")
        flash(f'保存配置失败: {str(e)}', 'danger')
        return redirect(url_for('notifications'))


@app.route('/notifications/save/email', methods=['POST'])
def save_email_notification():
    """保存邮件通知配置"""
    try:
        sys.path.insert(0, BASE_DIR)
        from config_manager import save_email_notification_config

        # 邮件配置
        email_config = {
            'enabled': request.form.get('email_enabled') is not None,
            'smtp_server': request.form.get('smtp_server', ''),
            'smtp_port': int(request.form.get('smtp_port', 587) or 587),
            'use_tls': request.form.get('use_tls') is not None,
            'username': request.form.get('email_username', ''),
            'password': request.form.get('email_password', ''),
            'from_address': request.form.get('from_address', ''),
            'recipients': [r.strip() for r in request.form.get('recipients', '').split(',') if r.strip()]
        }

        # 保存到数据库
        save_email_notification_config(email_config)

        flash('邮件通知设置已保存', 'success')
        return redirect(url_for('notifications'))

    except Exception as e:
        flash(f'保存配置失败: {str(e)}', 'danger')
        return redirect(url_for('notifications'))


@app.route('/notifications/save/wechat', methods=['POST'])
def save_wechat_notification():
    """保存企业微信通知配置"""
    try:
        sys.path.insert(0, BASE_DIR)
        from config_manager import save_wechat_notification_config

        # 企业微信配置
        wechat_config = {
            'enabled': request.form.get('wechat_enabled') is not None,
            'corp_id': request.form.get('corp_id', ''),
            'corp_secret': request.form.get('corp_secret', ''),
            'agent_id': request.form.get('agent_id', ''),
            'to_users': request.form.get('to_users', '@all')
        }

        # 保存到数据库
        save_wechat_notification_config(wechat_config)

        flash('企业微信通知设置已保存', 'success')
        return redirect(url_for('notifications'))

    except Exception as e:
        flash(f'保存配置失败: {str(e)}', 'danger')
        return redirect(url_for('notifications'))


def save_notifications_all():
    """保存所有通知配置（旧版兼容）"""
    try:
        sys.path.insert(0, BASE_DIR)
        from config_manager import save_notification_config

        # 获取表单数据（checkbox 选中时为 'on'，未选中时不存在）
        enabled = request.form.get('enabled') is not None
        on_success = request.form.get('on_success') is not None
        on_failure = request.form.get('on_failure') is not None

        # 邮件配置
        email_enabled = request.form.get('email_enabled') is not None
        email_config = {
            'enabled': email_enabled,
            'smtp_server': request.form.get('smtp_server', ''),
            'smtp_port': int(request.form.get('smtp_port', 587) or 587),
            'use_tls': request.form.get('use_tls') is not None,
            'username': request.form.get('email_username', ''),
            'password': request.form.get('email_password', ''),
            'from_address': request.form.get('from_address', ''),
            'recipients': [r.strip() for r in request.form.get('recipients', '').split(',') if r.strip()]
        }

        # 企业微信配置
        wechat_enabled = request.form.get('wechat_enabled') is not None
        wechat_config = {
            'enabled': wechat_enabled,
            'corp_id': request.form.get('corp_id', ''),
            'corp_secret': request.form.get('corp_secret', ''),
            'agent_id': request.form.get('agent_id', ''),
            'to_users': request.form.get('to_users', '@all')
        }

        # 保存到数据库
        save_notification_config(enabled, on_success, on_failure, email_config, wechat_config)

        flash('通知配置已保存', 'success')
        return redirect(url_for('notifications'))

    except Exception as e:
        flash(f'保存配置失败: {str(e)}', 'danger')
        return redirect(url_for('notifications'))


@app.route('/notifications/test', methods=['POST'])
def test_notification():
    """测试通知发送"""
    config = load_config()
    notifications_config = config.get('notifications', {})

    test_type = request.form.get('test_type')  # 'email' 或 'wechat'

    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("notifications", "/app/notifications.py")
        notifications = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(notifications)

        if test_type == 'email':
            email_config = notifications_config.get('email', {})

            # 检查基本配置是否完整
            if not email_config.get('smtp_server') or not email_config.get('username'):
                return jsonify({'success': False, 'message': '邮件配置不完整，请先填写 SMTP 服务器和用户名'})

            # 如果未启用，允许测试但给出提示
            if not email_config.get('enabled'):
                print("警告：邮件通知当前未启用，但正在发送测试邮件")

            notifier = notifications.EmailNotifier(email_config)
            success = notifier.send(
                '数据库备份系统测试通知',
                '这是一封测试邮件，用于验证邮件通知配置是否正确。\n\n如果您收到这封邮件，说明配置成功！',
                is_html=False
            )

            if success:
                return jsonify({'success': True, 'message': '测试邮件已发送'})
            else:
                return jsonify({'success': False, 'message': '发送测试邮件失败'})

        elif test_type == 'wechat':
            wechat_config = notifications_config.get('wechat', {})

            app.logger.info(f"企业微信测试，配置: {wechat_config}")

            # 检查基本配置是否完整
            if not wechat_config.get('corp_id') or not wechat_config.get('corp_secret') or not wechat_config.get('agent_id'):
                app.logger.error("企业微信配置不完整")
                return jsonify({'success': False, 'message': '企业微信配置不完整，请先填写 Corp ID、Secret 和 Agent ID'})

            # 如果未启用，允许测试但给出提示
            if not wechat_config.get('enabled'):
                app.logger.warning("企业微信通知当前未启用，但正在发送测试消息")

            app.logger.info("开始创建企业微信通知器...")

            # 设置 notifications 模块的 logger 使用 Flask 的 logger
            notifications.logger = app.logger

            notifier = notifications.WeChatNotifier(wechat_config)

            app.logger.info("开始发送测试消息...")
            success = notifier.send(
                '数据库备份系统测试通知',
                '这是一条测试消息，用于验证企业微信通知配置是否正确。\n\n如果您收到这条消息，说明配置成功！'
            )

            app.logger.info(f"发送结果: {success}")

            if success:
                return jsonify({'success': True, 'message': '测试消息已发送'})
            else:
                return jsonify({'success': False, 'message': '发送测试消息失败'})

    except Exception as e:
        app.logger.error(f"测试通知异常: {str(e)}")
        import traceback
        app.logger.error(traceback.format_exc())
        return jsonify({'success': False, 'message': f'测试失败: {str(e)}'})


# --- 备份历史和统计 API ---

@app.route('/api/backup/history')
@login_required
def api_backup_history():
    """获取备份历史记录（支持分页和过滤）"""
    try:
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)
        db_type = request.args.get('db_type')
        status = request.args.get('status')

        sys.path.insert(0, BASE_DIR)
        from backup_logger import get_backup_history

        history = get_backup_history(
            limit=limit,
            offset=offset,
            db_type=db_type,
            status=status
        )

        return jsonify({'success': True, 'data': history})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/backup/statistics')
@login_required
def api_backup_statistics():
    """获取备份统计信息"""
    try:
        days = request.args.get('days', 7, type=int)

        sys.path.insert(0, BASE_DIR)
        from backup_logger import get_backup_statistics

        stats = get_backup_statistics(days=days)

        return jsonify({'success': True, 'data': stats})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/system/logs')
@login_required
def api_system_logs():
    """获取系统日志"""
    try:
        limit = request.args.get('limit', 100, type=int)
        log_type = request.args.get('type', None)
        category = request.args.get('category', None)

        sys.path.insert(0, BASE_DIR)
        from system_logger import get_logs

        logs = get_logs(limit=limit, log_type=log_type, category=category)

        return jsonify({'success': True, 'data': logs})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# --- 数据库连接测试和列表查询 API ---

@app.route('/api/test_connection', methods=['POST'])
@login_required
def test_connection():
    """测试数据库连接"""
    try:
        data = request.get_json()
        db_type = data.get('db_type')
        host = data.get('host')
        port = int(data.get('port', 5432 if db_type == 'postgresql' else 3306))
        user = data.get('user')
        password = data.get('password')
        database = data.get('database', '')

        if db_type == 'postgresql':
            # 测试 PostgreSQL 连接
            try:
                import psycopg2
                conn_params = {
                    'host': host,
                    'port': port,
                    'user': user,
                    'password': password,
                    'connect_timeout': 5
                }
                # 默认连接到 postgres 数据库
                if database:
                    conn_params['dbname'] = database
                else:
                    conn_params['dbname'] = 'postgres'

                conn = psycopg2.connect(**conn_params)
                conn.close()
                return jsonify({'success': True, 'message': '连接成功'})
            except Exception as e:
                return jsonify({'success': False, 'message': f'连接失败: {str(e)}'})

        elif db_type == 'mysql':
            # 测试 MySQL 连接
            try:
                import pymysql
                conn_params = {
                    'host': host,
                    'port': port,
                    'user': user,
                    'password': password,
                    'connect_timeout': 5
                }
                if database:
                    conn_params['database'] = database

                conn = pymysql.connect(**conn_params)
                conn.close()
                return jsonify({'success': True, 'message': '连接成功'})
            except Exception as e:
                return jsonify({'success': False, 'message': f'连接失败: {str(e)}'})

        return jsonify({'success': False, 'message': '不支持的数据库类型'})

    except Exception as e:
        return jsonify({'success': False, 'message': f'测试连接时出错: {str(e)}'}), 500


@app.route('/api/get_databases', methods=['POST'])
@login_required
def get_databases():
    """获取服务器上的数据库列表"""
    try:
        data = request.get_json()
        db_type = data.get('db_type')
        host = data.get('host')
        port = int(data.get('port', 5432 if db_type == 'postgresql' else 3306))
        user = data.get('user')
        password = data.get('password')

        databases = []

        if db_type == 'postgresql':
            # 获取 PostgreSQL 数据库列表
            try:
                import psycopg2
                conn = psycopg2.connect(
                    host=host,
                    port=port,
                    user=user,
                    password=password,
                    dbname='postgres',  # 默认连接到 postgres 数据库
                    connect_timeout=5
                )
                conn.autocommit = True
                cursor = conn.cursor()

                # 查询所有数据库（排除系统模板数据库，但保留 postgres）
                cursor.execute("""
                    SELECT datname
                    FROM pg_database
                    WHERE datistemplate = false
                    ORDER BY datname
                """)

                databases = [row[0] for row in cursor.fetchall()]

                # 在列表开头添加"所有数据库"选项
                databases.insert(0, '')

                cursor.close()
                conn.close()

                return jsonify({'success': True, 'databases': databases})

            except Exception as e:
                return jsonify({'success': False, 'message': f'获取数据库列表失败: {str(e)}'})

        elif db_type == 'mysql':
            # 获取 MySQL 数据库列表
            try:
                import pymysql
                conn = pymysql.connect(
                    host=host,
                    port=port,
                    user=user,
                    password=password,
                    connect_timeout=5
                )
                cursor = conn.cursor()

                # 查询所有数据库
                cursor.execute("SHOW DATABASES")

                # 过滤掉系统数据库
                system_databases = {'information_schema', 'performance_schema', 'mysql', 'sys'}
                databases = [row[0] for row in cursor.fetchall() if row[0] not in system_databases]
                databases.sort()  # 按名称排序

                # 在列表开头添加"所有数据库"选项
                databases.insert(0, '')

                cursor.close()
                conn.close()

                return jsonify({'success': True, 'databases': databases})

            except Exception as e:
                return jsonify({'success': False, 'message': f'获取数据库列表失败: {str(e)}'})

        return jsonify({'success': False, 'message': '不支持的数据库类型'})

    except Exception as e:
        return jsonify({'success': False, 'message': f'获取数据库列表时出错: {str(e)}'}), 500


if __name__ == '__main__':
    # 启动时自动检查并确保数据库表完整性
    print("\n" + "=" * 60)
    print("应用启动 - 检查数据库完整性")
    print("=" * 60)
    try:
        ensure_v22_tables()
    except Exception as e:
        print(f"⚠️  数据库完整性检查失败: {str(e)}")
        print("继续启动应用...")
    print("=" * 60 + "\n")

    app.run(host='0.0.0.0', port=5001, debug=True)
