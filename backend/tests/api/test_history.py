"""验证 /api/sessions/{sid}/history 端点：返回 utterance + suggestion 列表，按时序排列。"""
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from main import app
from models.utterance import Utterance
from repositories.sessions import SessionRepository
from repositories.suggestions import SuggestionRepository
from repositories.utterances import UtteranceRepository


@pytest.mark.asyncio
async def test_history_returns_empty_for_new_session(db_session):
    """新建 session 立即拉 history，utterances 和 suggestions 都是空数组。"""
    sid = await SessionRepository(db_session).create()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get(f"/api/sessions/{sid}/history")
    assert r.status_code == 200
    data = r.json()
    assert data["utterances"] == []
    assert data["suggestions"] == []


@pytest.mark.asyncio
async def test_history_returns_data_after_writes(db_session):
    """写入 utterance + suggestion 后，history 能拉到。"""
    sid = await SessionRepository(db_session).create()
    await UtteranceRepository(db_session).append(
        sid, Utterance(id="u1", text="你好", t_start=0, t_end=0.5,
                       speaker="lawyer", closed_by="vad"),
    )
    await SuggestionRepository(db_session).upsert_ready(
        sid, request_id="r1", text="建议", utt_id="u1",
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get(f"/api/sessions/{sid}/history")
    data = r.json()
    assert len(data["utterances"]) == 1
    assert data["utterances"][0]["id"] == "u1"
    assert data["utterances"][0]["text"] == "你好"
    assert len(data["suggestions"]) == 1
    assert data["suggestions"][0]["request_id"] == "r1"
    assert data["suggestions"][0]["text"] == "建议"


@pytest.mark.asyncio
async def test_history_returns_404_for_unknown_session(db_session):
    """陌生 session_id 返回 404——前端据此判断要不要新建。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get(f"/api/sessions/{uuid.uuid4()}/history")
    assert r.status_code == 404
