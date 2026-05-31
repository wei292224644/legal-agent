"""Orchestrator 事件路径：fake emitter + in-memory repo writer 验证。

设计目的：把 Orchestrator 从 sessionmaker 与 WebSocket 隔离开测。
- emitter 只收 list[OutboundEvent]
- repo writer 实现 SuggestionRepository 用到的几个方法，存 list[dict]
"""
from __future__ import annotations

import asyncio
import pytest
import pytest_asyncio
from dataclasses import dataclass, field

from agent.context_store import ContextStore
from agent.events import OutboundEvent


@dataclass
class FakeEmitter:
    received: list[OutboundEvent] = field(default_factory=list)

    async def __call__(self, evt: OutboundEvent) -> None:
        self.received.append(evt)


@dataclass
class FakeRepoWriter:
    """Orchestrator 通过它写 DB；这里只记账。"""
    calls: list[tuple[str, dict]] = field(default_factory=list)

    async def insert_direct(self, *, utt_id: str, text: str) -> None:
        self.calls.append(("insert_direct", {"utt_id": utt_id, "text": text}))

    async def upsert_pending(self, *, utt_id: str, request_id: str,
                              preview_topic: str | None,
                              preview_rationale: str | None) -> None:
        self.calls.append(("upsert_pending", {
            "utt_id": utt_id, "request_id": request_id,
            "preview_topic": preview_topic, "preview_rationale": preview_rationale,
        }))

    async def mark_running(self, request_id: str) -> None:
        self.calls.append(("mark_running", {"request_id": request_id}))

    async def upsert_ready(self, *, request_id: str, text: str, utt_id: str | None) -> None:
        self.calls.append(("upsert_ready", {
            "request_id": request_id, "text": text, "utt_id": utt_id,
        }))

    async def mark_dismissed(self, request_id: str) -> None:
        self.calls.append(("mark_dismissed", {"request_id": request_id}))

    async def mark_expired(self, request_id: str) -> None:
        self.calls.append(("mark_expired", {"request_id": request_id}))


@pytest_asyncio.fixture
async def orch(db_session):
    """用 db_session 派生 sessionmaker 给 ContextStore；Orchestrator
    用 fake emitter + repo writer（不走真实 DB,与 ctx 的 DB 隔离）。"""
    import uuid as _uuid
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from agent.orchestrator import Orchestrator
    from repositories.sessions import SessionRepository

    sm = async_sessionmaker(db_session.bind, expire_on_commit=False)
    sid = _uuid.uuid4()
    async with sm() as s:
        await SessionRepository(s).create(session_id=sid)
    ctx = ContextStore(session_id=sid, sessionmaker=sm)

    # 关掉 PA/Gate/HA（这一任务只验 wiring，不验业务）
    class _NoopGate:
        async def is_relevant(self, _utt):
            return False

    class _NoopPA:
        async def extract(self, **_):
            return []

    class _NoopHA:
        async def arun(self, _utt):
            return None

    o = Orchestrator(
        ctx=ctx,
        gate=_NoopGate(),
        pa=_NoopPA(),
        ha=_NoopHA(),
        session_id="sess",
        user_id="u",
    )
    o.set_event_emitter(FakeEmitter())
    o.set_repo_writer(FakeRepoWriter())
    yield o


@pytest.mark.asyncio
async def test_emitter_swallows_errors(orch):
    """emitter 抛错不应中断 Orchestrator——这是稳定性保证。"""
    async def boom(_evt):
        raise RuntimeError("ws gone")

    orch.set_event_emitter(boom)
    # 直接调内部 emit；不应抛出
    from agent.events import Pong
    await orch._emit_event(Pong())


def test_setters_exist(orch):
    """set_event_emitter / set_repo_writer 是新公共接口。"""
    assert callable(getattr(orch, "set_event_emitter"))
    assert callable(getattr(orch, "set_repo_writer"))


@pytest.mark.asyncio
async def test_handle_utterance_emits_profile_updated(orch):
    """客户句子 → PA 返回 entries → emit ProfileUpdated。
    业务意图：画像数据每次更新都要让前端实时看到，不能只入 DB。"""
    from unittest.mock import AsyncMock
    from agent.events import ProfileUpdated
    from agent.context_store import ProfileEntry
    from models.utterance import Utterance

    fake_emitter = FakeEmitter()
    orch.set_event_emitter(fake_emitter)

    entries = [
        ProfileEntry(key="姓名", value="张三", subject="client", timestamp=0.0,
                     source_utt_id="u1"),
        ProfileEntry(key="年龄", value="30", subject="client", timestamp=0.0,
                     source_utt_id="u1"),
    ]
    orch._pa.extract = AsyncMock(return_value=entries)

    utt = Utterance(id="u1", text="我叫张三今年三十", speaker="client",
                    t_start=0.0, t_end=1.0)
    await orch.handle_utterance(utt)

    profile_evts = [e for e in fake_emitter.received if isinstance(e, ProfileUpdated)]
    assert len(profile_evts) == 1
    assert {(p.key, p.value, p.subject) for p in profile_evts[0].entries} == {
        ("姓名", "张三", "client"), ("年龄", "30", "client"),
    }


@pytest.mark.asyncio
async def test_handle_utterance_lawyer_skips_profile_event(orch):
    """律师句子不跑 PA,自然不应 emit ProfileUpdated。"""
    from agent.events import ProfileUpdated
    from models.utterance import Utterance

    fake_emitter = FakeEmitter()
    orch.set_event_emitter(fake_emitter)

    utt = Utterance(id="u1", text="您好", speaker="lawyer",
                    t_start=0.0, t_end=1.0)
    await orch.handle_utterance(utt)

    profile_evts = [e for e in fake_emitter.received if isinstance(e, ProfileUpdated)]
    assert profile_evts == []
