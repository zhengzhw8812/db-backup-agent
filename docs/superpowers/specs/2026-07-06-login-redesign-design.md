# 登录页两版改造 — 设计文档

- 日期：2026-07-06
- 状态：已确认，待实现
- 适用：db-backup-agent 前端（Vue 3 + Naive UI + Vite），仅前端改动

## 1. 目标

当前登录页（`Login.vue` 的玻璃拟态卡片 + 紫色渐变）观感一般。提供**两个候选登录页**让用户对比择优：

- **Variant A — SoybeanAdmin 风格**：分屏商务风。
- **Variant B — tsparticles 粒子背景**：动效炫酷风。

两版共用现有认证逻辑，纯前端改动，零后端改动。用户选定后再做收尾（删另一版、固定 `/login`）。

## 2. 公共部分

- 认证：两版都调 `auth.doLogin(username, password)` → 成功 `router.push('/')` → 失败 `useMessage().error('用户名或密码错误')`。逻辑与现版 `Login.vue` 一致，只是 UI 不同。
- 品牌：标题「数据库备份管理器」+ 副标题「Database Backup Agent」（保留现版）。
- 表单校验：保留现版的「用户名/密码非空」前置校验。
- 主题：跟随 Naive UI 既有明暗主题（不引入新主题体系）。

## 3. Variant A — SoybeanAdmin 风格（`LoginSoybean.vue`）

- 分屏布局（桌面）：
  - 左侧 ~55%：品牌区，深蓝→紫渐变背景，大标题 + 副标题 + 一句简短产品文案 + 几何装饰 SVG（圆/线）。
  - 右侧 ~45%：白色表单卡片（Naive UI `n-input` 用户名/密码 + `n-button` 登录），居中。
- 窄屏（< 768px）：自动堆叠为单列，品牌区缩为顶部条。
- 风格关键词：干净、商务、留足白。

## 4. Variant B — 粒子动画背景（`LoginParticles.vue`）

- 全屏 `@tsparticles/vue3` 粒子动画背景：
  - 深色基调（深蓝/近黑），中等密度连线粒子，缓慢漂移，轻鼠标互动（hover 推开）。
  - 用 `@tsparticles/slim` 引擎（`loadSlim`），体积可控。
- 中央玻璃拟态卡片（`backdrop-filter: blur` + 半透明白）含 Naive UI 表单。
- 风格关键词：动效、科技感、视觉冲击。

## 5. 对比机制

- `/login` 保留为唯一入口路由。`Login.vue` 改为薄壳：读 `route.query.style`：
  - `soybean`（默认）/ 缺省 → 渲染 `<LoginSoybean>`
  - `particles` → 渲染 `<LoginParticles>`
- 卡片右上角一个「看另一版」按钮：切换 `?style=` query（无刷新，`router.replace`）。
- 认证守卫不变（未登录仍跳 `/login`）。
- 评测方式：用 Playwright 对 `?style=soybean` 与 `?style=particles` 各截一张桌面截图，并排展示给用户。

## 6. 集成与构建

- 依赖：`npm install @tsparticles/vue3 @tsparticles/slim`（更新 `frontend/package.json` + `package-lock.json`）。
- 插件注册：`frontend/src/main.ts` 中 `app.use(Particles, { init: async engine => await loadSlim(engine) })`（具体 API 以 `@tsparticles/vue3` 当前版本为准）。
- 仅 `LoginParticles.vue` 使用粒子；其余页面无影响。
- Docker 重建：`docker compose up -d --build`，让 :8000 服务的 `dist` 含两版 + 粒子（Dockerfile 内 `npm ci` 会按更新后的 lock 安装 tsparticles）。

## 7. 文件清单

新增/修改（仅前端）：
- 新增 `frontend/src/views/login/LoginSoybean.vue`
- 新增 `frontend/src/views/login/LoginParticles.vue`
- 修改 `frontend/src/views/Login.vue`（改为薄壳：按 query 分派 + 切换按钮）
- 修改 `frontend/src/main.ts`（注册 tsparticles 插件）
- 修改 `frontend/package.json` / `package-lock.json`（新增 tsparticles 依赖）

## 8. 不在范围内（YAGNI / 收尾再做）

- 选定后的收尾（删另一版、移除 query 切换、固定 `/login`）——单独一轮。
- 忘记密码 / 注册 / 第三方登录等新流程。
- 后端任何改动。
- 国际化、自定义主题配置面板。
