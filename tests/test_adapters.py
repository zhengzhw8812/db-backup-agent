import pytest
from app.adapters.base import get_adapter, register_adapter


class FakeAdapter:
    type = "fake"

    def dump(self, info, dest_path):
        pass


def test_get_unknown_type_raises():
    with pytest.raises(ValueError):
        get_adapter("does-not-exist")


def test_register_and_get(monkeypatch):
    from app.adapters import base
    monkeypatch.setitem(base._REGISTRY, "fake", FakeAdapter())
    assert isinstance(get_adapter("fake"), FakeAdapter)
