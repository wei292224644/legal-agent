"""Async SQLAlchemy engine + sessionmaker 工厂。"""
import os

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine_from_env() -> AsyncEngine:
    """从 DATABASE_URL 环境变量创建 async engine。缺失时显式抛错——配置错误必须立刻显现。"""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    return create_async_engine(url, pool_pre_ping=True)


def get_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """构造 async session 工厂；expire_on_commit=False 让对象在事务外仍可用。"""
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
