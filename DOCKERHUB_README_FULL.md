# 数据库备份代理 (DB Backup Agent)

**v2版本发布啦，这个版本对前端页面进行了一次重构，更人性化！**

[中文](#中文) | [English](#english)

---

<a name="中文"></a>
## 中文说明

这是一个轻量级的、通过 Web 界面管理的数据库备份工具，专为 PostgreSQL 和 MySQL 设计。它将复杂的备份策略和繁琐的命令行操作，简化为在浏览器中的几次点击。

### 📸 界面预览

**v2 版本全新界面**

![主界面](https://raw.githubusercontent.com/zhengzhw8812/db-backup-agent/main/Images/screenshot.png)

现代化的界面设计，让备份管理更加轻松高效。

> **注意**: 此镜像支持多架构。Docker 会根据您的设备（x86_64 或 ARM64）自动拉取优化后的版本。

### ✨ 主要功能

*   **Web 界面管理**: 提供简洁直观的 UI，无需记忆和输入复杂的命令行。
*   **支持多种数据库**: 同时支持 **PostgreSQL** 和 **MySQL** (兼容 MariaDB) 的备份。
*   **灵活的备份计划**: 可按天、周、月设置自动备份计划，或随时手动触发。
*   **备份保留策略**: 可自定义备份文件的保留天数，自动删除旧备份，有效管理存储空间。
*   **详细的备份历史**: 清晰地记录每一次备份的执行时间、触发方式、状态（成功/失败）和结果信息。
*   **多架构支持**: 完美支持 **x86_64 (amd64)** 和 **ARM64 (Apple Silicon, Raspberry Pi)**。

### 🚀 快速开始

#### 使用 Docker Compose (推荐)

创建一个 `docker-compose.yml` 文件：

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
      # 必须: 持久化存储备份文件和配置
      - ./backups:/backups
    environment:
      # 设置时区，确保定时任务准时执行
      - TZ=Asia/Shanghai

volumes:
  backups:
```

在同一目录下创建一个名为 `backups` 的文件夹，然后运行：

```bash
docker-compose up -d
```

启动成功后，访问 Web 界面：`http://localhost:5001`

### 🏷️ 镜像标签说明

*   `latest`: **推荐**。同时支持 x86_64 和 ARM64 架构。
*   `x86-only`: **仅 x86_64**。这是旧版本的保留镜像，仅包含 x86 架构支持。

### ⚙️ 配置说明

*   **端口**: 默认为 `5001`。
*   **数据卷**: 必须挂载 `/backups` 目录，所有的数据库备份文件、配置文件 (`config.json`) 和日志文件都将存储在这里。
*   **时区 (TZ)**: 强烈建议设置 `TZ` 环境变量（如 `Asia/Shanghai`），否则定时任务可能会有时差。

### 🔗 相关链接

*   **GitHub 仓库**: [zhengzhw8812/db-backup-agent](https://github.com/zhengzhw8812/db-backup-agent)
*   **问题反馈**: [GitHub Issues](https://github.com/zhengzhw8812/db-backup-agent/issues)

---

<a name="english"></a>
## English Description

A lightweight, web-managed database backup agent for PostgreSQL and MySQL. It simplifies complex backup strategies into a few clicks in your browser.

### 📸 Interface Preview

**All-New v2 Interface**

![Main Dashboard](https://raw.githubusercontent.com/zhengzhw8812/db-backup-agent/main/Images/screenshot.png)

Modern interface design makes backup management easier and more efficient than ever.

> **Note**: This image supports multi-architecture. It will automatically pull the correct version for your device (x86_64 or ARM64).

### ✨ Features

*   **Web Interface**: Simple and intuitive UI, no need to remember complex CLI commands.
*   **Multi-Database Support**: Supports both **PostgreSQL** and **MySQL** (MariaDB compatible).
*   **Flexible Scheduling**: Schedule backups daily, weekly, or monthly via cron, or trigger manually.
*   **Retention Policy**: Automatically delete old backups to save storage space.
*   **History & Logs**: Detailed execution logs for troubleshooting.
*   **Multi-Arch**: Perfect support for **amd64** and **arm64** (Apple Silicon, Raspberry Pi).

### 🚀 Quick Start

#### Docker Compose

Create a `docker-compose.yml` file:

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
      # Required: Persist backups and config
      - ./backups:/backups
    environment:
      # Set your timezone for accurate scheduling
      - TZ=Asia/Shanghai

volumes:
  backups:
```

Create a `backups` directory in the same folder, then run:

```bash
docker-compose up -d
```

Access the dashboard at `http://localhost:5001`.

### 🏷️ Tags

*   `latest`: **Recommended**. Multi-arch support (amd64 + arm64).
*   `x86-only`: Legacy tag for x86_64 architecture only.

### ⚙️ Configuration

*   **Port**: Defaults to `5001`.
*   **Volumes**: Mount `/backups` to persist your data.
*   **Timezone**: Set `TZ` env var (e.g., `Asia/Shanghai`, `America/New_York`) to ensure cron jobs run at expected local times.

### 🔗 Links

*   **GitHub Repository**: [zhengzhw8812/db-backup-agent](https://github.com/zhengzhw8812/db-backup-agent)
*   **Report Issues**: [GitHub Issues](https://github.com/zhengzhw8812/db-backup-agent/issues)
