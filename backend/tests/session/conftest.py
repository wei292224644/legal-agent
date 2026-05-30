"""session 子目录测试共用 fixture。

session 测试会构造真实 Orchestrator(默认 ha=HeavyAgent(...)),HeavyAgent
init 时调 get_agno_db() → PostgresDb(default URL) → 触发 psycopg 解析。
即使本机没装 psycopg,只要这里 autouse 把单例换成 InMemoryDb 就不会去解析 DSN。
"""

import pytest


@pytest.fixture(autouse=True)
def _agno_db_in_memory(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    from agno.db.in_memory import InMemoryDb  # noqa: PLC0415

    from agent.db import reset_agno_db_for_tests  # noqa: PLC0415
    reset_agno_db_for_tests(replacement=InMemoryDb())
    yield
    reset_agno_db_for_tests()
