import json
from app.workers.progress import ProgressReporter, request_cancel


class FakeRedis:
    def __init__(self):
        self.published = []
        self._store = {}

    def publish(self, channel, msg):
        self.published.append((channel, msg))
        return 0

    def exists(self, key):
        return key in self._store

    def set(self, key, val):
        self._store[key] = val


def test_report_publishes_to_record_channel():
    fake = FakeRedis()
    ProgressReporter(42, fake).report("dump", "exporting")
    assert fake.published == [("job:42", json.dumps({"stage": "dump", "detail": "exporting"}))]


def test_cancel_flag_roundtrip():
    fake = FakeRedis()
    r = ProgressReporter(7, fake)
    assert r.is_cancelled() is False
    request_cancel(7, fake)
    assert r.is_cancelled() is True


def test_restore_namespace_is_isolated():
    fake = FakeRedis()
    ProgressReporter(5, fake, kind="restore").report("verify")
    ProgressReporter(5, fake).report("dump")
    channels = [ch for ch, _ in fake.published]
    assert "restore:5" in channels
    assert "job:5" in channels
    # 同一 record_id 不同命名空间互不干扰
    request_cancel(5, fake, kind="restore")
    assert ProgressReporter(5, fake, kind="restore").is_cancelled() is True
    assert ProgressReporter(5, fake).is_cancelled() is False
