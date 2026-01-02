# 数据库备份代理 (db-backup-agent)

这是一个轻量级的、通过 Web 界面管理的数据库备份工具，专为 PostgreSQL 和 MySQL 设计。它将复杂的备份策略和繁琐的命令行操作，简化为在浏览器中的几次点击。

## ✨ 主要功能

*   **Web 界面管理**: 提供简洁直观的 UI，无需记忆和输入复杂的命令行。
*   **支持多种数据库**: 同时支持 PostgreSQL 和 MySQL 的备份。
*   **灵活的备份计划**: 可按天、周、月设置自动备份计划，或随时手动触发。
*   **备份保留策略**: 可自定义备份文件的保留天数，自动删除旧备份，有效管理存储空间。
*   **详细的备份历史**: 清晰地记录每一次备份的执行时间、触发方式、状态（成功/失败）和结果信息。
*   **便捷的故障排查**: 对于失败的任务，可直接在页面上查看详细的错误日志，快速定位问题。
*   **多架构支持**: 完美支持 **x86_64 (amd64)** 和 **ARM64 (Apple Silicon, Raspberry Pi)**。

## 🏷️ 镜像标签说明

*   `latest`: **推荐**。同时支持 x86_64 和 ARM64 架构，Docker 会自动根据您的设备拉取正确的版本。
*   `x86-only`: **仅 x86_64**。这是旧版本的保留镜像，仅包含 x86 架构支持，不建议新用户使用。

## 🚀 快速开始

使用 `docker-compose` 是运行此应用的最简单方式。

创建一个名为 `docker-compose.yml` 的文件：

```yaml
version: '3.8'

services:
  db-backup-agent:
    image: tony5188/db-backup-agent:latest
    container_name: db-backup-agent
    restart: unless-stopped
    ports:
      - "5001:5001"
    volumes:
      - ./backups:/backups
    environment:
      # 设置您所在的时区，确保定时任务在正确的时间执行
      # 例如: Asia/Shanghai
      - TZ=Asia/Shanghai

volumes:
  backups:
```

在与 `docker-compose.yml` 文件相同的目录下，创建一个名为 `backups` 的文件夹。这个文件夹将用于持久化存储所有的备份文件和应用的配置文件。

运行以下命令启动应用：

```bash
docker-compose up -d
```

启动成功后，在浏览器中访问 `http://<你的服务器IP>:5001` 即可开始使用。

## ⚙️ 配置

*   **端口**: 应用默认在容器内的 `5001` 端口运行。您可以根据需要在 `docker-compose.yml` 中映射到主机的其他端口。
*   **数据卷**:
    *   `./backups:/backups`: 这是 **必须** 的。它将主机上的 `backups` 目录挂载到容器的 `/backups` 目录。所有的数据库备份文件、配置文件 (`config.json`) 和日志文件都将存储在这里，从而确保在容器重启或更新后数据不会丢失。
*   **时区 (TZ)**: 强烈建议设置 `TZ` 环境变量。将其设置为您所在的时区（例如 `Asia/Shanghai`），可以确保您在网页上设置的定时备份任务在您预期的时间被准确触发。

## 🛠️ 构建与开发 (高级)

如果您希望自己构建镜像，可以使用本项目提供的脚本进行多架构构建。

**构建命令**:

```bash
# 构建并推送到 Docker Hub (自动支持 amd64 和 arm64)
./build_and_push.sh tony5188/db-backup-agent:latest
```

该脚本会自动：
1.  检测目标架构。
2.  并行构建 `linux/amd64` 和 `linux/arm64` 镜像。
3.  推送到 Docker Hub 并合并为一个 Tag。

### 架构支持详情

*   **x86_64 (amd64)**: 使用 Oracle 官方 MySQL 客户端 + PostgreSQL 官方客户端。
*   **ARM64**: 使用 MariaDB 客户端 (兼容 MySQL) + PostgreSQL 官方客户端。

## 📝 许可证

MIT License
