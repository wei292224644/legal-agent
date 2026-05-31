"""tests/api conftest：提供 db_session + 把 maker 注入 main 模块。"""
import os

import pytest
import pytest_asyncio

# 触发 ORM 注册到 metadata，否则 create_all 不会建表
import db.models  # noqa: F401
from db.base import Base
from db.engine import create_engine_from_env, get_sessionmaker


@pytest.fixture(autouse=True)
def _setup_env_and_maker():
    """autouse: 设置 DATABASE_URL 并确保 main._maker 可用。"""
    os.environ.setdefault(
        "DATABASE_URL",
        "postgresql+psycopg://legal:legal@localhost:5432/legal_agent",
    )
    import main
    if main._maker is None:
        engine = create_engine_from_env()
        main._maker = get_sessionmaker(engine)


@pytest_asyncio.fixture
async def db_session():
    """提供 db_session；复用已有表，不 drop_all。"""
    engine = create_engine_from_env()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_local = get_sessionmaker(engine)

    # 注入测试专用的 maker，使 endpoint 的 async with _maker() 用测试库的事务
    import main
    main._maker = get_sessionmaker(engine)

    async with session_local() as session:
        yield session

    await engine.dispose()
