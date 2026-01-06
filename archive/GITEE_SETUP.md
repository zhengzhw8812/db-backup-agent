# Git 多平台同步配置说明

本项目已配置同时推送到 GitHub 和 Gitee。

## 当前配置

```bash
# 查看所有 remote
git remote -v

# 输出示例：
origin  git@github.com:zhengzhw8812/db-backup-agent.git (fetch)
origin  git@github.com:zhengzhw8812/db-backup-agent.git (push)
gitee   https://gitee.com/zhengzhw8812/db-backup-agent.git (fetch)
gitee   https://gitee.com/zhengzhw8812/db-backup-agent.git (push)
```

## 使用方法

### 方法 1: 使用便捷脚本（推荐）

```bash
# 同时推送到 GitHub 和 Gitee
./git-push-all.sh
```

### 方法 2: 分别推送

```bash
# 推送到 GitHub
git push origin main

# 推送到 Gitee
git push gitee main
```

### 方法 3: 一次性推送到所有 remote

```bash
# 推送到所有配置的 remote
git push --all main
```

## 首次使用配置

如果需要配置自己的仓库，请按以下步骤操作：

### 1. 修改 remote URL

```bash
# 修改 GitHub URL（替换为你的用户名）
git remote set-url origin git@github.com:YOUR_USERNAME/db-backup-agent.git

# 修改 Gitee URL（替换为你的用户名）
git remote set-url gitee https://gitee.com/YOUR_USERNAME/db-backup-agent.git
```

### 2. 验证配置

```bash
git remote -v
```

### 3. 测试推送

```bash
./git-push-all.sh
```

## 认证配置

### GitHub 认证

如果使用 SSH URL（`git@github.com:...`），需要配置 SSH 密钥：

```bash
# 生成 SSH 密钥（如果还没有）
ssh-keygen -t ed25519 -C "your_email@example.com"

# 查看公钥
cat ~/.ssh/id_ed25519.pub

# 将公钥添加到 GitHub：Settings → SSH and GPG keys
```

### Gitee 认证

使用 HTTPS URL 时，首次推送会要求输入用户名和密码：

- **用户名**: Gitee 用户名或邮箱
- **密码**: Gitee 账户密码

**建议**: 在 Gitee 设置中启用"私人令牌"（Personal Access Token），使用令牌代替密码更安全。

## 常见问题

### 1. 推送失败：认证错误

**原因**: HTTPS URL 使用密码时可能遇到认证问题

**解决方案**:
```bash
# 方案 1: 使用私人令牌代替密码
# 在 Gitee 生成令牌后，推送时：
# 用户名：your_username
# 密码：your_personal_access_token

# 方案 2: 切换到 SSH URL
git remote set-url gitee git@gitee.com:USERNAME/db-backup-agent.git
```

### 2. Host key verification failed

**原因**: SSH 首次连接需要确认主机指纹

**解决方案**:
```bash
# 自动接受 Gitee 的主机密钥
ssh-keyscan gitee.com >> ~/.ssh/known_hosts
```

### 3. 远程仓库不存在

**原因**: Gitee 上还没有创建仓库

**解决方案**:
1. 访问 https://gitee.com/
2. 创建新仓库 `db-backup-agent`
3. 重新运行推送命令

## 自动化脚本说明

`git-push-all.sh` 脚本功能：

- ✅ 自动推送到 GitHub
- ✅ 自动推送到 Gitee
- ✅ 显示推送状态和错误信息
- ✅ 失败时自动停止并提示错误

## 注意事项

1. **保持同步**: 每次提交后使用 `git-push-all.sh` 确保两个平台同步
2. **分支名称**: 默认推送到 `main` 分支，如需修改请编辑脚本
3. **权限设置**: 确保在 GitHub 和 Gitee 都有仓库的推送权限
4. **SSH 密钥**: 如果使用 SSH URL，需要在两个平台都配置相同的 SSH 公钥

## 仓库地址

- **GitHub**: https://github.com/zhengzhw8812/db-backup-agent
- **Gitee**: https://gitee.com/zhengzhw8812/db-backup-agent
