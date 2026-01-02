# Dockerfile
FROM debian:bookworm-slim

# 1. 安装添加源所需的预备工具
RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    lsb-release \
    ca-certificates \
    wget \
    && rm -rf /var/lib/apt/lists/*

# 2. 添加 PostgreSQL 官方源 (为了获取 pg-client-17)
# 导入 GPG Key
RUN curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /usr/share/keyrings/postgresql-keyring.gpg
# 添加源列表
RUN echo "deb [signed-by=/usr/share/keyrings/postgresql-keyring.gpg] http://apt.postgresql.org/pub/repos/apt/ bookworm-pgdg main" > /etc/apt/sources.list.d/pgdg.list

# 3. 根据架构安装 MySQL 客户端 或 MariaDB 客户端
# 注意: Oracle 的 MySQL 官方源在 Debian ARM64 上支持有限，且需要特定配置。
# 在 ARM64 上使用 MariaDB 客户端是最佳替代方案 (兼容 MySQL 协议)。
RUN ARCH="$(dpkg --print-architecture)" && \
    if [ "$ARCH" = "amd64" ]; then \
        echo "检测到 x86_64 (amd64) 架构，安装 MySQL 官方客户端..." && \
        curl -fSL -o /tmp/mysql-apt-config.deb https://dev.mysql.com/get/mysql-apt-config_0.8.36-1_all.deb && \
        DEBIAN_FRONTEND=noninteractive dpkg -i /tmp/mysql-apt-config.deb && \
        rm /tmp/mysql-apt-config.deb && \
        apt-get update && \
        apt-get install -y mysql-client; \
    else \
        echo "检测到 $ARCH 架构，安装 MariaDB 客户端..." && \
        apt-get update && \
        apt-get install -y mariadb-client; \
    fi

# 4. 安装其他通用工具
# 注意: 这里再次 apt-get update 确保包列表是最新的 (虽然上面可能运行过，但为了稳健性)
RUN apt-get update && apt-get install -y \
    postgresql-client-17 \
    cron \
    gzip \
    bash \
    jq \
    python3 \
    python3-flask \
    procps \
    && rm -rf /var/lib/apt/lists/*

# 5. 配置工作目录和脚本
WORKDIR /backups

COPY ./scripts/backup.sh /usr/local/bin/backup.sh
COPY ./scripts/entrypoint.sh /usr/local/bin/entrypoint.sh

# 移除BOM, 修正行结尾, 并赋予执行权限
RUN sed -i -e '1s/^\xEF\xBB\xBF//' -e 's/\r$//' /usr/local/bin/backup.sh && \
    sed -i -e '1s/^\xEF\xBB\xBF//' -e 's/\r$//' /usr/local/bin/entrypoint.sh && \
    chmod +x /usr/local/bin/backup.sh && \
    chmod +x /usr/local/bin/entrypoint.sh

COPY app.py /app.py
COPY templates /templates
COPY static /static

EXPOSE 5001

COPY ./config/crontab /etc/cron.d/backup-cron
RUN chmod 0644 /etc/cron.d/backup-cron && \
    crontab /etc/cron.d/backup-cron

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
