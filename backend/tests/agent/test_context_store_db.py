"""验证 ContextStore 写穿 DB：append + profile worker 都落库，hydrate 能还原。"""
import asyncio

import pytest

from agent.context_store import ContextStore, ProfileEntry
from db.engine import get_sessionmaker
from models.utterance import Utterance
from repositories.profile_entries import ProfileEntryRepository
from repositories.sessions import SessionRepository
from repositories.utterances import UtteranceRepository


@pytest.mark.asyncio
async def test_append_writes_through_to_db(db_session):
    """append_utterance 后 DB 立即可查到。"""
    sid = await SessionRepository(db_session).create()
    maker = get_sessionmaker(db_session.bind)
    ctx = ContextStore(session_id=sid, sessionmaker=maker)
    await ctx.append_utterance(Utterance(
        id="u1", text="hello", t_start=0.0, t_end=0.5, closed_by="vad",
    ))
    items = await UtteranceRepository(db_session).list_by_session(sid)
    assert len(items) == 1
    assert items[0].id == "u1"


@pytest.mark.asyncio
async def test_hydrate_loads_existing_utterances(db_session):
    """新建 ContextStore + hydrate 后内存与 DB 一致。"""
    sid = await SessionRepository(db_session).create()
    await UtteranceRepository(db_session).append(
        sid, Utterance(id="u1", text="hi", t_start=0, t_end=0.1, closed_by="vad")
    )
    await ProfileEntryRepository(db_session).bulk_insert(
        sid, [ProfileEntry(key="k", value="v", timestamp=0.0, source_utt_id="u1", subject="本人")],
    )
    maker = get_sessionmaker(db_session.bind)
    ctx = ContextStore(session_id=sid, sessionmaker=maker)
    await ctx.hydrate()
    assert len(ctx.get_full_history()) == 1
    assert len(ctx.get_profile()) == 1


@pytest.mark.asyncio
async def test_enqueue_profile_writes_to_db(db_session):
    """profile worker 消费队列后 DB 可见——验证异步写穿路径。"""
    sid = await SessionRepository(db_session).create()
    await UtteranceRepository(db_session).append(
        sid, Utterance(id="u1", text="t", t_start=0, t_end=0.1, closed_by="vad")
    )
    maker = get_sessionmaker(db_session.bind)
    ctx = ContextStore(session_id=sid, sessionmaker=maker)
    await ctx.start_profile_worker()
    await ctx.enqueue_profile_update("u1", [
        ProfileEntry(key="职业", value="律师", timestamp=1.0, source_utt_id="u1", subject="本人"),
    ])
    # worker 异步消费，给一点时间
    await asyncio.sleep(0.5)
    await ctx.stop_profile_worker()
    db_entries = await ProfileEntryRepository(db_session).list_by_session(sid)
    assert len(db_entries) == 1
    assert db_entries[0].key == "职业"


def test_profile_entry_category_still_works():
    """ProfileEntry 数据类 category 字段正常——保留旧测试的核心意图。"""
    entry = ProfileEntry(key="月薪", value="25000", timestamp=0.0, source_utt_id="u1", category="收入")
    assert entry.category == "收入"
    entry_default = ProfileEntry(key="工龄", value="2年", timestamp=0.0, source_utt_id="u1")
    assert entry_default.category is None
