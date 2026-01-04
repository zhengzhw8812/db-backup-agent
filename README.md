# 数据库备份代理 (db-backup-agent)

一个轻量级、易部署的数据库备份管理工具，通过简洁的 Web 界面实现 PostgreSQL 和 MySQL 的自动化备份管理。无需编写复杂的脚本或记忆繁琐的命令行，即可在浏览器中轻松完成数据库备份策略的配置与管理。

## ✨ 主要功能

### 🎯 核心特性

- **Web 可视化管理** - 通过直观的 Web 界面完成所有操作，无需命令行交互
- **多数据库支持** - 同时支持 PostgreSQL 和 MySQL 数据库备份
- **灵活的备份策略** - 支持按天、周、月设置自动备份计划，亦可随时手动触发
- **智能保留策略** - 自定义备份文件保留天数，自动清理过期备份，节省存储空间
- **完整的备份记录** - 详细记录每次备份的执行时间、触发方式、状态和结果
- **便捷的故障排查** - 失败任务提供详细错误日志，快速定位问题根源
- **多平台兼容** - 支持 **x86_64 (amd64)** 和 **ARM64** 架构（如 Apple Silicon、树莓派）

## 📦 镜像标签

| 标签 | 说明 | 推荐度 |
|------|------|--------|
| `latest` | 同时支持 x86_64 和 ARM64 架构，Docker 自动识别设备架构并拉取对应版本 | ⭐ 推荐 |
| `x86-only` | 仅支持 x86_64 架构的旧版本保留镜像 | 不推荐新用户使用 |

## 🚀 快速开始

### 1. 创建配置文件

创建 `docker-compose.yml` 文件：

```yaml
version: '3.8'

services:
  db-backup-agent:
    image: {your-dockerhub-username}/db-backup-agent:latest
    container_name: db-backup-agent
    restart: unless-stopped
    ports:
      - "5001:5001"
    volumes:
      - ./backups:/backups
    environment:
      # 设置时区，确保定时任务在正确的时间执行
      - TZ=Asia/Shanghai

volumes:
  backups:
```

### 2. 启动服务

在 `docker-compose.yml` 同目录下创建 `backups` 文件夹（用于持久化存储备份文件和配置），然后执行：

```bash
docker-compose up -d
```

### 3. 访问应用

在浏览器中打开 `http://<你的服务器IP>:5001` 即可开始使用。

## 🖼️ 界面预览

### 注册页面

首次访问时需要创建管理员账号：

![注册页面](Images/register.png)

![注册页面](Images/register2.png)

### 主界面

登录后可管理数据库连接和备份任务：

![主界面](Images/screenshot.png)

## ⚙️ 配置说明

| 配置项 | 说明 | 必填 |
|--------|------|------|
| **端口映射** | 默认 `5001:5001`，可根据需要修改主机端口 | 否 |
| **数据卷** | `./backups:/backups` - 持久化存储备份文件和配置数据 | **是** |
| **时区 (TZ)** | 建议设置，如 `Asia/Shanghai`，确保定时任务准确执行 | 推荐 |

> 💡 **提示**: 数据卷映射是必须的，否则容器重启后所有配置和备份文件都会丢失。

## 🛠️ 构建镜像（高级用户）

如需自行构建镜像，可使用项目提供的多架构构建脚本：

```bash
# 构建并推送至 Docker Hub（自动支持 amd64 和 arm64）
./build_and_push.sh {your-dockerhub-username}/db-backup-agent:latest
```

脚本会自动完成以下步骤：
1. 检测目标架构
2. 并行构建 `linux/amd64` 和 `linux/arm64` 镜像
3. 推送至 Docker Hub 并合并为单个 Tag

### 架构差异

| 架构 | MySQL 客户端 | PostgreSQL 客户端 |
|------|--------------|-------------------|
| x86_64 | Oracle 官方客户端 | PostgreSQL 官方客户端 |
| ARM64 | MariaDB 客户端（兼容 MySQL） | PostgreSQL 官方客户端 |

