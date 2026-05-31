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

    sm = async_sessionmaker(db_session.bind, expire_on_commit=False)
    ctx = ContextStore(session_id=_uuid.uuid4(), sessionmaker=sm)

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
