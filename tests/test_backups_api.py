import pytest
from app.db import session as _session
from app.db.models import BackupRecord


@pytest.fixture
def authed(client):
    from app.services.account_service import ensure_account
    from app.db.models import DbConnection
    db = _session._SessionLocal()
    try:
        ensure_account(db, "admin", "pw")
        db.add(DbConnection(name="c", type="pg"))
        db.commit()
    finally:
        db.close()
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "pw"})
    return client


def _make_record(file_relpath="pg_1_1.sql.gz", content=b"x"):
    # 函数内读取 settings,确保拿到 conftest reload 后的实例(指向 tmp_path)。
    from app.config import settings
    bdir = settings.data_dir / "backups"
    bdir.mkdir(parents=True, exist_ok=True)
    (bdir / file_relpath).write_bytes(content)
    db = _session._SessionLocal()
    rec = BackupRecord(connection_id=1, trigger="manual", status="success",
                       file_path=file_relpath, size=len(content), checksum="c",
                       started_at=__import__("datetime").datetime.utcnow())
    db.add(rec); db.commit(); db.refresh(rec)
    rid = rec.id
    db.close()
    return rid


def test_list_and_download(authed):
    rid = _make_record()
    listed = authed.get("/api/v1/backups").json()
    assert any(b["id"] == rid for b in listed)
    r = authed.get(f"/api/v1/backups/{rid}/download")
    assert r.status_code == 200
    assert r.content == b"x"


def test_delete(authed):
    rid = _make_record()
    assert authed.delete(f"/api/v1/backups/{rid}").status_code == 204
    assert authed.get(f"/api/v1/backups/{rid}/download").status_code == 404


def test_traversal_rejected(authed):
    rid = _make_record()
    db = _session._SessionLocal()
    rec = db.get(BackupRecord, rid)
    rec.file_path = "../../etc/passwd"
    db.commit(); db.close()
    assert authed.get(f"/api/v1/backups/{rid}/download").status_code == 404


def test_list_pagination(authed):
    for _ in range(3):
        _make_record()
    page1 = authed.get("/api/v1/backups?limit=2&offset=0").json()
    page2 = authed.get("/api/v1/backups?limit=2&offset=2").json()
    assert len(page1) == 2
    assert len(page2) == 1  # 共 3 条,第二页只剩 1 条
