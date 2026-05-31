"""Re-export db_session fixture from tests/db/conftest for agent integration tests."""
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
    """提供 db_session；复用已有表，不 drop_all。"""
    engine = create_engine_from_env()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = get_sessionmaker(engine)
    async with SessionLocal() as session:
        yield session
    await engine.dispose()
