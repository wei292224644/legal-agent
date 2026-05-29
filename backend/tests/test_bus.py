"""Tests for UtteranceBus — 事件总线解耦 STT 与 Agent."""

import asyncio
from datetime import datetime

import pytest

from agent.bus import UtteranceBus
from agent.context_store import ContextStore
from agent.intent_router import IntentResult
from agent.orchestrator import Orchestrator
from models.utterance import Utterance


class StubIntentRouter:
    async def classify(self, text: str, speaker: str | None = None):
        return IntentResult(severity="simple", intent_type="query_law", rationale="stub")


class StubProfileAgent:
    async def extract(self, text: str, speaker: str | None, history: list, existing_profile: dict[str, str], utt_id: str = ""):
        return []


class StubHeavyAgent:
    async def analyze_quick(self, utt, intent_type, generation):
        return f"quick result for {utt.text}"

    async def analyze(self, utt, intent_type, generation):
        return f"deep result for {utt.text}"


@pytest.mark.asyncio
async def test_bus_delivers_utterance_to_handler():
    """Tracer bullet: utt 入 bus → Orchestrator consumer 处理 → suggestion callback 触发."""
    ctx = ContextStore()
    await ctx.start_profile_worker()

    orch = Orchestrator(
        ctx,
        ir=StubIntentRouter(),
        pa=StubProfileAgent(),
        ha=StubHeavyAgent(),
    )

    bus = UtteranceBus(maxsize=10)
    orch.attach_bus(bus)
    await orch.start()

    suggestions = []

    async def on_suggestion(text, meta):
        suggestions.append((text, meta))

    orch.set_suggestion_callback(on_suggestion)

    utt = Utterance(
        id="u_1",
        text="违法解除赔多少？",
        speaker="client",
        t_start=0.0,
        t_end=1.0,
        timestamp=datetime.now(),
    )
    await bus.put(utt)

    # 等待 consumer 处理完
    await asyncio.sleep(0.5)

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
        ok = await bus.put(
            Utterance(id=f"u_{i}", text=f"t{i}", t_start=0.0, t_end=1.0)
        )
        assert ok is True

    # 第 3 个应被拒绝
    ok = await bus.put(
        Utterance(id="u_2", text="overflow", t_start=0.0, t_end=1.0)
    )
    assert ok is False


@pytest.mark.asyncio
async def test_shutdown_stops_bus_consumer():
    """shutdown() 后 bus consumer 不再处理新 utterance。"""
    ctx = ContextStore()
    await ctx.start_profile_worker()

    orch = Orchestrator(
        ctx,
        ir=StubIntentRouter(),
        pa=StubProfileAgent(),
        ha=StubHeavyAgent(),
    )

    bus = UtteranceBus(maxsize=10)
    orch.attach_bus(bus)
    await orch.start()

    suggestions = []
    orch.set_suggestion_callback(lambda text, meta: suggestions.append(meta))

    # 先处理一个
    await bus.put(Utterance(id="u_1", text="first", t_start=0.0, t_end=1.0))
    await asyncio.sleep(0.5)
    assert len(suggestions) == 1

    # shutdown
    await orch.shutdown()

    # 再 put 一个，不应被处理
    await bus.put(Utterance(id="u_2", text="after shutdown", t_start=0.0, t_end=1.0))
    await asyncio.sleep(0.5)
    assert len(suggestions) == 1, "shutdown 后不应再处理新 utterance"


class SlowStubHeavyAgent:
    """第一个 utt 延迟 1s，第二个立即返回，用于验证并发性。"""

    async def analyze_quick(self, utt, intent_type, generation):
        if utt.id == "u_slow":
            await asyncio.sleep(1.0)
        return f"result for {utt.text}"

    async def analyze(self, utt, intent_type, generation):
        return f"deep result for {utt.text}"


@pytest.mark.asyncio
async def test_heavy_agent_runs_concurrently():
    """HeavyAgent.analyze_quick 在多个 utt 间应并发：快的先完成，不被慢的阻塞。"""
    ctx = ContextStore()
    await ctx.start_profile_worker()

    orch = Orchestrator(
        ctx,
        ir=StubIntentRouter(),
        pa=StubProfileAgent(),
        ha=SlowStubHeavyAgent(),
    )

    bus = UtteranceBus(maxsize=10)
    orch.attach_bus(bus)
    await orch.start()

    suggestions = []

    async def on_suggestion(text, meta):
        suggestions.append(meta)

    orch.set_suggestion_callback(on_suggestion)

    # 先放慢的，再放快的
    await bus.put(Utterance(id="u_slow", text="slow", t_start=0.0, t_end=1.0))
    await bus.put(Utterance(id="u_fast", text="fast", t_start=0.0, t_end=1.0))

    # 只等 0.5s（不足以等 u_slow 的 1s delay）
    await asyncio.sleep(0.5)

    # 如果 HeavyAgent 并发：u_fast 应先完成并 emit suggestion
    assert len(suggestions) >= 1
    assert suggestions[0]["utt_id"] == "u_fast"

    await orch.shutdown()
