# Gitee 推送指南

由于 Gitee 使用 HTTPS 认证，需要配置认证方式才能推送代码。

## 方法一：使用账号密码推送（推荐）

### 1. 使用命令行推送

执行以下命令，系统会提示输入用户名和密码：

```bash
git push gitee main
```

- **用户名**：你的 Gitee 用户名（或邮箱）
- **密码**：你的 Gitee 密码

### 2. 配置凭据存储（避免每次输入密码）

```bash
# 配置 Git 记住密码（缓存 1 小时）
git config --global credential.helper cache

# 或者永久存储密码
git config --global credential.helper store
```

配置后，第一次输入密码会被保存，之后无需再次输入。

## 方法二：使用 SSH 密钥推送

### 1. 生成 SSH 密钥（如果还没有）

```bash
ssh-keygen -t rsa -b 4096 -C "your_email@example.com"
```

### 2. 添加 SSH 密钥到 Gitee

1. 复制公钥内容：
```bash
cat ~/.ssh/id_rsa.pub
```

2. 在 Gitee 上添加密钥：
   - 访问 https://gitee.com/profile/sshkeys
   - 点击"添加公钥"
   - 粘贴公钥内容

### 3. 修改 Remote URL 为 SSH

```bash
git remote set-url gitee git@gitee:zhengzhw8812/db-backup-agent.git
```

### 4. 推送代码

```bash
git push gitee main
```

## 当前状态

- **GitHub Remote**: git@github.com:zhengzhw8812/db-backup-agent.git (SSH)
- **Gitee Remote**: https://gitee.com/zhengzhw8812/db-backup-agent.git (HTTPS)

## 推送命令

### 仅推送到 GitHub
```bash
git push origin main
```

### 仅推送到 Gitee
```bash
git push gitee main
```

### 同时推送到两个平台（使用归档脚本）
```bash
bash archive/git-push-all.sh
```

## 注意事项

1. 如果 Git 历史已被重写（如我们刚才删除了 commit 签名），需要使用 `--force` 参数：
```bash
git push gitee main --force
```

2. 首次推送到 Gitee 时，可能需要验证账号权限。

3. 如果使用双因素认证（2FA），不能使用密码，需要使用个人访问令牌（Personal Access Token）。
