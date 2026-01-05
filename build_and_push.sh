#!/bin/bash

set -e

# 检查参数
if [ -z "$1" ]; then
    echo "用法: ./build_and_push.sh <image-name>"
    echo "示例: ./build_and_push.sh your-dockerhub-username/db-backup-agent:latest"
    exit 1
fi

IMAGE_NAME=$1

# 检查是否登录了 Docker
echo "正在检查 Docker 登录状态..."
if ! docker system info | grep -q "Username"; then
    echo "警告: 似乎未登录 Docker Hub。如果没有登录，推送可能会失败。"
    echo "请运行 'docker login' 进行登录。"
    echo "按 Ctrl+C 取消，或按回车键继续..."
    read
fi

# 检查 buildx 是否可用
if ! docker buildx version > /dev/null 2>&1; then
    echo "错误: 未找到 docker buildx。请确保您安装了 Docker Desktop 或最新版本的 Docker。"
    exit 1
fi

# 创建并使用一个新的 builder 实例 (如果不存在)
# 多架构构建通常需要 docker-container 驱动
BUILDER_NAME="multi-arch-builder"
if ! docker buildx inspect $BUILDER_NAME > /dev/null 2>&1; then
    echo "创建一个新的 buildx builder: $BUILDER_NAME"
    docker buildx create --name $BUILDER_NAME --driver docker-container --use
    docker buildx inspect $BUILDER_NAME --bootstrap
else
    echo "使用现有的 buildx builder: $BUILDER_NAME"
    docker buildx use $BUILDER_NAME
fi

echo "========================================================"
echo "开始构建并推送镜像: $IMAGE_NAME"
echo "目标架构: linux/amd64, linux/arm64"
echo "========================================================"

# 执行构建和推送
docker buildx build \
    --platform linux/amd64,linux/arm64 \
    -t "$IMAGE_NAME" \
    --push \
    .

echo "========================================================"
echo "成功! 镜像已推送到 Docker Hub。"
echo "您可以使用以下命令拉取:"
echo "docker pull $IMAGE_NAME"
echo "========================================================"
