import gzip
from pathlib import Path
from app.core.archive import compress_file, sha256_of_file


def test_compress_then_gunzip_roundtrips(tmp_path):
    src = tmp_path / "a.sql"
    src.write_bytes(b"CREATE TABLE t (id int);\n")
    dest = tmp_path / "a.sql.gz"
    compress_file(src, dest)
    assert dest.exists()
    with gzip.open(dest, "rb") as f:
        assert f.read() == b"CREATE TABLE t (id int);\n"


def test_sha256_stable_and_distinct(tmp_path):
    a = tmp_path / "a"
    a.write_bytes(b"hello")
    b = tmp_path / "b"
    b.write_bytes(b"world")
    assert sha256_of_file(a) == sha256_of_file(a)  # 稳定
    assert sha256_of_file(a) != sha256_of_file(b)  # 不同内容不同摘要
    assert len(sha256_of_file(a)) == 64
