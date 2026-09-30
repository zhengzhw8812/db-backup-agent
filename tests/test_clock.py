from datetime import datetime, timezone

from app.core.clock import utcnow


def test_utcnow_naive_and_fresh():
    now = utcnow()
    assert now.tzinfo is None  # naive:与既有 SQLite 存储格式一致
    delta = datetime.now(timezone.utc).replace(tzinfo=None) - now
    assert abs(delta.total_seconds()) < 5
