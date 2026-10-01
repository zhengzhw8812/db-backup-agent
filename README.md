# 数据库备份代理 (db-backup-agent)

一个轻量级、易部署的数据库备份管理工具。单容器运行,通过 Web 界面完成 PostgreSQL、MySQL、MongoDB、Redis、SQLite 的自动化备份管理:配置连接、制定计划、执行备份、恢复数据、同步到云存储,全程无需命令行。

## ✨ 主要功能

- **多数据库支持** - PostgreSQL / MySQL / MongoDB / Redis / SQLite 五种数据库的备份与恢复
- **灵活的备份计划** - 按库配置 cron 计划,亦可随时手动触发;支持一次备份连接下的多个库
- **实时进度推送** - 备份/恢复各阶段进度经 SSE 实时推送到页面,支持中途取消
- **并发保护** - 连接级互斥:同一连接同时只跑一个备份,防止资源冲突
- **智能保留策略** - 自定义保留天数,过期备份(文件+记录)自动清理
- **备份恢复** - 从任意一份成功备份恢复到目标连接,支持恢复进度跟踪与取消
- **云同步** - 备份自动上传到 S3 兼容存储(MinIO / AWS S3 / Cloudflare R2 / B2 等),支持多目标
- **NFS / SMB 共享目的地** - 直连 NAS 共享做备份落盘(容器内自动挂载,需特权模式)
- **消息通知** - 邮件、企业微信、飞书机器人、Server酱(个人微信),备份成功/失败/失联告警可测
- **备份验证** - 手动或每周自动校验备份文件完整性(gzip CRC + 校验和)
- **配置库自备份** - 每日自动快照应用配置库(VACUUM INTO 一致性快照,保留 7 份)
- **消息通知** - 备份结果自动推送:邮件(SMTP)与企业微信应用消息,均支持测试发送
- **数据加密** - 数据库连接密码 Fernet 对称加密存储,登录密码 argon2 哈希
- **系统日志与仪表盘** - 运行事件、备份历史完整可查,仪表盘汇总状态
- **多架构镜像** - 支持 x86_64 (amd64) 与 ARM64(如 Apple Silicon、树莓派)

## 📦 镜像标签

**Docker Hub**: https://hub.docker.com/r/tony5188/db-backup-agent

| 标签 | 说明 |
|------|------|
| `latest` | amd64 + arm64 多架构镜像,Docker 自动识别设备架构 |

## 🚀 快速开始

### 1. 创建 docker-compose.yml

```yaml
services:
  db-backup:
    image: tony5188/db-backup-agent:latest
    container_name: db-backup-agent
    restart: unless-stopped
    # NFS/SMB 备份目的地需要在容器内挂载文件系统,必须特权模式
    privileged: true
    ports:
      - "8000:8000"
    volumes:
      - ./data:/data          # 配置数据库、备份文件、密钥、日志都在这里持久化
    environment:
      - TZ=Asia/Shanghai
      # 首次启动创建管理员账号(仅在账号表为空时生效)
      - APP_INITIAL_ADMIN_USER=admin
      - APP_INITIAL_ADMIN_PASSWORD=change-me-on-first-login
```

### 2. 启动

```bash
docker-compose up -d
```

### 3. 访问

浏览器打开 `http://<你的服务器IP>:8000`,用上面设置的管理员账号登录。

> 💡 容器自带健康检查(访问 `/api/v1/health`),`docker ps` 可直接看到健康状态。

## ⚙️ 配置说明

所有配置经 `APP_` 前缀环境变量注入(完整清单见仓库 `.env.example`):

| 变量 | 说明 | 默认 |
|------|------|------|
| `APP_DATA_DIR` | 数据持久化目录(挂载卷) | `/data` |
| `APP_REDIS_URL` | 任务队列 Redis(容器内自带) | `redis://127.0.0.1:6379/0` |
| `APP_SECRET_KEY` / `APP_FERNET_KEY` | 会话与凭据加密密钥,**必须成对提供**;不提供则首次启动自动生成到 `data/keys/` | 自动生成 |
| `APP_INITIAL_ADMIN_USER` / `APP_INITIAL_ADMIN_PASSWORD` | 首启管理员账号(仅账号表为空时生效) | `admin` / 无 |
| `APP_SCHEDULER_ENABLED` | 是否在本进程启动定时调度(多进程部署时只允许一个进程开启) | `true` |
| `APP_COOKIE_SECURE` | 会话 Cookie 是否加 Secure 标记(TLS 终结代理后置 true) | `false` |

> ⚠️ **备份密钥**: `data/keys/keys.json` 用于加密数据库连接密码,请连同 `data/` 一起备份。丢失后将无法解密已保存的连接凭据。

## 🛠️ 本地开发

后端(FastAPI + SQLAlchemy + APScheduler + arq)、前端(Vue 3 + Naive UI + Vite)的目录结构、开发命令与备份数据流说明,见 [AGENTS.md](AGENTS.md)。

