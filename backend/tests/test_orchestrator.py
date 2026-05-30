"""Tests for Orchestrator — gate-only spawn + run-state 反应。"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from agent.context_store import ContextStore
from agent.orchestrator import Orchestrator
from models.utterance import Utterance


@pytest.fixture(autouse=True)
def _mock_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    from agno.db.in_memory import InMemoryDb  # noqa: PLC0415

    from agent.db import reset_agno_db_for_tests  # noqa: PLC0415
    reset_agno_db_for_tests(replacement=InMemoryDb())


@pytest_asyncio.fixture
async def store():
    ctx = ContextStore()
    await ctx.start_profile_worker()
    return ctx


def _completed_run(content: str, run_id: str = "run_1"):
    r = MagicMock()
    r.is_paused = False
    r.content = content
    r.run_id = run_id
    return r


def _paused_run(topic: str, rationale: str, run_id: str = "run_1"):
    req = MagicMock()
    req.tool_execution.tool_args = {"topic": topic, "rationale": rationale}
    r = MagicMock()
    r.is_paused = True
    r.run_id = run_id
    r.active_requirements = [req]
    return r


@pytest.mark.asyncio
async def test_gate_false_does_not_spawn_child(store, mock_relevance_gate):
    """relevance=false → 不 spawn,但 PA 仍跑(画像兜底)。"""
    gate = mock_relevance_gate(is_relevant=False)
    pa = MagicMock()
    pa.extract = AsyncMock(return_value=[])
    ha = MagicMock()
    ha.arun = AsyncMock(side_effect=AssertionError("relevance=false 不应 spawn"))

    orch = Orchestrator(store, gate=gate, pa=pa, ha=ha)
    orch.set_suggestion_callback(lambda t, m: None)

    utt = Utterance(id="u_1", text="好的", speaker="client", t_start=0.0, t_end=1.0)
    await orch.handle_utterance(utt)
    await asyncio.sleep(0.1)

    pa.extract.assert_awaited_once()
    ha.arun.assert_not_awaited()


@pytest.mark.asyncio
async def test_gate_true_completed_run_emits_ready(store, mock_relevance_gate):
    """relevance=true + child completed(未踩 gated)→ 直接推 ready。"""
    gate = mock_relevance_gate(is_relevant=True)
    pa = MagicMock()
    pa.extract = AsyncMock(return_value=[])
    ha = MagicMock()
    ha.arun = AsyncMock(return_value=_completed_run("法条第47条…"))

    orch = Orchestrator(store, gate=gate, pa=pa, ha=ha)
    suggestions = []
    orch.set_suggestion_callback(lambda t, m: suggestions.append((t, m)))

    await orch.handle_utterance(Utterance(id="u_1", text="N+1怎么算", speaker="client", t_start=0.0, t_end=1.0))
    await asyncio.sleep(0.1)

    assert len(suggestions) == 1
    text, meta = suggestions[0]
    assert "第47条" in text
    assert meta["kind"] == "ready"


@pytest.mark.asyncio
async def test_gate_true_paused_run_emits_pending_with_preview(store, mock_relevance_gate):
    """child 踩 gated → emit pending,meta.preview 来自 tool_args。"""
    gate = mock_relevance_gate(is_relevant=True)
    pa = MagicMock()
    pa.extract = AsyncMock(return_value=[])
    ha = MagicMock()
    ha.arun = AsyncMock(return_value=_paused_run("胜率评估", "需要全画像与多步推理"))

    orch = Orchestrator(store, gate=gate, pa=pa, ha=ha)
    suggestions = []
    orch.set_suggestion_callback(lambda t, m: suggestions.append((t, m)))

    await orch.handle_utterance(Utterance(id="u_1", text="能赢吗", speaker="client", t_start=0.0, t_end=1.0))
    await asyncio.sleep(0.1)

    assert len(suggestions) == 1
    text, meta = suggestions[0]
    assert text is None
    assert meta["kind"] == "pending"
    assert "request_id" in meta
    assert meta["preview"]["topic"] == "胜率评估"
    assert meta["preview"]["rationale"] == "需要全画像与多步推理"


@pytest.mark.asyncio
async def test_stale_completed_run_is_dropped(store, mock_relevance_gate):
    """child 在飞期间又有新 utterance 进来 → 该次完成的回答 stale,不推送。"""
    gate = mock_relevance_gate(is_relevant=True)
    pa = MagicMock()
    pa.extract = AsyncMock(return_value=[])
    ha = MagicMock()

    first_done = asyncio.Event()
    second_arun_started = asyncio.Event()

    async def staged_arun(utt):
        if utt.id == "u_1":
            await first_done.wait()
            return _completed_run("旧问题的迟到答案")
        # 第二句 child 立即返回,让其 ready 不污染断言
        second_arun_started.set()
        return _completed_run("新问题的及时答案")

    ha.arun = staged_arun

    orch = Orchestrator(store, gate=gate, pa=pa, ha=ha)
    suggestions = []
    orch.set_suggestion_callback(lambda t, m: suggestions.append((t, m)))

    # 第一句触发慢 child;还没完成就来第二句让 generation 走远
    await orch.handle_utterance(Utterance(id="u_1", text="问题A", speaker="client", t_start=0.0, t_end=1.0))
    await asyncio.sleep(0.05)
    await orch.handle_utterance(Utterance(id="u_2", text="问题B", speaker="client", t_start=1.0, t_end=2.0))
    # 确保第二句的 child 已经完成、generation=2 已落地
    await second_arun_started.wait()
    await asyncio.sleep(0.05)
    first_done.set()
    await asyncio.sleep(0.1)

    # 旧 child 完成时 generation 已不匹配,不应出现在结果里
    ready_texts = [t for t, m in suggestions if m["kind"] == "ready"]
    assert "旧问题的迟到答案" not in ready_texts, "stale generation 的答案必须被丢弃"
    assert "新问题的及时答案" in ready_texts, "新问题应正常输出"


@pytest.mark.asyncio
async def test_profile_fallback_when_gate_false(store, mock_relevance_gate):
    """gate=false 不 gate PA:含关键事实的 client 句仍进画像。"""
    gate = mock_relevance_gate(is_relevant=False)
    pa = MagicMock()

    from agent.context_store import ProfileEntry  # noqa: PLC0415
    pa.extract = AsyncMock(return_value=[ProfileEntry(key="入职日期", value="2019-03", timestamp=0.0, source_utt_id="u_1")])

    ha = MagicMock()
    orch = Orchestrator(store, gate=gate, pa=pa, ha=ha)
    orch.set_suggestion_callback(lambda t, m: None)

    await orch.handle_utterance(Utterance(id="u_1", text="我2019年3月入职的", speaker="client", t_start=0.0, t_end=1.0))
    await asyncio.sleep(0.1)

    profile = store.get_profile()
    assert any(e.key == "入职日期" for e in profile)


@pytest.mark.asyncio
async def test_lawyer_skips_pa_but_still_runs_gate(store, mock_relevance_gate):
    """律师发言:不调 PA,但仍过 gate(律师可能显式求助)。"""
    gate_calls = []

    class SpyGate:
        async def is_relevant(self, utt):
            gate_calls.append(utt.speaker)
            return False

    pa = MagicMock()
    pa.extract = AsyncMock(return_value=[])
    ha = MagicMock()

    orch = Orchestrator(store, gate=SpyGate(), pa=pa, ha=ha)
    orch.set_suggestion_callback(lambda t, m: None)

    await orch.handle_utterance(Utterance(id="u_1", text="您工作多久了？", speaker="lawyer", t_start=0.0, t_end=1.0))
    await asyncio.sleep(0.05)

    assert gate_calls == ["lawyer"]
    pa.extract.assert_not_called()


@pytest.mark.asyncio
async def test_uncertain_speaker_treated_as_client(store, mock_relevance_gate):
    """声纹 uncertain 归一为 client,与旧契约保持一致。"""
    gate = mock_relevance_gate(is_relevant=False)
    pa = MagicMock()
    pa.extract = AsyncMock(return_value=[])
    ha = MagicMock()

    orch = Orchestrator(store, gate=gate, pa=pa, ha=ha)
    orch.set_suggestion_callback(lambda t, m: None)

    await orch.handle_utterance(Utterance(id="u_1", text="两年三个月", speaker="uncertain", t_start=0.0, t_end=1.0))
    await asyncio.sleep(0.05)

    assert pa.extract.call_args.kwargs["speaker"] == "client"
    assert store.get_full_history()[-1].speaker == "client"


@pytest.mark.asyncio
async def test_bus_consumer_survives_handler_exception(store):
    """gate 抛异常不应杀死 bus consumer。"""
    from agent.bus import UtteranceBus  # noqa: PLC0415

    class FlakyGate:
        def __init__(self):
            self.calls = 0

        async def is_relevant(self, utt):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("LLM timeout")
            return True

    class StubPA:
        async def extract(self, **kwargs):
            return []

    class StubHA:
        async def arun(self, utt):
            return _completed_run(f"答: {utt.text}")

    bus = UtteranceBus()
    orch = Orchestrator(store, gate=FlakyGate(), pa=StubPA(), ha=StubHA())
    orch.attach_bus(bus)

    suggestions = []
    orch.set_suggestion_callback(lambda t, m: suggestions.append((t, m)))
    await orch.start()

    await bus.put(Utterance(id="u_1", text="第一句", speaker="client", t_start=0.0, t_end=1.0))
    await bus.put(Utterance(id="u_2", text="第二句", speaker="client", t_start=1.0, t_end=2.0))
    await asyncio.sleep(0.3)
    await orch.shutdown()

    ready = [m for _, m in suggestions if m["kind"] == "ready"]
    assert len(ready) == 1, "第二句应正常处理"
    assert ready[0]["utt_id"] == "u_2"
