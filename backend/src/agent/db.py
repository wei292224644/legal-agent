"""Agno PostgresDb 单例。

生产用 Postgres,因为 HITL run 状态 + 多会话画像写并发量超过 SQLite 单写锁能扛的量级。
测试通过 reset_agno_db_for_tests(replacement=InMemoryDb()) 注入内存替身,不依赖 Postgres。
"""

from __future__ import annotations

from agno.db.base import BaseDb
from agno.db.postgres import PostgresDb

from config import AGNO_DB_URL

_db: BaseDb | None = None


def get_agno_db() -> BaseDb:
    """返回模块级 db 单例;首次调用时按 AGNO_DB_URL 建 PostgresDb。"""
    global _db
    if _db is None:
        _db = PostgresDb(db_url=AGNO_DB_URL)
    return _db


def reset_agno_db_for_tests(replacement: BaseDb | None = None) -> None:
    """清空模块级单例;可选注入替身(测试常用 InMemoryDb)。

    Args:
        replacement: 若提供,直接装入单例槽位;否则下次 get_agno_db 按 AGNO_DB_URL 重建。
    """
    global _db
    if _db is not None and hasattr(_db, "db_engine"):
        try:
            _db.db_engine.dispose()
        except Exception:
            pass
    _db = replacement
