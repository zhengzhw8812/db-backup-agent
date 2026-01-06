#!/usr/bin/env python3
"""测试通知配置流程"""
import sys
sys.path.insert(0, '/')

from config_manager import get_notification_config, get_db_connection

print("=" * 60)
print("通知配置调试测试")
print("=" * 60)

# 1. 检查数据库原始值
print("\n1. 数据库原始值:")
conn = get_db_connection()
cursor = conn.cursor()
cursor.execute('SELECT id, enabled, on_success, on_failure FROM notification_config ORDER BY id DESC LIMIT 1')
row = cursor.fetchone()
if row:
    row_dict = dict(row)
    print(f"   行数据: {row_dict}")
    print(f"   enabled = {row_dict['enabled']} (type: {type(row_dict['enabled']).__name__})")
else:
    print("   ❌ 没有找到记录")
conn.close()

# 2. 检查 get_notification_config 返回值
print("\n2. get_notification_config() 返回值:")
config = get_notification_config()
print(f"   enabled = {config['enabled']} (type: {type(config['enabled']).__name__})")
print(f"   on_success = {config['on_success']}")
print(f"   on_failure = {config['on_failure']}")

# 3. 模拟 Jinja2 模板条件
print("\n3. Jinja2 模板条件测试:")
enabled = config['enabled']
print(f"   模板代码: {{% if notifications.enabled %}}")
print(f"   实际值: notifications.enabled = {enabled}")
print(f"   条件结果: {bool(enabled)}")
if enabled:
    print(f"   HTML 输出: <input type=\"checkbox\" name=\"enabled\" id=\"enabled\" checked>")
    print(f"   ❌ 错误: 开关会显示为开启（蓝色）")
else:
    print(f"   HTML 输出: <input type=\"checkbox\" name=\"enabled\" id=\"enabled\">")
    print(f"   ✅ 正确: 开关会显示为关闭（灰色）")

# 4. 测试布尔转换
print("\n4. 布尔转换测试:")
test_values = [0, 1, False, True, "0", "1"]
for val in test_values:
    result = bool(val)
    print(f"   bool({val!r}) = {result}")

print("\n" + "=" * 60)
