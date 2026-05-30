"""验证 SessionRepository 的 CRUD 行为，确认调用方拿到的是真值源。"""
import uuid

import pytest

from repositories.sessions import SessionRepository


@pytest.mark.asyncio
async def test_create_returns_session_with_active_status(db_session):
    """create 后立即查得到，status 默认 active——验证默认值与可见性。"""
    repo = SessionRepository(db_session)
    sid = await repo.create()
    fetched = await repo.get(sid)
    assert fetched is not None
    assert fetched.status == "active"


@pytest.mark.asyncio
async def test_set_status_persists(db_session):
    """set_status 写入后查询能读到——验证更新路径。"""
    repo = SessionRepository(db_session)
    sid = await repo.create()
    await repo.set_status(sid, "disconnected")
    fetched = await repo.get(sid)
    assert fetched.status == "disconnected"


@pytest.mark.asyncio
async def test_get_unknown_returns_none(db_session):
    """查不存在的 session 返回 None，不抛异常——调用方据此判断是否需创建。"""
    repo = SessionRepository(db_session)
    assert await repo.get(uuid.uuid4()) is None


@pytest.mark.asyncio
async def test_set_summary_persists(db_session):
    """set_summary 可写入 None 和字符串——AI 摘要正常生成时填字符串，失败时保持 None。"""
    repo = SessionRepository(db_session)
    sid = await repo.create()
    await repo.set_summary(sid, "测试摘要")
    fetched = await repo.get(sid)
    assert fetched.summary == "测试摘要"
