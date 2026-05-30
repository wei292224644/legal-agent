"""验证 ORM 模型字段、约束、外键关系，避免迁移后查询时才发现 schema 漏。"""
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from db.models import ProfileEntry, Session, Suggestion, Utterance


@pytest.mark.asyncio
async def test_session_roundtrip(db_session):
    """插入与查询 session——验证主键/默认值/状态字段全部生效。"""
    sid = uuid.uuid4()
    db_session.add(Session(id=sid, status="active"))
    await db_session.commit()
    fetched = (await db_session.execute(select(Session).where(Session.id == sid))).scalar_one()
    assert fetched.status == "active"
    assert fetched.lawyer_id == "lawyer-default"


@pytest.mark.asyncio
async def test_utterance_session_fk(db_session):
    """utterance.session_id 引用不存在的 session 必须抛 IntegrityError——验证外键约束。"""
    db_session.add(Utterance(
        id="utt-1", session_id=uuid.uuid4(), seq=1, text="hi",
        t_start=0.0, t_end=0.5, closed_by="vad", content_hash="abc",
    ))
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_utterance_seq_unique_per_session(db_session):
    """同一 session 下重复 seq 必须冲突——防止并发 append 重号。"""
    sid = uuid.uuid4()
    db_session.add(Session(id=sid, status="active"))
    db_session.add(Utterance(
        id="utt-a", session_id=sid, seq=1, text="a",
        t_start=0, t_end=0.1, closed_by="vad", content_hash="h1",
    ))
    await db_session.commit()
    db_session.add(Utterance(
        id="utt-b", session_id=sid, seq=1, text="b",
        t_start=0.1, t_end=0.2, closed_by="vad", content_hash="h2",
    ))
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_suggestion_request_id_unique(db_session):
    """同 session 下重复 request_id 必须冲突——保证幂等键唯一性。"""
    sid = uuid.uuid4()
    db_session.add(Session(id=sid, status="active"))
    db_session.add(Utterance(
        id="utt-1", session_id=sid, seq=1, text="t",
        t_start=0, t_end=0.1, closed_by="vad", content_hash="h",
    ))
    await db_session.commit()
    db_session.add(Suggestion(
        id=uuid.uuid4(), session_id=sid, utt_id="utt-1",
        request_id="req-1", kind="pending",
    ))
    await db_session.commit()
    db_session.add(Suggestion(
        id=uuid.uuid4(), session_id=sid, utt_id="utt-1",
        request_id="req-1", kind="ready", text="ok",
    ))
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_profile_entry_source_utt_set_null(db_session):
    """删除 utterance 后 profile.source_utt_id 变 NULL——避免悬空外键。"""
    sid = uuid.uuid4()
    db_session.add(Session(id=sid, status="active"))
    await db_session.flush()  # 先落库 session，保证 FK 顺序
    db_session.add(Utterance(
        id="utt-x", session_id=sid, seq=1, text="t",
        t_start=0, t_end=0.1, closed_by="vad", content_hash="h",
    ))
    await db_session.flush()  # 先落库 utterance，保证 FK 顺序
    entry = ProfileEntry(
        id=uuid.uuid4(), session_id=sid, source_utt_id="utt-x",
        key="职业", value="律师", timestamp=0.0, subject="本人",
    )
    db_session.add(entry)
    await db_session.commit()
    await db_session.delete(await db_session.get(Utterance, "utt-x"))
    await db_session.commit()
    await db_session.refresh(entry)
    assert entry.source_utt_id is None
