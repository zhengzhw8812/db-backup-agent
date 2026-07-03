FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl gnupg2 ca-certificates supervisor redis-server \
        postgresql-client default-mysql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY app/ ./app/
RUN pip install --no-cache-dir .

COPY deploy/ ./deploy/
COPY .env.example ./

ENV APP_DATA_DIR=/data \
    APP_PORT=5001

EXPOSE 5001
RUN chmod +x /app/deploy/entrypoint.sh
CMD ["/app/deploy/entrypoint.sh"]
