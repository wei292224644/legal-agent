"""tests/db 公用 fixture：autouse 注入 DATABASE_URL + 提供干净的 db_session。"""
import os

import pytest
import pytest_asyncio

import db.models  # noqa: F401  # 触发 ORM 注册到 metadata
from db.base import Base
from db.engine import create_engine_from_env, get_sessionmaker


@pytest.fixture(autouse=True)
def _set_database_url():
    os.environ.setdefault(
        "DATABASE_URL",
        "postgresql+psycopg://legal:legal@localhost:5432/legal_agent",
    )


@pytest_asyncio.fixture
async def db_session():
    """提供 db_session；复用已有表，不 drop_all。"""
    engine = create_engine_from_env()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_local = get_sessionmaker(engine)
    async with session_local() as session:
        yield session
    await engine.dispose()
