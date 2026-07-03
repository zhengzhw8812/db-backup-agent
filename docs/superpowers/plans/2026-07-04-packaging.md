# 生产打包 (Production Packaging) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 把重写后的应用打成**单容器**部署(master spec §5/§14):多阶段 Dockerfile(node 打前端 → python:3.12-slim 运行;装 pg/mysql/redis 客户端 + redis-server),supervisord 同容器托管 **redis + uvicorn + arq worker** 三进程,FastAPI 托管前端 SPA(`/` 返回 index.html、客户端路由 fallback、`/api/*` 仍走 API),docker-compose 暴露 8000 + `/data` 卷。**本机有 Docker,需真 `docker build`/`docker run` 验证。**

**Architecture:** 单容器三进程(supervisord 守护),`/data` 卷持久化(sqlite/redis/backups/logs/keys),端口 8000。前端 Vite 构建产物拷到 `/app/static`,FastAPI 在 `static_dir` 存在时挂载 SPA fallback(条件挂载,故 dev/测试无该目录时 main 行为不变)。

**Tech Stack:** Docker multi-stage + supervisord + redis + uvicorn + arq。

**关键决策(文档化):**
- 本轮只构建/验证 **amd64**(本机架构);buildx 多架构(arm64 + mongodump/mariadb 架构差异)留后续。
- **mongodump 暂不装入容器**(mongodb-database-tools 不在 apt、体积大、国内下载易失败)——pg/mysql/redis/sqlite 客户端可用;Mongo 备份在容器内暂不可用,文档标注。
- redis 用自带 `redis-server`,配置 `bind 127.0.0.1`、`dir /data/redis`、AOF 持久化。
- 首启管理员:`APP_INITIAL_ADMIN_PASSWORD` 环境变量(已有 `ensure_account` 逻辑)。
- env 前缀 `APP_`:`APP_DATA_DIR=/data`、`APP_REDIS_URL=redis://127.0.0.1:6379/0`、`APP_INITIAL_ADMIN_USER/PASSWORD`、可选 `APP_SECRET_KEY/APP_FERNET_KEY`。

**前置:** Phase 1–通知完成;`minio` 已在 pyproject;`app/config.py` 用 `APP_` 前缀。

---

## 文件结构
- Modify `app/config.py` — 加 `static_dir` 设置
- Modify `app/main.py` — 条件挂载 SPA fallback
- Test `tests/test_spa.py` — SPA fallback + /api 不受影响
- Create `deploy/supervisord.conf`、`deploy/redis.conf`、`deploy/entrypoint.sh`(覆盖 legacy)
- Create `Dockerfile`(覆盖 legacy)、`.dockerignore`
- Create `docker-compose.yml`(覆盖 legacy)

---

## Tasks

### Task 1: FastAPI 托管 SPA(static_dir + fallback)

**Files:** Modify `app/config.py`, `app/main.py`; Test `tests/test_spa.py`

- [ ] **Step 1: 写失败测试** —— 创建 `tests/test_spa.py`:
```python
import pytest


@pytest.fixture
def spa_client(client, tmp_path, monkeypatch):
    """给 app 挂一个临时 static_dir(含 index.html + assets/x.js),reload main。"""
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html>SPA</html>")
    (static / "assets" / "x.js").write_text("console.log(1)")
    monkeypatch.setenv("APP_STATIC_DIR", str(static))
    from importlib import reload
    from app import config, main
    reload(config); reload(main)
    from fastapi.testclient import TestClient
    with TestClient(main.app) as c:
        yield c


def test_spa_root_returns_index(client):
    # 默认无 static_dir → / 走 404(无挂载),不崩
    r = client.get("/")
    assert r.status_code in (404, 200)


def test_spa_fallback_serves_index_and_assets(spa_client):
    assert spa_client.get("/").text == "<html>SPA</html>"
    assert spa_client.get("/dashboard").text == "<html>SPA</html>"  # 客户端路由 fallback
    assert spa_client.get("/assets/x.js").text == "console.log(1)"


def test_api_still_works_with_spa(spa_client):
    # /api/v1/* 不被 SPA fallback 吞掉
    assert spa_client.get("/api/v1/health").status_code == 200
```
> `/api/v1/health` 已存在(health router)。`test_spa_root_returns_index` 用默认 client(无 static_dir)仅断言不崩。

