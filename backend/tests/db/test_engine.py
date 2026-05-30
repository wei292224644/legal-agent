"""测试 async engine 能与真实 Postgres 建立连接并执行简单查询。"""
import pytest
from sqlalchemy import text

from db.engine import create_engine_from_env, get_sessionmaker


@pytest.mark.asyncio
async def test_engine_connects_to_postgres():
    """engine 能连上 Postgres 并执行 SELECT 1——验证连接串与驱动配置正确。"""
    engine = create_engine_from_env()
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        assert result.scalar_one() == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_sessionmaker_yields_async_session():
    """session 工厂能产出可用的 AsyncSession——避免 maker 配置写错。"""
    engine = create_engine_from_env()
    session_local = get_sessionmaker(engine)
    async with session_local() as session:
        result = await session.execute(text("SELECT 2"))
        assert result.scalar_one() == 2
    await engine.dispose()
