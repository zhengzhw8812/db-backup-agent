from app.cloud.base import CloudConfig, StorageAdapter, register_storage, get_storage
from app.cloud import s3  # noqa: F401  触发注册