- [ ] **Step 2: 跑测试确认失败** —— `python3 -m pytest tests/test_spa.py -v` → FAIL(static_dir/挂载不存在)。

- [ ] **Step 3: config.py 加 static_dir** —— 在 `app/config.py` 的 `Settings` 加字段:
```python
    static_dir: Path = Path("/app/static")
```
(放在 `data_dir` 之后。)

- [ ] **Step 4: main.py 挂载 SPA fallback** —— 在 `app/main.py` 的 `create_app()` 里,所有 `app.include_router(...)` 之后、`return app` 之前,加:
```python
    # 生产:托管前端 SPA(仅当 static_dir 存在;dev 由 Vite 服务,测试无该目录 → 跳过)
    static_dir = settings.static_dir
    if static_dir.exists():
        from fastapi.responses import FileResponse

        @app.get("/{full_path:path}")
        async def _spa(full_path: str):
            candidate = static_dir / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(static_dir / "index.html")
```
> `/api/*`、`/docs`、`/openapi.json` 均为已注册路由,先于 catch-all 匹配,不受影响。

- [ ] **Step 5: 跑测试确认通过** —— `python3 -m pytest tests/test_spa.py -v` → PASS(3)。再 `python3 -m pytest -p no:warnings -q` 全绿(~118)。

- [ ] **Step 6: 提交** —— `git add app/config.py app/main.py tests/test_spa.py && git commit -m "feat(packaging): FastAPI 托管 SPA(static_dir 条件挂载 + fallback)"`

---

### Task 2: deploy/ 进程配置(supervisord + redis + entrypoint)

**Files:** Create `deploy/supervisord.conf`、`deploy/redis.conf`、`deploy/entrypoint.sh`(覆盖 legacy)

- [ ] **Step 1: supervisord.conf** —— 覆盖 `deploy/supervisord.conf`:
```ini
[supervisord]
nodaemon=true
logfile=/data/logs/supervisord.log
pidfile=/tmp/supervisord.pid
user=root

[program:redis]
command=redis-server /etc/redis/redis-app.conf
autorestart=true
priority=10
stdout_logfile=/data/logs/redis.log
stderr_logfile=/data/logs/redis.err.log

[program:web]
command=uvicorn app.main:app --host 0.0.0.0 --port 8000
directory=/app
autorestart=true
priority=20
stdout_logfile=/data/logs/web.log
stderr_logfile=/data/logs/web.err.log

[program:worker]
command=arq app.workers.app.WorkerSettings
directory=/app
autorestart=true
priority=30
stdout_logfile=/data/logs/worker.log
stderr_logfile=/data/logs/worker.err.log
```

- [ ] **Step 2: redis.conf** —— 创建 `deploy/redis.conf`:
```ini
bind 127.0.0.1
port 6379
dir /data/redis
dbfilename dump.rdb
appendonly yes
appendfilename "appendonly.aof"
save 60 1
```

- [ ] **Step 3: entrypoint.sh** —— 覆盖 `deploy/entrypoint.sh`:
```bash
#!/bin/sh
set -e
# /data 可能是空卷挂载 —— 确保子目录存在
mkdir -p /data/sqlite /data/redis /data/backups /data/logs /data/keys
exec supervisord -n -c /etc/supervisor/supervisord.conf
```
> 之后 Dockerfile 会 `chmod +x`。

- [ ] **Step 4: 提交** —— `git add deploy/supervisord.conf deploy/redis.conf deploy/entrypoint.sh && git commit -m "feat(packaging): supervisord/redis/entrypoint 进程配置"`

---

### Task 3: Dockerfile(多阶段)+ .dockerignore

**Files:** Create `Dockerfile`(覆盖 legacy)、`.dockerignore`

- [ ] **Step 1: .dockerignore** —— 创建 `.dockerignore`:
```
.git
.github
**/__pycache__
**/*.pyc
.pytest_cache
data
backups
frontend/node_modules
frontend/dist
docs
Images
legacy
*.md
.claude
.env
```

