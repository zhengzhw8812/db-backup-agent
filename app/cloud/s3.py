from __future__ import annotations
import time
from functools import lru_cache

from minio import Minio

from app.cloud.base import CloudConfig, register_storage


@lru_cache(maxsize=32)
def _build_client(endpoint: str, access_key: str, secret_key: str, secure: bool, region: str) -> Minio:
    """按(endpoint, 凭据)缓存 Minio 客户端,避免每次上传都新建连接池/TLS 握手。
    凭据轮换时 access_key/secret_key 变化 → 自然产生新缓存项。"""
    return Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure, region=region or None)


class S3StorageAdapter:
    """S3 兼容存储(MinIO / AWS S3 / R2 / B2 等),经 minio SDK。

    endpoint 为 host:port(无 scheme);secure 决定 https。minio SDK 的
    fput_object 对大文件自动分块上传。"""

    provider = "s3"
    _RETRY_ATTEMPTS = 3

    def _client(self, cfg: CloudConfig) -> Minio:
        return _build_client(cfg.endpoint, cfg.access_key, cfg.secret_key, cfg.secure, cfg.region or "")

    def _key(self, cfg: CloudConfig, key: str) -> str:
        return f"{cfg.prefix}/{key}" if cfg.prefix else key

    def _with_retry(self, fn, attempts: int = _RETRY_ATTEMPTS):
        """指数退避重试,吸收云存储偶发 5xx/连接重置。"""
        last = None
        for i in range(attempts):
            try:
                return fn()
            except Exception as exc:  # noqa: BLE001
                last = exc
                if i < attempts - 1:
                    time.sleep(0.5 * (2 ** i))
        raise last  # type: ignore[misc]

    def upload(self, cfg: CloudConfig, local_path: str, key: str) -> str:
        full = self._key(cfg, key)
        self._with_retry(lambda: self._client(cfg).fput_object(cfg.bucket, full, local_path))
        return f"s3://{cfg.bucket}/{full}"

    def delete(self, cfg: CloudConfig, key: str) -> None:
        self._with_retry(lambda: self._client(cfg).remove_object(cfg.bucket, self._key(cfg, key)))

    def list_prefix(self, cfg: CloudConfig, prefix: str) -> list[str]:
        full = self._key(cfg, prefix)
        objs = self._with_retry(lambda: list(self._client(cfg).list_objects(
            cfg.bucket, prefix=full, recursive=True)))
        strip = f"{cfg.prefix}/" if cfg.prefix else ""
        return [(o.object_name[len(strip):] if o.object_name.startswith(strip) else o.object_name)
                for o in objs]

    def test(self, cfg: CloudConfig) -> None:
        try:
            ok = self._with_retry(lambda: self._client(cfg).bucket_exists(cfg.bucket))
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(self._explain_test_failure(exc)) from exc
        if not ok:
            raise ValueError(f"存储桶不存在: {cfg.bucket}。请检查桶名拼写与 Region")

    @staticmethod
    def _explain_test_failure(exc: Exception) -> str:
        """把 SDK 原始异常翻译成可操作的中文指引。"""
        msg = f"{type(exc).__name__}: {exc}"
        text = str(exc).lower()
        if "ssl" in text or "certificate" in text:
            return (f"TLS 不匹配:{msg}。请核对 HTTPS 开关与本机端口"
                    "(HTTPS 一般是 443;MinIO/S3 兼容存储的 9000 等端口通常应关闭 HTTPS)")
        if any(k in text for k in ("connection", "timeout", "maxretry", "refused", "unreachable", "resolve")):
            return (f"连不上:{msg}。请检查 Endpoint 格式(应为 host:port,不带 http:// 前缀)、"
                    "端口是否正确(MinIO 常用 9000)以及网络可达性")
        if any(k in text for k in ("accessdenied", "invalidaccesskeyid", "signature", "403", "invalidtoken")):
            return f"认证失败:{msg}。请检查 Access Key / Secret Key 是否正确,以及该账号是否有此桶的访问权限"
        if "nosuchbucket" in text or "bucket" in text:
            return f"桶不存在:{msg}。请检查桶名拼写与 Region 设置"
        return f"连接失败:{msg}。请检查 Endpoint / 桶名 / 凭据 / 网络"


register_storage(S3StorageAdapter())
