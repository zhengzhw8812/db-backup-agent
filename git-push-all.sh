#!/bin/bash
# 同时推送到 GitHub 和 Gitee 的脚本

echo "======================================"
echo "  同步推送到 GitHub 和 Gitee"
echo "======================================"
echo ""

# 推送到 GitHub
echo "📦 推送到 GitHub..."
git push origin main
if [ $? -eq 0 ]; then
    echo "✅ GitHub 推送成功"
else
    echo "❌ GitHub 推送失败"
    exit 1
fi

echo ""

# 推送到 Gitee
echo "📦 推送到 Gitee..."
git push gitee main
if [ $? -eq 0 ]; then
    echo "✅ Gitee 推送成功"
else
    echo "❌ Gitee 推送失败"
    exit 1
fi

echo ""
echo "======================================"
echo "✅ 所有平台推送完成！"
echo "======================================"
