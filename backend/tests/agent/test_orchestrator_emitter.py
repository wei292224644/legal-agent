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


@pytest.mark.asyncio
async def test_run_child_emits_insight_ready_and_persists(orch):
    """非 gated 路径:HeavyAgent 直出文本 → InsightReady 事件 + repo.insert_direct。
    业务意图:大多数 utterance 走这条路径,事件丢失等于"实时洞察"一直空白。"""
    from unittest.mock import AsyncMock
    from agent.events import InsightReady
    from models.utterance import Utterance

    fake_emitter = FakeEmitter()
    fake_repo = FakeRepoWriter()
    orch.set_event_emitter(fake_emitter)
    orch.set_repo_writer(fake_repo)

    class _FakeRun:
        is_paused = False
        content = "这是直接洞察"

    orch._ha.arun = AsyncMock(return_value=_FakeRun())

    utt = Utterance(id="u1", text="某客户陈述", speaker="client",
                    t_start=0.0, t_end=1.0)
    generation = await orch._ctx.append_utterance(utt)
    await orch._run_child(utt, generation)

    insight_evts = [e for e in fake_emitter.received if isinstance(e, InsightReady)]
    assert len(insight_evts) == 1
    evt = insight_evts[0]
    assert evt.utt_id == "u1"
    assert evt.text == "这是直接洞察"
    assert evt.id.startswith("ins_")

    direct_calls = [c for c in fake_repo.calls if c[0] == "insert_direct"]
    assert len(direct_calls) == 1
    assert direct_calls[0][1] == {"utt_id": "u1", "text": "这是直接洞察"}


@pytest.mark.asyncio
async def test_run_child_skips_empty_insight(orch):
    """空 content 不应入 DB 也不应发事件——避免占位卡片污染 UI。"""
    from unittest.mock import AsyncMock
    from agent.events import InsightReady
    from models.utterance import Utterance

    fake_emitter = FakeEmitter()
    fake_repo = FakeRepoWriter()
    orch.set_event_emitter(fake_emitter)
    orch.set_repo_writer(fake_repo)

    class _FakeRun:
        is_paused = False
        content = "   "

    orch._ha.arun = AsyncMock(return_value=_FakeRun())
    utt = Utterance(id="u1", text="x", speaker="client", t_start=0.0, t_end=1.0)
    generation = await orch._ctx.append_utterance(utt)
    await orch._run_child(utt, generation)

    assert [e for e in fake_emitter.received if isinstance(e, InsightReady)] == []
    assert fake_repo.calls == []


@pytest.mark.asyncio
async def test_run_child_emits_analysis_proposed_and_persists(orch):
    """gated 路径:HeavyAgent paused 等确认 → AnalysisProposed + upsert_pending。"""
    from unittest.mock import AsyncMock
    from agent.events import AnalysisProposed
    from models.utterance import Utterance

    fake_emitter = FakeEmitter()
    fake_repo = FakeRepoWriter()
    orch.set_event_emitter(fake_emitter)
    orch.set_repo_writer(fake_repo)

    class _FakeReq:
        class tool_execution:
            tool_args = {"topic": "本案是否构成违约", "rationale": "对方未履行交付义务"}
        def confirm(self): pass
        def reject(self, _): pass

    class _FakeRun:
        is_paused = True
        run_id = "agno_run_xyz"
        active_requirements = [_FakeReq()]
        requirements = active_requirements
        content = None

    orch._ha.arun = AsyncMock(return_value=_FakeRun())
    utt = Utterance(id="u1", text="x", speaker="client", t_start=0.0, t_end=1.0)
    generation = await orch._ctx.append_utterance(utt)
    await orch._run_child(utt, generation)

    proposed = [e for e in fake_emitter.received if isinstance(e, AnalysisProposed)]
    assert len(proposed) == 1
    evt = proposed[0]
    assert evt.utt_id == "u1"
    assert evt.topic == "本案是否构成违约"
    assert evt.rationale == "对方未履行交付义务"
    assert evt.request_id.startswith("req_")

    pending_calls = [c for c in fake_repo.calls if c[0] == "upsert_pending"]
    assert len(pending_calls) == 1
    assert pending_calls[0][1]["utt_id"] == "u1"
    assert pending_calls[0][1]["request_id"] == evt.request_id

    # PendingRequest 必须仍在内存以便后续 confirm
    assert evt.request_id in orch._pending


@pytest.mark.asyncio
async def test_confirm_analysis_emits_ready_and_persists(orch):
    """confirm → continue_run 返回 → AnalysisReady + mark_running + upsert_ready。
    业务意图:律师等了卡片确认深析,结果必须实时回到 UI 同时落 DB 便于刷新恢复。"""
    from unittest.mock import AsyncMock
    from agent.events import AnalysisReady
    from agent.orchestrator import PendingRequest

    fake_emitter = FakeEmitter()
    fake_repo = FakeRepoWriter()
    orch.set_event_emitter(fake_emitter)
    orch.set_repo_writer(fake_repo)

    class _FakeReq:
        def confirm(self): pass
        def reject(self, _): pass

    class _FakeRun:
        is_paused = False
        content = "深度分析结论"
        run_id = "agno_run_1"
        active_requirements = [_FakeReq()]
        requirements = active_requirements

    orch._pending["req_abc"] = PendingRequest(
        request_id="req_abc", run_id="agno_run_1", utt_id="u1",
        generation=0, preview={"topic": "", "rationale": ""},
        run_output=_FakeRun(),
    )
    orch._ha.acontinue_run = AsyncMock(return_value=_FakeRun())

    ok = await orch.confirm_analysis("req_abc")
    assert ok is True

    ready = [e for e in fake_emitter.received if isinstance(e, AnalysisReady)]
    assert len(ready) == 1
    assert ready[0].request_id == "req_abc"
    assert ready[0].utt_id == "u1"
    assert ready[0].text == "深度分析结论"

    op_names = [c[0] for c in fake_repo.calls]
    assert "mark_running" in op_names
    assert "upsert_ready" in op_names
