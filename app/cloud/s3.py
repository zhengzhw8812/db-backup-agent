from __future__ import annotations

from minio import Minio

from app.cloud.base import CloudConfig, register_storage


class S3StorageAdapter:
    """S3 兼容存储(MinIO / AWS S3 / R2 / B2 等),经 minio SDK。

    endpoint 为 host:port(无 scheme);secure 决定 https。minio SDK 的
    fput_object 对大文件自动分块上传。"""

    provider = "s3"

    def _client(self, cfg: CloudConfig) -> Minio:
        return Minio(cfg.endpoint, access_key=cfg.access_key, secret_key=cfg.secret_key,
                     secure=cfg.secure, region=cfg.region)

    def _key(self, cfg: CloudConfig, key: str) -> str:
        return f"{cfg.prefix}/{key}" if cfg.prefix else key

    def upload(self, cfg: CloudConfig, local_path: str, key: str) -> str:
        full = self._key(cfg, key)
        self._client(cfg).fput_object(cfg.bucket, full, local_path)
        return f"s3://{cfg.bucket}/{full}"

    def delete(self, cfg: CloudConfig, key: str) -> None:
        self._client(cfg).remove_object(cfg.bucket, self._key(cfg, key))

    def test(self, cfg: CloudConfig) -> None:
        if not self._client(cfg).bucket_exists(cfg.bucket):
            raise ValueError(f"存储桶不存在: {cfg.bucket}")


register_storage(S3StorageAdapter())
