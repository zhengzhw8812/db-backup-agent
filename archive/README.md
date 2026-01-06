# Archive 目录

此目录存放项目开发过程中的辅助文档、测试脚本和临时文件。

## 📁 目录内容

### 文档文件

- **BROWSER_CACHE_SOLUTION.md** - 浏览器缓存问题解决方案
  - 详细说明了通知设置页面的缓存问题及解决方法
  - 用户问题排查指南

- **CACHE_FIX_GUIDE.md** - 缓存修复技术说明
  - 技术层面的缓存控制实现说明
  - HTTP 响应头和 HTML meta 标签配置

- **DOCKER_COMPOSE_GUIDE.md** - Docker Compose 使用指南
  - Docker Compose 完整使用文档
  - 部署、配置、故障排查指南

- **GITEE_SETUP.md** - Git 多平台同步配置
  - GitHub 和 Gitee 同步配置说明
  - 多仓库管理最佳实践

### 测试脚本

- **test_notifications_flow.py** - 通知配置流程测试脚本
  - 测试数据库值转换
  - 测试模板渲染逻辑
  - 验证布尔转换

- **test_notifications_html.sh** - HTML 输出测试脚本
  - 测试通知页面 HTML 生成
  - 验证 checkbox 状态

- **test_auto_migration.py** - 自动迁移测试脚本
  - 测试数据库版本检测
  - 测试表结构迁移

### 开发工具

- **claude_code_env.sh** - Claude Code 开发环境配置脚本
  - 自动安装 Node.js 和 Claude Code CLI
  - 配置 API 密钥和环境变量
  - 用于本地开发环境设置

- **git-push-all.sh** - Git 多平台推送脚本
  - 同时推送到 GitHub 和 Gitee
  - 自动化多仓库同步流程

## 📝 说明

这些文件是项目开发过程中产生的辅助文件，不是项目核心功能的一部分：

- **文档文件**: 为特定问题提供详细解决方案和说明
- **测试脚本**: 用于开发和调试的临时测试工具

这些文件归档保存以备参考，但不包含在生产镜像中。

## 🚀 生产环境

生产环境的 Docker 镜像不包含此目录的任何文件。
