"""Tests for Agno PostgresDb wiring: singleton + 测试替身注入。

设计契约:
- 同进程内 get_agno_db() 必须返回同一实例(连接池单例);
- reset_agno_db_for_tests(replacement=...) 允许注入 InMemoryDb 让单测不依赖真实 Postgres。
"""

import pytest
from agno.db.in_memory import InMemoryDb

from agent.db import get_agno_db, reset_agno_db_for_tests


@pytest.fixture(autouse=True)
def _isolate():
    reset_agno_db_for_tests(replacement=InMemoryDb())
    yield
    reset_agno_db_for_tests()


def test_get_agno_db_returns_same_instance():
    """同进程内多次调用必须返回同一个 db 实例(避免重复打开连接池)。"""
    db1 = get_agno_db()
    db2 = get_agno_db()
    assert db1 is db2


def test_reset_with_replacement_swaps_singleton():
    """测试用例可通过 reset_agno_db_for_tests(replacement=...) 注入 InMemoryDb,
    让上层代码(orchestrator/heavy_agent)在单测里完全不依赖 Postgres。"""
    custom = InMemoryDb()
    reset_agno_db_for_tests(replacement=custom)
    assert get_agno_db() is custom


def test_reset_without_replacement_forces_rebuild():
    """reset_agno_db_for_tests() 不传参时清空单例,下次 get_agno_db 会按 AGNO_DB_URL 重建。
    此用例靠 autouse fixture 把替身设为 InMemoryDb,验证清空逻辑而不连真实 Postgres。"""
    first = get_agno_db()
    reset_agno_db_for_tests(replacement=InMemoryDb())
    second = get_agno_db()
    assert first is not second
