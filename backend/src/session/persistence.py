"""Session 持久化后端抽象与实现。

支持 InMemory（测试）和 SQLite（生产）两种后端。
Snapshot 失败仅记录日志，不抛异常——内存中仍保有完整状态。
"""

from __future__ import annotations

import json
import sqlite3
from abc import ABC, abstractmethod
from pathlib import Path


class PersistenceBackend(ABC):
    """持久化后端抽象。"""

    @abstractmethod
    def save(self, session_id: str, data: dict) -> None:
        """保存 session 数据；失败时只记录日志，不抛异常。"""

    @abstractmethod
    def load(self, session_id: str) -> dict | None:
        """加载 session 数据；不存在时返回 None。"""

    @abstractmethod
    def delete(self, session_id: str) -> None:
        """删除 session 数据。"""

    @abstractmethod
    def list_ids(self) -> list[str]:
        """返回所有已持久化的 session_id。"""


class InMemoryBackend(PersistenceBackend):
    """内存后端，用于测试。"""

    def __init__(self) -> None:
        self._store: dict[str, dict] = {}

    def save(self, session_id: str, data: dict) -> None:
        self._store[session_id] = data

    def load(self, session_id: str) -> dict | None:
        return self._store.get(session_id)

    def delete(self, session_id: str) -> None:
        self._store.pop(session_id, None)

    def list_ids(self) -> list[str]:
        return list(self._store.keys())


class SQLiteBackend(PersistenceBackend):
    """SQLite 后端，用于生产。"""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._db_path = str(db_path)
        self._ensure_table()

    def _ensure_table(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    data BLOB NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    status TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_status_updated ON sessions(status, updated_at)"
            )

    def save(self, session_id: str, data: dict) -> None:
        try:
            payload = json.dumps(data, ensure_ascii=False)
            created_at = data.get("created_at", 0.0)
            updated_at = data.get("last_active_at", 0.0)
            status = data.get("status", "unknown")
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO sessions (session_id, data, created_at, updated_at, status)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                        data = excluded.data,
                        updated_at = excluded.updated_at,
                        status = excluded.status
                    """,
                    (session_id, payload, created_at, updated_at, status),
                )
        except Exception as exc:
            # Snapshot 失败只记录日志，不抛异常
            print(f"[WARN] Session snapshot failed for {session_id}: {exc}")

    def load(self, session_id: str) -> dict | None:
        try:
            with sqlite3.connect(self._db_path) as conn:
                row = conn.execute(
                    "SELECT data FROM sessions WHERE session_id = ?", (session_id,)
                ).fetchone()
                if row is None:
                    return None
                return json.loads(row[0])
        except Exception as exc:
            print(f"[WARN] Session load failed for {session_id}: {exc}")
            return None

    def delete(self, session_id: str) -> None:
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        except Exception as exc:
            print(f"[WARN] Session delete failed for {session_id}: {exc}")

    def list_ids(self) -> list[str]:
        try:
            with sqlite3.connect(self._db_path) as conn:
                rows = conn.execute("SELECT session_id FROM sessions").fetchall()
                return [r[0] for r in rows]
        except Exception as exc:
            print(f"[WARN] Session list_ids failed: {exc}")
            return []