## 📄 开源协议

本项目基于 [MIT License](LICENSE) 开源。

## 📋 更新日志

### v3.0.0

#### ✨ 重大更新 - 全栈重写
- **后端重写为 FastAPI** - SQLAlchemy 2 ORM + Pydantic 校验,替代 v2 的 Flask 单体
- **前端重写为 Vue 3 单页应用** - TypeScript + Naive UI + Pinia + ECharts,替代 v2 的 Jinja2 模板
- **数据库适配器架构** - 新增 MongoDB / Redis / SQLite 备份与恢复支持(原有 PostgreSQL / MySQL 保留)
- **备份恢复功能** - 新增从历史备份一键恢复到目标连接
- **云同步功能** - 新增 S3 兼容对象存储同步(MinIO / AWS S3 / R2 / B2)
- **任务队列** - 备份/恢复/同步经 arq + Redis 队列异步执行,与 Web 进程隔离
- **实时进度** - SSE 推送备份各阶段进度,支持任务取消
- **安全升级** - 登录密码 SHA-256 → argon2,连接密码 Fernet 加密,密钥原子持久化
- **部署升级** - supervisor 管理多进程(Web / Worker / Redis),镜像多架构

#### ⚠️ 不兼容变更
- v2 的多用户与两步验证(2FA)功能在 v3 中暂未保留,当前为单管理员账号
- 数据目录结构变更为 `/data`(SQLite 库、备份文件、密钥分目录存放),与 v2 的 `/backups` 卷不通用

### v2.4.0 (2026-01-12)

#### ✨ 新功能
- **多用户数据隔离** - 完整的多用户支持，每个用户的备份任务、配置和历史完全独立
- **用户注册功能** - 支持用户自主注册，注册成功后自动引导设置两步验证
- **两步验证（2FA）** - 新增 TOTP 一次性密码认证功能，增强账户安全
- **OTP 设置向导** - 友好的二维码扫描和验证码输入界面
- **安全管理页面** - 统一的安全设置入口，支持启用/禁用两步验证
- **忘记密码功能** - 新增密码重置功能，支持通过 OTP 验证重置密码
- **智能登录流程** - 登录页面 OTP 输入框始终显示，支持可选填写

#### ⚡ 优化改进
- **注册流程优化** - 注册成功后自动登录并引导到 OTP 设置页面
- **登录页面优化** - OTP 输入框始终显示，"如未设置可留空"提示，详细的使用说明
- **密码重置流程** - 提供实时的密码强度指示器，根据用户 OTP 状态自动调整流程
- **统一配色方案** - 采用统一的蓝色主题，界面更加专业美观
- **主页导航优化** - 新增"🔐 安全设置"入口

#### 🔒 安全增强
- **数据库级隔离** - 所有业务表增加 user_id 外键，确保数据安全隔离
- **文件系统隔离** - 备份文件按用户分目录存储（/backups/user_{user_id}/）
- **TOTP 算法** - 使用标准 TOTP 算法（RFC 6238），每 30 秒生成新的 6 位验证码
- **密钥安全存储** - 密钥使用 Base32 编码存储，安全可靠
- **验证时间窗口** - 允许前后 1 个周期（30秒），避免时钟偏差问题
- **密码确认机制** - 两步验证启用/禁用操作需要密码确认，防止误操作

#### 🗄️ 数据库变更
- 新增 user_otp_config 表（OTP 配置表）
- backup_history 表新增 user_id 字段
- database_connections 表新增 user_id 字段
- backup_schedules 表新增 user_id 字段
- password_reset_tokens 表新增 user_id 字段
- 为所有 user_id 字段创建索引，优化查询性能

#### 🎯 验证器应用支持
- Google Authenticator (iOS/Android)
- Microsoft Authenticator (iOS/Android)
- Authy (iOS/Android/Desktop)
- 1Password, LastPass 等密码管理器的内置功能

### v2.3.0 (2026-01-06)

#### ✨ 新功能
- **并发备份控制** - 添加备份锁机制，防止同一类型的数据库同时执行多个备份任务
- **智能锁管理** - 基于数据库的持久化锁，支持自动过期（2小时）和崩溃恢复
- **通知页面优化** - 改进通知设置页面的交互体验和视觉反馈
- **调试支持** - 新增通知调试页面，方便排查通知配置问题

#### ⚡ 优化改进
- 优化通知设置页面的 JavaScript 初始化逻辑，页面加载时正确显示配置状态
- 改进禁用状态的视觉反馈，输入框和测试按钮半透明，保存按钮保持正常颜色
- 添加多层浏览器缓存控制，确保配置状态实时同步
- 备份锁支持内存缓存和数据库双重存储，提高性能和可靠性

