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