- [ ] **Step 2: Dockerfile** —— 覆盖根 `Dockerfile`:
```dockerfile
# ---------- Stage 1: 构建前端 ----------
FROM node:20-bookworm-slim AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---------- Stage 2: 运行时 ----------
FROM python:3.12-slim-bookworm

# DB 客户端 + redis + supervisord(mongodump 暂略,见计划说明)
RUN apt-get update && apt-get install -y --no-install-recommends \
        postgresql-client \
        mariadb-client \
        redis-server \
        supervisor \
        gzip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python 依赖(先装,利用层缓存)
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

# 应用代码
COPY app ./app

# 前端构建产物 → FastAPI 托管
COPY --from=frontend /fe/dist /app/static

# 进程配置
COPY deploy/supervisord.conf /etc/supervisor/conf.d/app.conf
COPY deploy/redis.conf /etc/redis/redis-app.conf
COPY deploy/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# 默认环境(可被 -e 覆盖)
ENV APP_DATA_DIR=/data \
    APP_REDIS_URL=redis://127.0.0.1:6379/0 \
    APP_STATIC_DIR=/app/static

VOLUME /data
EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
```
> supervisord 默认读 `/etc/supervisor/supervisord.conf`,其 `include` `/etc/supervisor/conf.d/*.conf`。Debian 的 supervisor 包提供基础 supervisord.conf;我们的 app.conf 放 conf.d。

- [ ] **Step 3: 提交** —— `git add Dockerfile .dockerignore && git commit -m "feat(packaging): 多阶段 Dockerfile(node 打 FE → python 运行)"`

---

### Task 4: docker-compose.yml

**Files:** Create `docker-compose.yml`(覆盖 legacy)

- [ ] **Step 1: compose** —— 覆盖 `docker-compose.yml`:
```yaml
services:
  db-backup:
    build: .
    image: db-backup-agent:latest
    container_name: db-backup-agent
    restart: unless-stopped
    ports:
      - "8000:8000"
    volumes:
      - ./data:/data
    environment:
      APP_INITIAL_ADMIN_USER: ${APP_INITIAL_ADMIN_USER:-admin}
      APP_INITIAL_ADMIN_PASSWORD: ${APP_INITIAL_ADMIN_PASSWORD:-changeme}
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health').read()"]
      interval: 30s
      timeout: 10s
      start_period: 40s
      retries: 3
```
> healthcheck 用 python(镜像内置)避免再装 curl。

- [ ] **Step 2: 提交** —— `git add docker-compose.yml && git commit -m "feat(packaging): docker-compose(端口 8000 + /data 卷)"`

---

### Task 5: Docker 构建 + 运行验证(controller 执行,非 subagent)

由控制器(controller)在本机执行(有 Docker + 国内镜像):

- [ ] **Step 1: 构建** —— `sudo docker build -t db-backup-agent:test .`(amd64)。预期成功;若失败,据报错修 Dockerfile/deploy 配置后重试。
- [ ] **Step 2: 运行** ——
```bash
sudo docker rm -f dba-test 2>/dev/null
sudo docker run -d --name dba-test -p 8000:8000 \
  -v "$PWD/data-smoke:/data" \
  -e APP_INITIAL_ADMIN_PASSWORD=admin123 \
  db-backup-agent:test
```
- [ ] **Step 3: 等待启动 + 验证** ——
```bash
sleep 6
sudo docker exec dba-test supervisorctl status      # redis/web/worker 均 RUNNING
curl -fsS http://localhost:8000/api/v1/health        # 200
curl -fsS http://localhost:8000/ | head -1           # index.html
curl -fsS http://localhost:8000/dashboard | head -1  # index.html(SPA fallback)
curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}' -i | head -1   # 200
```
- [ ] **Step 4: 清理** —— `sudo docker rm -f dba-test && sudo docker rmi db-backup-agent:test 2>/dev/null; rm -rf data-smoke`
- [ ] **Step 5: 记录验证结果** —— controller 在收尾报告里贴构建/运行输出摘要;如有调整,补一个 `fix(packaging): ...` 提交。

---

## 完成标准
- `docker build` 成功;`docker run` 后 supervisor 三进程 RUNNING;`/api/v1/health` 200;`/` 与 `/dashboard` 返回 index.html;登录端点 200。
- 后端测试全绿(~118,含 SPA fallback);前端 `npm run build` 通过(构建已在镜像里)。
- `docker-compose up` 可起(端口 8000、`./data:/data`)。

## 留给后续
- buildx 多架构镜像(amd64+arm64)+ `build_and_push.sh` 更新。
- mongodump 装入镜像(mongodb-database-tools)。
- 首启引导页(无 `APP_INITIAL_ADMIN_PASSWORD` 时浏览器引导设置管理员)。
- 生产硬化:非 root 运行、`--read-only` + tmpfs、secret 管理(不依赖 env 明文)。
