# Docker Compose 使用指南

本文档介绍如何使用 Docker Compose 构建和运行数据库备份代理。

## 📋 前置要求

- Docker 20.10+
- Docker Compose 2.0+

## 🚀 快速开始

### 1. 构建镜像

使用 docker-compose 构建镜像：

```bash
docker-compose build
```

### 2. 启动容器

启动容器（后台运行）：

```bash
docker-compose up -d
```

### 3. 查看日志

查看容器日志：

```bash
docker-compose logs -f
```

查看最近 20 行日志：

```bash
docker-compose logs --tail 20
```

### 4. 停止容器

停止运行中的容器：

```bash
docker-compose stop
```

### 5. 删除容器

停止并删除容器：

```bash
docker-compose down
```

停止并删除容器以及数据卷：

```bash
docker-compose down -v
```

## 📂 目录结构

```
db-backup-agent/
├── docker-compose.yml          # Docker Compose 配置文件
├── Dockerfile                   # Docker 镜像构建文件
├── app.py                       # Flask Web 应用
├── config_manager.py            # 配置管理模块
├── backup_lock.py               # 备份锁管理模块
├── scripts/
│   ├── backup.sh                # 备份脚本
│   └── entrypoint.sh            # 容器启动脚本
├── templates/                   # HTML 模板文件
├── static/                      # 静态资源文件
└── backups/                     # 备份文件存储目录（持久化）
```

## 🔧 配置说明

### docker-compose.yml 配置项

```yaml
version: '3.8'

services:
  db-backup:
    # 构建配置
    build:
      context: .                 # 构建上下文为当前目录
      dockerfile: Dockerfile     # 使用的 Dockerfile

    # 镜像名称和标签
    image: tony5188/db-backup-agent:test

    # 容器名称
    container_name: db-backup-test

    # 自动重启策略
    restart: always

    # 端口映射
    ports:
      - "5001:5001"              # 主机端口:容器端口

    # 数据卷挂载
    volumes:
      - ./backups:/backups       # 持久化存储备份文件和数据库
      - /etc/localtime:/etc/localtime:ro  # 同步主机时区

    # 环境变量
    environment:
      - TZ=Asia/Shanghai         # 时区设置
```

### 修改端口映射

如果需要使用其他端口，修改 `ports` 配置：

```yaml
ports:
  - "8080:5001"  # 使用主机的 8080 端口
```

### 修改时区

修改 `environment` 中的 `TZ` 变量：

```yaml
environment:
  - TZ=America/New_York    # 美国东部时间
  - TZ=Europe/London       # 伦敦时间
  - TZ=Asia/Tokyo          # 东京时间
```

## 🌐 访问 Web 界面

容器启动后，通过浏览器访问：

```
http://localhost:5001
```

或使用服务器 IP：

```
http://<服务器IP>:5001
```

## 📊 数据持久化

所有重要数据都存储在 `./backups` 目录中：

- **users.db**: SQLite 数据库，包含所有配置（数据库连接、备份计划、通知设置等）
- **备份文件**: PostgreSQL 和 MySQL 的备份文件
- **日志文件**: 备份日志和系统日志

### 备份配置数据库

定期备份 `users.db` 文件：

```bash
cp ./backups/users.db ./backups/users.db.backup.$(date +%Y%m%d)
```

### 恢复配置数据库

```bash
cp ./backups/users.db.backup.20260106 ./backups/users.db
docker-compose restart
```

## 🔄 更新镜像

### 1. 重新构建镜像

```bash
docker-compose build
```

### 2. 重启容器

```bash
docker-compose up -d
```

### 3. 查看新版本

```bash
docker-compose logs --tail 50
```

## 🛠️ 常用命令

### 查看容器状态

```bash
docker-compose ps
```

### 进入容器 Shell

```bash
docker-compose exec db-backup bash
```

### 执行容器内命令

```bash
docker-compose exec db-backup python3 /backup_lock.py list
```

### 查看实时日志

```bash
docker-compose logs -f db-backup
```

### 重启容器

```bash
docker-compose restart
```

### 查看容器资源使用

```bash
docker stats db-backup-test
```

## 🐛 故障排查

### 1. 容器无法启动

查看详细日志：

```bash
docker-compose logs
```

检查端口是否被占用：

```bash
netstat -tlnp | grep 5001
```

### 2. 无法访问 Web 界面

检查容器状态：

```bash
docker-compose ps
```

检查防火墙设置：

```bash
# Ubuntu/Debian
sudo ufw status

# CentOS/RHEL
sudo firewall-cmd --list-all
```

### 3. 数据库连接失败

检查数据库配置：

```bash
docker-compose exec db-backup python3 /config_manager.py export
```

### 4. 备份任务失败

查看备份日志：

```bash
docker-compose exec db-backup ls -la /backups/logs/details/
```

查看系统日志：

```bash
docker-compose exec db-backup python3 /app/system_logger.py show --limit 50
```

## 📝 生产环境部署建议

### 1. 修改重启策略

```yaml
restart: unless-stopped  # 除非手动停止，否则总是重启
```

### 2. 添加资源限制

```yaml
deploy:
  resources:
    limits:
      cpus: '1'
      memory: 512M
    reservations:
      cpus: '0.5'
      memory: 256M
```

### 3. 添加健康检查

```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:5001/"]
  interval: 30s
  timeout: 10s
  retries: 3
```

### 4. 使用环境变量文件

创建 `.env` 文件：

```env
TZ=Asia/Shanghai
PORT=5001
```

修改 docker-compose.yml：

```yaml
environment:
  - TZ=${TZ}
ports:
  - "${PORT}:5001"
```

### 5. 配置日志轮转

```yaml
logging:
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "3"
```

## 🔐 安全建议

1. **修改默认密钥**: 修改 `app.py` 中的 `secret_key`
2. **使用 HTTPS**: 在生产环境使用反向代理（如 Nginx）配置 SSL
3. **限制访问**: 使用防火墙限制 5001 端口的访问
4. **定期更新**: 定期更新镜像以获取安全补丁
5. **备份数据**: 定期备份 `./backups` 目录

## 📚 更多信息

- 完整文档: [README.md](README.md)
- 版本历史: [CHANGELOG.md](CHANGELOG.md)
- 问题反馈: https://github.com/yourusername/db-backup-agent/issues
