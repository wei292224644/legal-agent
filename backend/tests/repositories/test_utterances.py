"""验证 utterance 仓储：追加自动分配 seq，列表按时序返回。"""
import pytest

from models.utterance import Utterance
from repositories.sessions import SessionRepository
from repositories.utterances import UtteranceRepository


def _utt(uid: str, t: float) -> Utterance:
    return Utterance(id=uid, text=f"t{uid}", t_start=t, t_end=t + 0.1, closed_by="vad")


@pytest.mark.asyncio
async def test_append_assigns_increasing_seq(db_session):
    """连续 append 的 seq 单调递增——保证 list_by_session 能稳定排序。"""
    sid = await SessionRepository(db_session).create()
    repo = UtteranceRepository(db_session)
    s1 = await repo.append(sid, _utt("u1", 0.0))
    s2 = await repo.append(sid, _utt("u2", 1.0))
    assert s2 == s1 + 1


@pytest.mark.asyncio
async def test_list_returns_in_seq_order(db_session):
    """list_by_session 必须按 seq 升序——刷新页面后用户看到的顺序与说话顺序一致。"""
    sid = await SessionRepository(db_session).create()
    repo = UtteranceRepository(db_session)
    await repo.append(sid, _utt("u1", 0.0))
    await repo.append(sid, _utt("u2", 1.0))
    items = await repo.list_by_session(sid)
    assert [u.id for u in items] == ["u1", "u2"]


@pytest.mark.asyncio
async def test_list_empty_for_unknown_session(db_session):
    """陌生 session_id 返回空列表，不抛异常——hydration API 才能用统一空数组应答。"""
    import uuid as _u

    repo = UtteranceRepository(db_session)
    assert await repo.list_by_session(_u.uuid4()) == []
