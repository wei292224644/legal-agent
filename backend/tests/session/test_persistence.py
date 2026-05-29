"""持久化后端测试。"""

import tempfile

import pytest

from session.persistence import InMemoryBackend, SQLiteBackend


class TestInMemoryBackend:
    def test_save_and_load(self):
        be = InMemoryBackend()
        be.save("s1", {"foo": 1})
        assert be.load("s1") == {"foo": 1}

    def test_load_missing_returns_none(self):
        be = InMemoryBackend()
        assert be.load("nope") is None

    def test_delete(self):
        be = InMemoryBackend()
        be.save("s1", {"foo": 1})
        be.delete("s1")
        assert be.load("s1") is None

    def test_list_ids(self):
        be = InMemoryBackend()
        be.save("a", {})
        be.save("b", {})
        assert set(be.list_ids()) == {"a", "b"}


class TestSQLiteBackend:
    def test_save_and_load(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        be = SQLiteBackend(path)
        be.save("s1", {"foo": 1, "created_at": 0.0, "last_active_at": 0.0, "status": "active"})
        assert be.load("s1") == {"foo": 1, "created_at": 0.0, "last_active_at": 0.0, "status": "active"}

    def test_load_missing_returns_none(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        be = SQLiteBackend(path)
        assert be.load("nope") is None

    def test_delete(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        be = SQLiteBackend(path)
        be.save("s1", {"created_at": 0.0, "last_active_at": 0.0, "status": "active"})
        be.delete("s1")
        assert be.load("s1") is None

    def test_list_ids(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        be = SQLiteBackend(path)
        be.save("a", {"created_at": 0.0, "last_active_at": 0.0, "status": "active"})
        be.save("b", {"created_at": 0.0, "last_active_at": 0.0, "status": "active"})
        assert set(be.list_ids()) == {"a", "b"}

    def test_save_upsert(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name
        be = SQLiteBackend(path)
        be.save("s1", {"v": 1, "created_at": 0.0, "last_active_at": 0.0, "status": "active"})
        be.save("s1", {"v": 2, "created_at": 0.0, "last_active_at": 1.0, "status": "disconnected"})
        assert be.load("s1")["v"] == 2
