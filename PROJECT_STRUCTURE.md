# 项目结构说明

## 📁 根目录结构

```
db-backup-agent/
├── app.py                      # Flask 主应用
├── db_init.py                  # 数据库初始化脚本
├── migrate_db.py               # 数据库迁移脚本
├── config_manager.py           # 配置管理模块
├── backup_lock.py              # 备份锁管理模块
├── backup_logger.py            # 备份日志记录
├── system_logger.py            # 系统日志记录
├── notifications.py            # 通知发送模块
├── requirements.txt            # Python 依赖
├── Dockerfile                  # Docker 镜像构建文件
├── docker-compose.yml          # Docker Compose 配置
├── build_and_push.sh          # 多架构镜像构建脚本
├── git-push-all.sh            # 双平台推送脚本
├── README.md                   # 项目说明文档
│
├── templates/                  # HTML 模板目录
│   ├── index.html             # 主页
│   ├── login.html             # 登录页
│   ├── register.html          # 注册页
│   ├── notifications.html     # 通知设置页
│   ├── changelog.html         # 版本更新说明
│   └── debug_notifications.html # 通知调试页
│
├── static/                     # 静态资源目录
│   └── style.css              # 样式文件
│
├── scripts/                    # 脚本目录
│   ├── backup.sh              # 备份执行脚本
│   └── entrypoint.sh          # 容器启动脚本
│
├── config/                     # 配置文件目录
│   └── crontab                # 定时任务配置
│
└── archive/                    # 归档目录（开发文档和测试文件）
    ├── README.md              # 归档文件说明
    ├── BROWSER_CACHE_SOLUTION.md
    ├── CACHE_FIX_GUIDE.md
    ├── DOCKER_COMPOSE_GUIDE.md
    ├── GITEE_SETUP.md
    ├── test_notifications_flow.py
    ├── test_notifications_html.sh
    └── ...其他历史文件
```

## 📦 核心文件说明

### Python 应用文件

| 文件 | 说明 | 功能 |
|------|------|------|
| `app.py` | Flask 主应用 | Web 服务器、路由处理、用户认证 |
| `config_manager.py` | 配置管理 | 数据库连接、备份计划、通知配置的 CRUD 操作 |
| `backup_lock.py` | 备份锁管理 | 并发控制、锁获取/释放、状态查询 |
| `notifications.py` | 通知发送 | 邮件和企业微信通知发送 |
| `backup_logger.py` | 备份日志 | 备份任务日志记录 |
| `system_logger.py` | 系统日志 | 系统运行日志记录 |
| `db_init.py` | 数据库初始化 | 首次运行时创建数据库表 |
| `migrate_db.py` | 数据库迁移 | 版本升级时的数据迁移 |

### 配置文件

| 文件 | 说明 |
|------|------|
| `requirements.txt` | Python 依赖包列表 |
| `Dockerfile` | Docker 镜像构建定义 |
| `docker-compose.yml` | Docker Compose 编排配置 |
| `config/crontab` | Cron 定时任务配置 |

### 脚本文件

| 文件 | 说明 |
|------|------|
| `scripts/backup.sh` | 执行数据库备份的 Shell 脚本 |
| `scripts/entrypoint.sh` | 容器启动时的入口脚本 |
| `build_and_push.sh` | 构建并推送多架构 Docker 镜像 |
| `git-push-all.sh` | 同时推送到 GitHub 和 Gitee |

### 模板文件

| 文件 | 说明 |
|------|------|
| `templates/index.html` | 主界面 - 数据库管理 |
| `templates/login.html` | 登录页面 |
| `templates/register.html` | 注册页面 |
| `templates/notifications.html` | 通知设置页面 |
| `templates/changelog.html` | 版本更新说明页面 |
| `templates/debug_notifications.html` | 通知调试页面 |

### 静态资源

| 文件 | 说明 |
|------|------|
| `static/style.css` | 全局样式表 |

## 🎯 目录说明

### `/templates` - HTML 模板

存放所有的 HTML 模板文件，使用 Jinja2 模板引擎渲染。

### `/static` - 静态资源

存放 CSS、JavaScript、图片等静态资源。

### `/scripts` - 执行脚本

存放 Shell 脚本，主要用于备份执行和容器启动。

### `/config` - 配置文件

存放应用配置文件，如 cron 定时任务配置。

### `/archive` - 归档目录

存放开发过程中的辅助文档和测试脚本，不影响生产环境运行。

## 🚀 生产环境部署

生产环境只需要以下核心文件：

1. **Python 应用文件**: `app.py`, `config_manager.py`, `backup_lock.py` 等
2. **配置文件**: `requirements.txt`, `Dockerfile`, `docker-compose.yml`
3. **模板和静态资源**: `templates/`, `static/`
4. **脚本文件**: `scripts/backup.sh`, `scripts/entrypoint.sh`, `config/crontab`

归档目录 `archive/` 不会包含在生产镜像中。

## 📝 开发环境

开发时可以使用归档目录中的工具：

- 测试脚本：`archive/test_notifications_flow.py`
- 数据库诊断：`archive/diagnose_db.sh`
- 文档参考：`archive/*.md`

这些文件提供了详细的开发和故障排查指南。
