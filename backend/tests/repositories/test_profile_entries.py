"""验证 profile 仓储：批量插入、按 session 列出（timestamp 升序）。"""
import pytest

from agent.context_store import ProfileEntry
from models.utterance import Utterance
from repositories.profile_entries import ProfileEntryRepository
from repositories.sessions import SessionRepository
from repositories.utterances import UtteranceRepository


@pytest.mark.asyncio
async def test_bulk_insert_and_list_timestamp_order(db_session):
    """批量插入后按 timestamp 升序返回——画像在前端展示时按事实出现顺序排列。"""
    sid = await SessionRepository(db_session).create()
    await UtteranceRepository(db_session).append(
        sid, Utterance(id="u1", text="t", t_start=0, t_end=0.1, closed_by="vad")
    )
    repo = ProfileEntryRepository(db_session)
    await repo.bulk_insert(sid, [
        ProfileEntry(key="职业", value="律师", timestamp=2.0, source_utt_id="u1", subject="本人"),
        ProfileEntry(key="年龄", value="30", timestamp=1.0, source_utt_id="u1", subject="本人"),
    ])
    items = await repo.list_by_session(sid)
    assert [e.key for e in items] == ["年龄", "职业"]
