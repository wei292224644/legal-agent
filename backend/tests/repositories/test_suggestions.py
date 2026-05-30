"""验证 suggestion 仓储：upsert 幂等、按 request_id 更新到 ready。"""
import uuid

import pytest

from models.utterance import Utterance
from repositories.sessions import SessionRepository
from repositories.suggestions import SuggestionRepository
from repositories.utterances import UtteranceRepository


@pytest.mark.asyncio
async def test_upsert_pending_then_ready(db_session):
    """先 upsert pending,再 upsert ready,最终一行,kind/text 已更新——验证幂等键工作。"""
    sid = await SessionRepository(db_session).create()
    await UtteranceRepository(db_session).append(
        sid, Utterance(id="u1", text="t", t_start=0, t_end=0.1, closed_by="vad")
    )
    repo = SuggestionRepository(db_session)
    await repo.upsert_pending(sid, utt_id="u1", request_id="r1", preview_topic="A", preview_rationale="B")
    await repo.upsert_ready(sid, request_id="r1", text="answer")
    items = await repo.list_by_session(sid)
    assert len(items) == 1
    assert items[0]["kind"] == "ready"
    assert items[0]["text"] == "answer"
    assert items[0]["preview_topic"] == "A"


@pytest.mark.asyncio
async def test_upsert_ready_without_pending_creates_row(db_session):
    """没有 pending 直接 ready 也应该插入(短路径场景)——保证 callback 顺序错乱时数据不丢。"""
    sid = await SessionRepository(db_session).create()
    await UtteranceRepository(db_session).append(
        sid, Utterance(id="u1", text="t", t_start=0, t_end=0.1, closed_by="vad")
    )
    repo = SuggestionRepository(db_session)
    await repo.upsert_ready(sid, request_id="r1", text="answer", utt_id="u1")
    items = await repo.list_by_session(sid)
    assert len(items) == 1
    assert items[0]["text"] == "answer"
