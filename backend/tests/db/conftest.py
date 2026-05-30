"""tests/db 公用 fixture：autouse 注入 DATABASE_URL + 提供干净的 db_session。"""
import os

import pytest
import pytest_asyncio

from db.base import Base
from db.engine import create_engine_from_env, get_sessionmaker
import db.models  # noqa: F401  # 触发 ORM 注册到 metadata


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
    SessionLocal = get_sessionmaker(engine)
    async with SessionLocal() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
