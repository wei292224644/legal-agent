"""Session 模块 — 管理会谈生命周期、持久化与恢复。"""

from session.manager import SessionManager
from session.models import SessionState
from session.persistence import InMemoryBackend, PersistenceBackend, SQLiteBackend
from session.serializer import SessionSerializer

__all__ = [
    "SessionManager",
    "SessionState",
    "PersistenceBackend",
    "InMemoryBackend",
    "SQLiteBackend",
    "SessionSerializer",
]
