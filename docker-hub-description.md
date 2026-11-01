# 🗄️ DB Backup Agent — 自部署数据库备份管理平台

单容器运行的数据库备份管理工具:Web 界面完成 **PostgreSQL / MySQL / MongoDB / Redis / SQLite** 的定时备份、恢复、云同步与消息通知,全程无需命令行。数据全部留在你自己的服务器上。

> 🆕 **v3.4.0**:备份/计划/恢复四页合一 · 通知渠道列表(同渠道多账号) · 计划一键「立即执行」 · 配置库自备份上云 · 表单防误关

## ✨ 功能亮点

- **五种数据库** — PostgreSQL / MySQL / MongoDB / Redis / SQLite 备份与恢复
- **计划备份** — cron 定时 + 手动触发 + 计划页一键立即执行,连接级并发互斥
- **实时进度** — 备份/恢复各阶段 SSE 实时推送,支持中途取消
- **云同步** — S3 兼容(MinIO / AWS S3 / Cloudflare R2 / B2)+ NFS/SMB 直连 NAS
- **通知渠道** — 邮件 / 企业微信 / 飞书机器人 / Server酱,渠道列表化支持同渠道多账号,一键测试
- **备份验证** — gzip CRC + SHA-256 校验和,每周自动校验可选
- **配置库自备份** — 每日自动快照,本地保留 7 份 + 云端轮转保留 30 份
- **保留策略** — 按连接自定义保留天数,过期备份(文件+记录)自动清理,云副本联动
- **安全** — 数据库凭据 Fernet 加密存储,登录密码 argon2 哈希
- **多架构** — `amd64` + `arm64`(Apple Silicon / 树莓派 / 国产 ARM 服务器)

## 🚀 快速开始

```yaml
# docker-compose.yml
services:
  db-backup:
    image: tony5188/db-backup-agent:latest
    container_name: db-backup-agent
    restart: unless-stopped
    privileged: true          # NFS/SMB 备份目的地需要;纯 S3 可去掉
    ports:
      - "8000:8000"
    volumes:
      - ./data:/data          # 配置库、备份文件、密钥全在这里持久化
    environment:
      - TZ=Asia/Shanghai
      - APP_INITIAL_ADMIN_USER=admin
      - APP_INITIAL_ADMIN_PASSWORD=change-me-on-first-login
```

```bash
docker compose up -d
# 浏览器打开 http://<服务器IP>:8000 登录
```

> 💡 容器自带健康检查(`/api/v1/health`),`docker ps` 直接可见健康状态。

## ⚙️ 主要环境变量

| 变量 | 说明 | 默认 |
|------|------|------|
| `APP_DATA_DIR` | 数据目录(挂载卷) | `/data` |
| `APP_INITIAL_ADMIN_USER` / `APP_INITIAL_ADMIN_PASSWORD` | 首启管理员账号(仅账号表为空时生效) | `admin` / 无 |
| `APP_SECRET_KEY` / `APP_FERNET_KEY` | 会话与凭据加密密钥(成对;不配则首启自动生成到 `data/keys/`) | 自动生成 |
| `APP_SCHEDULER_ENABLED` | 定时调度开关(多进程部署只允许一个进程开启) | `true` |
| `APP_COOKIE_SECURE` | TLS 反代后置 `true` | `false` |

> ⚠️ `data/keys/keys.json` 用于加密数据库连接密码,请连同 `data/` 一起备份;丢失后已保存的连接凭据无法解密。

## 🏷️ 标签

| 标签 | 说明 |
|------|------|
| `latest` | 最新稳定版(amd64 + arm64 多架构) |
| `3.4.0` / `3.3.0` / `3.2.0` | 按版本号固定 |

## 🔗 相关链接

- 源码与文档:[github.com/zhengzhw8812/db-backup-agent](https://github.com/zhengzhw8812/db-backup-agent)
- 更新日志:[README Changelog](https://github.com/zhengzhw8812/db-backup-agent#-更新日志)
- 许可:MIT
