"""统一的时间助手:全仓用本模块取 UTC 当前时间。

datetime.utcnow() 自 Python 3.12 起弃用并将在未来版本移除。
这里返回 naive UTC(tzinfo=None):与既有 SQLite 存储格式完全一致,
零迁移;aware 化涉及历史数据回填,不在本次范围。"""
from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