#### 🐛 问题修复
- 修复通知开关刷新后状态显示不正确的问题
- 修复关闭通知后保存按钮无法点击的问题
- 修复邮件/企业微信配置区域在禁用状态下的样式显示问题
- 修复并发备份可能导致的资源冲突和数据不一致问题

#### 📚 文档更新
- 新增浏览器缓存问题解决方案文档
- 新增 Docker Compose 使用指南
- 新增缓存修复技术说明文档

### v2.2.0 (2026-01-05)

#### ✨ 新功能
- **数据库自动迁移** - 新增数据库版本自动检测和迁移功能
- **完整性检查** - 应用启动时自动检查并修复数据库表和索引
- **表结构验证** - 自动检测表结构是否完整，缺失或不完整的表会自动重建
- **数据保护** - 表重建时自动备份和恢复兼容列的数据
- **索引管理** - 自动创建缺失的数据库索引，优化查询性能

#### ⚡ 优化改进
- 简化数据库升级流程，无需手动执行迁移脚本
- 支持从 v2.0.0、v2.1.0 自动升级到 v2.2.0
- 改进错误处理和日志输出，便于问题排查
- 优化迁移脚本，支持跨版本升级

#### 🐛 问题修复
- 修复数据库表结构不完整导致的功能异常
- 修复索引缺失导致的查询性能问题
- 修复版本升级时表结构不一致的问题

### v2.1.0 (2026-01-05)

#### ✨ 新功能
- 添加企业微信通知支持，可在备份成功/失败时接收通知
- 添加邮件通知支持，支持 SMTP 配置和多个收件人
- 通知类型支持配置（成功时通知、失败时通知）
- 添加备份历史记录功能，可查看所有备份任务的执行历史
- 添加系统日志功能，记录系统运行状态和错误信息
- Web 界面添加版本更新说明页面

#### ⚡ 优化改进
- 优化通知消息格式，使用纯文本格式以兼容微信手机端
- 企业微信 Token 缓存机制优化，支持配置变更自动检测
- Token 失效时自动重试机制，提高通知发送成功率
- 备份脚本优化，支持在后台异步发送通知，不阻塞备份流程
- 数据库配置管理优化，支持动态加载配置

#### 🐛 问题修复
- 修复企业微信通知在手机端显示"暂不支持此消息类型"的问题
- 修复配置变更后 Token 缓存未更新导致的通知发送失败问题
- 修复模块导入路径问题，提高容器内运行的兼容性
- 修复日志文件路径处理问题

### v2.0.0 (2025-12-25)

#### ✨ 重大更新 - 前端页面重构
- 全新的现代化 UI 设计，采用渐变色背景和卡片式布局
- 响应式设计优化，支持移动端和平板设备访问
- 添加备份文件列表页面，支持文件预览、下载和删除
- 添加备份计划配置界面，可视化设置定时任务
- 添加备份历史记录页面，展示所有备份任务的执行状态
- 添加系统日志页面，可查看系统运行日志和错误信息
- 优化表单交互体验，使用模态框替代原生弹窗
- 添加实时状态更新，无需刷新页面即可看到最新状态

### v1.1.0 (2025-12-20)

#### ✨ 新功能
- 支持 MySQL 和 PostgreSQL 数据库备份
- 支持多种备份计划（每天、每周、每月）
- 支持手动立即备份功能
- 支持多个数据库配置同时管理
- Web 界面管理，支持数据库配置的增删改查
- 自动清理过期备份文件
- 备份文件下载和删除功能

### v1.0.0 (2025-12-01)

#### ✨ 初始版本
- 基础数据库备份功能
- Docker 容器化部署
- 用户认证系统
- 基本的备份文件管理

### v2.5.0 (2026-01-12)

> 以下条目来自旧版英文更新日志,按原文保留。

#### ✨ New Features
- **Two-Factor Authentication (2FA)** - Added TOTP-based one-time password authentication for enhanced account security
- **OTP Setup Wizard** - User-friendly QR code scanning and verification code input interface
- **Security Management Page** - Unified security settings entry point for enabling/disabling 2FA
- **Authenticator App Support** - Compatible with Google Authenticator, Microsoft Authenticator, Authy, and other mainstream apps
- **Smart Login Flow** - Automatically enables or skips two-step verification based on user configuration

#### ⚡ Improvements
- Added "🔐 Security Settings" entry point in main page navigation
- Login page dynamically displays OTP verification code input field
- Two-step verification requires confirmation before enabling, ensuring correct configuration
- Security operations require password confirmation to prevent accidental changes

#### 🔒 Security Enhancements
- Uses standard TOTP algorithm (RFC 6238), generating new 6-digit codes every 30 seconds
- Secret keys stored using Base32 encoding for security
- Verification time window allows ±1 period (30 seconds) to avoid clock skew issues
- Enabling/disabling 2FA requires password confirmation
- Session intermediate state management ensures secure login flow
