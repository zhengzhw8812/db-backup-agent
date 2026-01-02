from flask import Flask, render_template, request, redirect, url_for, jsonify, send_from_directory
import json
import os
import subprocess
import uuid
from datetime import datetime, timedelta

import re

app = Flask(__name__)

CONFIG_FILE = os.path.join('/backups', 'config.json')
BACKUP_DIR = '/backups'

# --- 辅助函数 ---

def load_config():
    """加载配置文件，如果文件不存在或为空，则返回一个默认结构。"""
    if os.path.exists(CONFIG_FILE) and os.path.getsize(CONFIG_FILE) > 0:
        with open(CONFIG_FILE, 'r') as f:
            try:
                config = json.load(f)
                # 兼容旧版配置，确保 schedules 字典存在
                config.setdefault('schedules', {})
                return config
            except json.JSONDecodeError:
                pass  # 文件损坏或为空，返回默认值
    # 默认结构
    return {"postgresql": [], "mysql": [], "retention_days": 7, "schedules": {}}

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


HISTORY_LOG_FILE = os.path.join('/backups', 'backup_history.log')

def load_backup_history():
    """加载并解析备份历史日志。"""
    if not os.path.exists(HISTORY_LOG_FILE):
        return []
    
    history = []
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
            
    # 按时间倒序排序，然后只取前30条
    return sorted(history, key=lambda x: x['timestamp'], reverse=True)[:30]


# --- 路由 ---

@app.route('/')
def index():
    """主页，显示配置、备份列表和备份历史。"""
    config = load_config()
    # 确保关键字段存在
    config.setdefault('postgresql', [])
    config.setdefault('mysql', [])
    config.setdefault('retention_days', 7)
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

    backups_with_info = []
    one_week_ago = datetime.now() - timedelta(days=7)
    retention_days = config.get('retention_days', 7)

    for backup_file in backup_files:
        file_path = os.path.join(BACKUP_DIR, backup_file)
        creation_time = datetime.fromtimestamp(os.path.getmtime(file_path))
        
        # 只显示最近一周的备份
        if creation_time >= one_week_ago:
            deletion_time = creation_time + timedelta(days=retention_days)
            backups_with_info.append({
                'name': backup_file,
                'delete_time': deletion_time.strftime('%Y-%m-%d %H:%M:%S')
            })

    backup_history = load_backup_history()

    return render_template('index.html', config=config, backups=backups_with_info, schedules_ui=schedules_ui, humanized_schedules=humanized_schedules, backup_history=backup_history)

@app.route('/add_db', methods=['POST'])
def add_db():
    """添加一个新的数据库配置。"""
    config = load_config()
    db_type = request.form.get('type')
    
    if db_type in ['postgresql', 'mysql']:
        new_db = {
            "id": str(uuid.uuid4()), # 分配唯一ID
            "host": request.form.get('host'),
            "port": request.form.get('port'),
            "user": request.form.get('user'),
            "password": request.form.get('password')
        }
        if db_type == 'postgresql':
            new_db['db'] = request.form.get('db')
        elif db_type == 'mysql':
            new_db['db'] = request.form.get('db')
        
        config[db_type].append(new_db)
        save_config(config)
        
    return redirect(url_for('index'))

@app.route('/delete_db/<db_type>/<db_id>', methods=['POST'])
def delete_db(db_type, db_id):
    """根据ID删除一个数据库配置。"""
    config = load_config()
    if db_type in config and isinstance(config[db_type], list):
        # 通过ID过滤掉要删除的项
        config[db_type] = [db for db in config[db_type] if db.get('id') != db_id]
        save_config(config)
    return redirect(url_for('index'))

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
    """根据前端动态表单保存全局设置，并构建cron表达式。"""
    config = load_config()

    def _build_cron_from_form(db_prefix):
        """根据表单数据为指定数据库类型构建cron表达式。"""
        frequency = request.form.get(f'{db_prefix}_frequency')
        if not frequency or frequency == 'disabled':
            return 'disabled'

        time_str = request.form.get(f'{db_prefix}_time', '02:00')
        try:
            hour, minute = time_str.split(':')
        except (ValueError, AttributeError):
            hour, minute = '2', '0' # 默认值

        if frequency == 'daily':
            return f"{minute} {hour} * * *"
        elif frequency == 'weekly':
            weekday = request.form.get(f'{db_prefix}_weekday', '0') # 默认周日
            return f"{minute} {hour} * * {weekday}"
        elif frequency == 'monthly':
            day_of_month = request.form.get(f'{db_prefix}_day_of_month', '1') # 默认1号
            return f"{minute} {hour} {day_of_month} * *"
        
        return 'disabled'

    try:
        config['retention_days'] = int(request.form.get('retention_days'))
        
        if 'schedules' not in config:
            config['schedules'] = {}
            
        config['schedules']['postgresql'] = _build_cron_from_form('pg')
        config['schedules']['mysql'] = _build_cron_from_form('mysql')
        
        save_config(config)
        
        # 调用函数以立即更新 crontab
        update_crontab()
        
    except (ValueError, TypeError) as e:
        # 在实际应用中，这里最好有一个日志记录或闪现消息
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
