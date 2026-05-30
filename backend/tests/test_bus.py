"""Tests for UtteranceBus — 事件总线解耦 STT 与 Agent。"""

import asyncio
from unittest.mock import MagicMock

import pytest

from agent.bus import UtteranceBus
from agent.context_store import ContextStore
from agent.orchestrator import Orchestrator
from models.utterance import Utterance


@pytest.fixture(autouse=True)
def _mock_env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    from agno.db.in_memory import InMemoryDb  # noqa: PLC0415

    from agent.db import reset_agno_db_for_tests  # noqa: PLC0415
    reset_agno_db_for_tests(replacement=InMemoryDb())


class _StubGate:
    async def is_relevant(self, utt) -> bool:
        return True


class _StubPA:
    async def extract(self, **kwargs):
        return []


def _completed_run(content: str, run_id: str = "run_1"):
    r = MagicMock()
    r.is_paused = False
    r.content = content
    r.run_id = run_id
    return r


class _StubHA:
    """每次 arun 立即返回完成态 run,供 bus tracer 测试用。"""

    async def arun(self, utt):
        return _completed_run(f"quick result for {utt.text}")


@pytest.mark.asyncio
async def test_bus_delivers_utterance_to_handler():
    """Tracer bullet: utt 入 bus → Orchestrator consumer 处理 → suggestion callback 触发。"""
    ctx = ContextStore()
    await ctx.start_profile_worker()

    orch = Orchestrator(ctx, gate=_StubGate(), pa=_StubPA(), ha=_StubHA())

    bus = UtteranceBus(maxsize=10)
    orch.attach_bus(bus)
    await orch.start()

    suggestions = []

    async def on_suggestion(text, meta):
        suggestions.append((text, meta))

    orch.set_suggestion_callback(on_suggestion)

    utt = Utterance(id="u_1", text="违法解除赔多少？", speaker="client", t_start=0.0, t_end=1.0)
    await bus.put(utt)

    # 等待 consumer 处理完
    await asyncio.sleep(0.3)

    assert len(suggestions) == 1
    text, meta = suggestions[0]
    assert text == "quick result for 违法解除赔多少？"
    assert meta["kind"] == "ready"

    await orch.shutdown()


@pytest.mark.asyncio
async def test_bus_full_returns_false():
    """有界队列满时 put 返回 False，不阻塞生产者。"""
    bus = UtteranceBus(maxsize=2)

    # 快速填满队列（不启动 consumer）
    for i in range(2):
        ok = await bus.put(Utterance(id=f"u_{i}", text=f"t{i}", t_start=0.0, t_end=1.0))
        assert ok is True

    # 第 3 个应被拒绝
    ok = await bus.put(Utterance(id="u_2", text="overflow", t_start=0.0, t_end=1.0))
    assert ok is False


@pytest.mark.asyncio
async def test_shutdown_stops_bus_consumer():
    """shutdown() 后 bus consumer 不再处理新 utterance。"""
    ctx = ContextStore()
    await ctx.start_profile_worker()

    orch = Orchestrator(ctx, gate=_StubGate(), pa=_StubPA(), ha=_StubHA())

    bus = UtteranceBus(maxsize=10)
    orch.attach_bus(bus)
    await orch.start()

    suggestions = []
    orch.set_suggestion_callback(lambda text, meta: suggestions.append(meta))

    # 先处理一个
    await bus.put(Utterance(id="u_1", text="first", speaker="client", t_start=0.0, t_end=1.0))
    await asyncio.sleep(0.3)
    assert len(suggestions) == 1

    # shutdown
    await orch.shutdown()

    # 再 put 一个，不应被处理
    await bus.put(Utterance(id="u_2", text="after shutdown", speaker="client", t_start=0.0, t_end=1.0))
    await asyncio.sleep(0.3)
    assert len(suggestions) == 1, "shutdown 后不应再处理新 utterance"


class _SlowFastHA:
    """第一句 u_slow 等 1s,第二句立即返回,验证 _spawn_inflight 不阻塞主循环。"""

    async def arun(self, utt):
        if utt.id == "u_slow":
            await asyncio.sleep(1.0)
        return _completed_run(f"result for {utt.text}")


@pytest.mark.asyncio
async def test_child_runs_concurrently():
    """child run 在多个 utt 间应并发:_spawn_inflight 让快的先 emit,不被慢的阻塞。"""
    ctx = ContextStore()
    await ctx.start_profile_worker()

    orch = Orchestrator(ctx, gate=_StubGate(), pa=_StubPA(), ha=_SlowFastHA())

    bus = UtteranceBus(maxsize=10)
    orch.attach_bus(bus)
    await orch.start()

    suggestions = []

    async def on_suggestion(text, meta):
        suggestions.append(meta)

    orch.set_suggestion_callback(on_suggestion)

    # 先放慢的,再放快的
    await bus.put(Utterance(id="u_slow", text="slow", speaker="client", t_start=0.0, t_end=1.0))
    await bus.put(Utterance(id="u_fast", text="fast", speaker="client", t_start=0.0, t_end=1.0))

    # 0.5s 不足以等 u_slow 的 1s delay,但 u_fast 应已 emit
    await asyncio.sleep(0.5)

    # 注意:u_fast 在 u_slow 后入 bus,但因 child 并发,u_fast 完成时 generation 已是 2,
    # 而 u_slow 完成时 generation 也是 2 → u_slow 被 stale check 丢弃。
    # 这里只断言 u_fast 出现且早于 0.5s,验证并发性。
    fast_metas = [m for m in suggestions if m["utt_id"] == "u_fast"]
    assert len(fast_metas) == 1, "u_fast 应在 0.5s 内 emit,证明 child 真的并发"

    await orch.shutdown()
