#!/bin/bash

echo "=== 测试通知页面 HTML 输出 ==="
echo ""

# 1. 检查数据库中的实际值
echo "1. 数据库中的值:"
docker exec db-backup-test sqlite3 /backups/users.db "SELECT id, enabled, on_success, on_failure FROM notification_config ORDER BY id DESC LIMIT 1;"
echo ""

# 2. 通过 config_manager 获取的值
echo "2. config_manager.get_notification_config() 返回的值:"
docker exec db-backup-test python3 << 'EOF'
import sys
sys.path.insert(0, '/')
from config_manager import get_notification_config
config = get_notification_config()
print(f"enabled = {config['enabled']} (type: {type(config['enabled']).__name__})")
print(f"on_success = {config['on_success']} (type: {type(config['on_success']).__name__})")
print(f"on_failure = {config['on_failure']} (type: {type(config['on_failure']).__name__})")
print(f"email enabled = {config['email']['enabled']}")
print(f"wechat enabled = {config['wechat']['enabled']}")
EOF
echo ""

# 3. 测试模板渲染逻辑
echo "3. 模板条件测试:"
docker exec db-backup-test python3 << 'EOF'
enabled = False
if enabled:
    print("enabled=False 时，条件 '{% if notifications.enabled %}' 结果: True (会添加 checked)")
else:
    print("enabled=False 时，条件 '{% if notifications.enabled %}' 结果: False (不会添加 checked)")

enabled = True
if enabled:
    print("enabled=True 时，条件 '{% if notifications.enabled %}' 结果: True (会添加 checked)")
else:
    print("enabled=True 时，条件 '{% if notifications.enabled %}' 结果: False (不会添加 checked)")
EOF
echo ""

# 4. 获取实际渲染的 HTML
echo "4. 检查实际 HTML 中 checkbox 的状态:"
echo "   访问 http://localhost:5001/notifications 并查看源代码"
echo "   搜索 'id=\"enabled\"' 查看是否有 'checked' 属性"
echo ""

echo "=== 测试完成 ==="