## 📄 开源协议

本项目基于 [MIT License](LICENSE) 开源。

---

# Database Backup Agent (db-backup-agent)

A lightweight, easy-to-deploy database backup management tool that provides automated backup management for PostgreSQL and MySQL through a clean Web interface. No complex scripts or command-line operations required – configure and manage your database backup strategies with just a few clicks in your browser.

## ✨ Key Features

### 🎯 Core Features

- **Web-based Management** - Complete all operations through an intuitive web interface, no command line interaction needed
- **Multi-Database Support** - Supports both PostgreSQL and MySQL database backups
- **Flexible Backup Schedules** - Set up automatic backup plans by day, week, or month, or trigger manual backups anytime
- **Smart Retention Policy** - Customize backup file retention days, automatically clean up expired backups to save storage space
- **Complete Backup Records** - Detailed logs of execution time, trigger method, status, and results for each backup
- **Easy Troubleshooting** - Failed tasks provide detailed error logs for quick problem diagnosis
- **Multi-Platform Support** - Supports **x86_64 (amd64)** and **ARM64** architectures (e.g., Apple Silicon, Raspberry Pi)

## 📦 Image Tags

| Tag | Description | Recommendation |
|-----|-------------|----------------|
| `latest` | Supports both x86_64 and ARM64 architectures, Docker automatically pulls the correct version for your device | ⭐ Recommended |
| `x86-only` | Legacy version for x86_64 architecture only | Not recommended for new users |

## 🚀 Quick Start

### 1. Create Configuration File

Create a `docker-compose.yml` file:

```yaml
version: '3.8'

services:
  db-backup-agent:
    image: {your-dockerhub-username}/db-backup-agent:latest
    container_name: db-backup-agent
    restart: unless-stopped
    ports:
      - "5001:5001"
    volumes:
      - ./backups:/backups
    environment:
      # Set timezone to ensure scheduled tasks run at the correct time
      - TZ=Asia/Shanghai

volumes:
  backups:
```

### 2. Start the Service

Create a `backups` folder in the same directory as `docker-compose.yml` (for persistent storage of backup files and configurations), then run:

```bash
docker-compose up -d
```

### 3. Access the Application

Open `http://<your-server-ip>:5001` in your browser to start using the application.

## 🖼️ Interface Preview

### Registration Page

First-time access requires creating an admin account:

![Registration Page](Images/register.png)

![Registration Page](Images/register2.png)

### Main Interface

After login, you can manage database connections and backup tasks:

![Main Interface](Images/screenshot.png)

## ⚙️ Configuration

| Configuration | Description | Required |
|---------------|-------------|----------|
| **Port Mapping** | Default `5001:5001`, can modify host port as needed | No |
| **Data Volume** | `./backups:/backups` - Persistent storage for backup files and configuration data | **Yes** |
| **Timezone (TZ)** | Recommended to set, e.g., `Asia/Shanghai`, ensures scheduled tasks execute accurately | Recommended |

> 💡 **Tip**: Data volume mapping is mandatory. Without it, all configurations and backup files will be lost after container restart.

## 🛠️ Building Images (Advanced Users)

If you need to build the image yourself, you can use the provided multi-architecture build script:

```bash
# Build and push to Docker Hub (automatically supports amd64 and arm64)
./build_and_push.sh {your-dockerhub-username}/db-backup-agent:latest
```

The script automatically completes the following steps:
1. Detect target architectures
2. Build `linux/amd64` and `linux/arm64` images in parallel
3. Push to Docker Hub and merge into a single tag

### Architecture Differences

| Architecture | MySQL Client | PostgreSQL Client |
|--------------|--------------|-------------------|
| x86_64 | Oracle Official Client | PostgreSQL Official Client |
| ARM64 | MariaDB Client (MySQL compatible) | PostgreSQL Official Client |

## 📄 License

This project is open-sourced under the [MIT License](LICENSE).
