"""tests/db 公用 fixture：自动注入 DATABASE_URL,避免测试间环境耦合。"""
import os

import pytest


@pytest.fixture(autouse=True)
def _set_database_url():
    os.environ.setdefault(
        "DATABASE_URL",
        "postgresql+psycopg://legal:legal@localhost:5432/legal_agent",
    )
