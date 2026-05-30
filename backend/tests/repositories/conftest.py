"""tests/repositories 公用 fixture：复用 db_session。"""
import os

import pytest
import pytest_asyncio

import db.models  # noqa: F401
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
    """每个测试用新的 engine + drop_all/create_all，避免污染。"""
    engine = create_engine_from_env()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    session_local = get_sessionmaker(engine)
    async with session_local() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
