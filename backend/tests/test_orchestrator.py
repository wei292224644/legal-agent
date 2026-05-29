"""Tests for Orchestrator."""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from agent.context_store import ContextStore
from agent.heavy_agent import HeavyAgent
from agent.intent_router import IntentResult
from agent.orchestrator import Orchestrator
from agent.profile_agent import ProfileAgent
from models.utterance import Utterance


@pytest.fixture(autouse=True)
def _mock_deepseek_env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")


@pytest_asyncio.fixture
async def store():
    ctx = ContextStore()
    await ctx.start_profile_worker()
    return ctx


@pytest.mark.asyncio
async def test_routes_simple_intent_to_quick(store, mock_ir_client):
    """simple → analyze_quick，直接推送 ready 建议。"""
    ir_stub = mock_ir_client(severity="simple", intent_type="query_law")
    pa_client = MagicMock()
    pa_client.chat.completions.create = AsyncMock(
        return_value=MagicMock(choices=[MagicMock(message=MagicMock(content='{"entries": []}'))])
    )

    ha = HeavyAgent(store)
    with patch("agno.agent.Agent.arun", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = AsyncMock(content="根据劳动法第87条，应支付2N赔偿金。")

        orch = Orchestrator(store, ir=ir_stub, pa=ProfileAgent(client=pa_client), ha=ha)

        hw_results = []

        async def on_suggestion(text, meta):
            hw_results.append((text, meta))

        orch.set_suggestion_callback(on_suggestion)

        utt = Utterance(
            id="u_1",
            text="违法解除赔多少？",
            speaker="client",
            t_start=0.0,
            t_end=1.0,
            timestamp=datetime.now(),
        )
        await orch.handle_utterance(utt)
        await asyncio.sleep(0.1)

        assert len(hw_results) == 1
        text, meta = hw_results[0]
        assert "劳动法" in text
        assert meta["kind"] == "ready"
        assert meta["severity"] == "simple"


@pytest.mark.asyncio
async def test_simple_record_only_skips_quick_analysis(store, mock_ir_client):
    """simple + record_only 应跳过 analyze_quick：record_only 字面语义就是打点不响应。"""
    ir_stub = mock_ir_client(severity="simple", intent_type="record_only")
    pa_client = MagicMock()
    pa_client.chat.completions.create = AsyncMock(
        return_value=MagicMock(choices=[MagicMock(message=MagicMock(content='{"entries": []}'))])
    )

    ha = HeavyAgent(store)
    with patch("agno.agent.Agent.arun", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = AsyncMock(content="不该被调用")

        orch = Orchestrator(store, ir=ir_stub, pa=ProfileAgent(client=pa_client), ha=ha)

        suggestions = []

        async def on_suggestion(text, meta):
            suggestions.append((text, meta))

        orch.set_suggestion_callback(on_suggestion)

        utt = Utterance(
            id="u_1",
            text="两年三个月。",
            speaker="client",
            t_start=0.0,
            t_end=1.0,
            timestamp=datetime.now(),
        )
        await orch.handle_utterance(utt)
        await asyncio.sleep(0.1)

        assert len(suggestions) == 0, "record_only 不应触发任何建议"
        mock_run.assert_not_called(), "record_only 不应触达 HeavyAgent"


@pytest.mark.asyncio
async def test_complex_emits_pending_not_ready(store, mock_ir_client):
    """complex → 发出 pending 建议（text=None），不触发 analyze。"""
    ir_stub = mock_ir_client(severity="complex", intent_type="query_law")
    pa_client = MagicMock()
    pa_client.chat.completions.create = AsyncMock(
        return_value=MagicMock(choices=[MagicMock(message=MagicMock(content='{"entries": []}'))])
    )

    ha = HeavyAgent(store)
    with patch("agno.agent.Agent.arun", new_callable=AsyncMock) as mock_full:
        mock_full.return_value = AsyncMock(content="分析结果")

        orch = Orchestrator(store, ir=ir_stub, pa=ProfileAgent(client=pa_client), ha=ha)

        suggestions = []

        async def on_suggestion(text, meta):
            suggestions.append((text, meta))

        orch.set_suggestion_callback(on_suggestion)

        utt = Utterance(
            id="u_1",
            text="能赢吗",
            speaker="client",
            t_start=0.0,
            t_end=1.0,
            timestamp=datetime.now(),
        )
        await orch.handle_utterance(utt)
        await asyncio.sleep(0.1)

        assert len(suggestions) == 1
        text, meta = suggestions[0]
        assert text is None
        assert meta["kind"] == "pending"
        assert "request_id" in meta
        mock_full.assert_not_called()


@pytest.mark.asyncio
async def test_confirm_analysis_triggers_heavy_agent(store, mock_ir_client):
    """律师确认后调用 confirm_analysis → 触发 analyze。"""
    ir_stub = mock_ir_client(severity="complex", intent_type="query_law")
    pa_client = MagicMock()
    pa_client.chat.completions.create = AsyncMock(
        return_value=MagicMock(choices=[MagicMock(message=MagicMock(content='{"entries": []}'))])
    )

    ha = HeavyAgent(store)
    with patch("agno.agent.Agent.arun", new_callable=AsyncMock) as mock_full:
        mock_full.return_value = AsyncMock(content="根据案情分析，建议收集证据后申请劳动仲裁。")

        orch = Orchestrator(store, ir=ir_stub, pa=ProfileAgent(client=pa_client), ha=ha)

        suggestions = []

        async def on_suggestion(text, meta):
            suggestions.append((text, meta))

        orch.set_suggestion_callback(on_suggestion)

        utt = Utterance(
            id="u_1",
            text="能赢吗",
            speaker="client",
            t_start=0.0,
            t_end=1.0,
            timestamp=datetime.now(),
        )
        await orch.handle_utterance(utt)
        await asyncio.sleep(0.1)

        request_id = suggestions[0][1]["request_id"]
        ok = await orch.confirm_analysis(request_id)
        await asyncio.sleep(0.1)
        assert ok

        mock_full.assert_called_once()
        assert len(suggestions) == 2
        assert suggestions[1][1]["kind"] == "ready"
        assert "劳动仲裁" in suggestions[1][0]


@pytest.mark.asyncio
async def test_dismiss_pending_removes_request(store, mock_ir_client):
    """律师关闭建议卡片后 pending 被清除。"""
    ir_stub = mock_ir_client(severity="complex", intent_type="query_law")
    pa_client = MagicMock()
    pa_client.chat.completions.create = AsyncMock(
        return_value=MagicMock(choices=[MagicMock(message=MagicMock(content='{"entries": []}'))])
    )

    ha = HeavyAgent(store)
    orch = Orchestrator(store, ir=ir_stub, pa=ProfileAgent(client=pa_client), ha=ha)

    suggestions = []

    async def on_suggestion(text, meta):
        suggestions.append((text, meta))

    orch.set_suggestion_callback(on_suggestion)

    utt = Utterance(
        id="u_1",
        text="能赢吗",
        speaker="client",
        t_start=0.0,
        t_end=1.0,
        timestamp=datetime.now(),
    )
    await orch.handle_utterance(utt)
    await asyncio.sleep(0.1)

    request_id = suggestions[0][1]["request_id"]
    assert request_id in orch._pending

    orch.dismiss_pending(request_id)
    assert request_id not in orch._pending


@pytest.mark.asyncio
async def test_ignore_does_not_trigger_suggestion(store, mock_ir_client):
    ir_stub = mock_ir_client(severity="ignore", intent_type="none")
    pa_client = MagicMock()
    pa_client.chat.completions.create = AsyncMock(
        return_value=MagicMock(choices=[MagicMock(message=MagicMock(content='{"entries": []}'))])
    )

    ha = HeavyAgent(store)
    orch = Orchestrator(store, ir=ir_stub, pa=ProfileAgent(client=pa_client), ha=ha)

    suggestions = []

    async def on_suggestion(text, meta):
        suggestions.append(text)

    orch.set_suggestion_callback(on_suggestion)

    utt = Utterance(
        id="u_1",
        text="律师你好",
        speaker="client",
        t_start=0.0,
        t_end=1.0,
        timestamp=datetime.now(),
    )
    await orch.handle_utterance(utt)
    await asyncio.sleep(0.1)

    assert len(suggestions) == 0


@pytest.mark.asyncio
async def test_pa_extracts_facts_to_profile(store, mock_ir_client):
    ir_stub = mock_ir_client(severity="ignore", intent_type="none")
    pa_client = MagicMock()
    pa_client.chat.completions.create = AsyncMock(
        return_value=MagicMock(
            choices=[MagicMock(message=MagicMock(content='{"entries": [{"key": "月薪", "value": "两万五"}]}'))]
        )
    )

    ha = HeavyAgent(store)
    orch = Orchestrator(store, ir=ir_stub, pa=ProfileAgent(client=pa_client), ha=ha)
    orch.set_suggestion_callback(lambda text, meta: None)

    utt = Utterance(
        id="u_1",
        text="月薪两万五，税前",
        speaker="client",
        t_start=0.0,
        t_end=1.0,
        timestamp=datetime.now(),
    )
    await orch.handle_utterance(utt)
    await asyncio.sleep(0.1)

    profile = store.get_profile()
    assert len(profile) >= 1
    keys = [e.key for e in profile]
    assert "月薪" in keys


@pytest.mark.asyncio
async def test_profile_timestamp_from_utt(store, mock_ir_client):
    """PA entries 的 timestamp 应被 Orchestrator 覆盖为 utt.t_start。"""
    ir_stub = mock_ir_client(severity="ignore", intent_type="none")
    pa_client = MagicMock()
    pa_client.chat.completions.create = AsyncMock(
        return_value=MagicMock(
            choices=[MagicMock(message=MagicMock(content='{"entries": [{"key": "月薪", "value": "两万五"}]}'))]
        )
    )

    ha = HeavyAgent(store)
    orch = Orchestrator(store, ir=ir_stub, pa=ProfileAgent(client=pa_client), ha=ha)
    orch.set_suggestion_callback(lambda text, meta: None)

    utt = Utterance(
        id="u_1",
        text="月薪两万五，税前",
        speaker="client",
        t_start=12.5,
        t_end=13.0,
        timestamp=datetime.now(),
    )
    await orch.handle_utterance(utt)
    await asyncio.sleep(0.1)

    profile = store.get_profile()
    assert len(profile) == 1
    assert profile[0].timestamp == 12.5


@pytest.mark.asyncio
async def test_ten_turn_dialogue_stability_and_completeness(store):
    """10轮短对话回归: simple 直推, complex 挂起, ignore 不触发。"""

    class StubIntentRouter:
        def __init__(self, mapping):
            self._mapping = mapping

        async def classify(self, text: str, speaker: str | None = None):
            entry = self._mapping.get(text, ("ignore", "none"))
            severity, intent_type = entry
            return IntentResult(severity=severity, intent_type=intent_type, rationale="stub")

    class StubProfileAgent:
        async def extract(self, text: str, speaker: str | None, history: list, existing_profile: dict[str, str], utt_id: str = ""):
            entries = []
            if "月薪" in text and "月薪" not in existing_profile:
                entries.append(MagicMock(key="月薪", value="25000", source_utt_id=utt_id or ""))
            if "工龄" in text and "工龄" not in existing_profile:
                entries.append(MagicMock(key="工龄", value="2年3个月", source_utt_id=utt_id or ""))
            if "解除通知" in text and "解除通知时间" not in existing_profile:
                entries.append(MagicMock(key="解除通知时间", value="2026-05-01", source_utt_id=utt_id or ""))
            return entries

    class StubHeavyAgent:
        async def analyze(self, utt: Utterance, intent_type: str, generation: int):
            return f"[{intent_type}] 建议: {utt.text[:20]} (g={generation})"

        async def analyze_quick(self, utt: Utterance, intent_type: str, generation: int):
            return f"[quick:{intent_type}] {utt.text[:20]} (g={generation})"

    turns = [
        ("u_1", "律师你好", "client", ("ignore", "none")),
        ("u_2", "我被公司违法解除了", "client", ("complex", "query_law")),
        ("u_3", "先确认解除通知时间", "lawyer", ("ignore", "none")),
        ("u_4", "解除通知是5月1号口头说的", "client", ("simple", "record_only")),
        ("u_5", "月薪两万五，税前", "client", ("simple", "record_only")),
        ("u_6", "工龄2年3个月", "client", ("simple", "record_only")),
        ("u_7", "能拿多少赔偿", "client", ("simple", "compute_compensation")),
        ("u_8", "还要不要继续上班", "client", ("complex", "query_law")),
        ("u_9", "先准备证据清单", "lawyer", ("ignore", "none")),
        ("u_10", "好的我会整理合同和工资流水", "client", ("ignore", "none")),
    ]
    intent_mapping = {text: entry for _, text, _, entry in turns}

    orch = Orchestrator(
        store,
        ir=StubIntentRouter(intent_mapping),
        pa=StubProfileAgent(),
        ha=StubHeavyAgent(),
    )

    suggestions = []

    async def on_suggestion(text, meta):
        suggestions.append((text, meta))

    orch.set_suggestion_callback(on_suggestion)

    generations = []
    for utt_id, text, speaker, _ in turns:
        generation = await orch.handle_utterance(
            Utterance(id=utt_id, text=text, speaker=speaker, t_start=0.0, t_end=1.0, timestamp=datetime.now())
        )
        generations.append(generation)

    await asyncio.sleep(0.1)

    assert generations == list(range(1, 11))

    ready_suggestions = [(t, m) for t, m in suggestions if m["kind"] == "ready"]
    pending_suggestions = [(t, m) for t, m in suggestions if m["kind"] == "pending"]

    # simple/record_only 走"打点不响应"分支，不应进入 quick 路径
    simple_actionable_count = sum(1 for _, _, _, (s, it) in turns if s == "simple" and it != "record_only")
    complex_count = sum(1 for _, _, _, (s, _) in turns if s == "complex")

    assert len(ready_suggestions) == simple_actionable_count
    assert len(pending_suggestions) == complex_count
    assert all(t is not None for t, _ in ready_suggestions)
    assert all(t is None for t, _ in pending_suggestions)
    assert all("request_id" in m for _, m in pending_suggestions)

    for _, meta in pending_suggestions:
        await orch.confirm_analysis(meta["request_id"])
    await asyncio.sleep(0.1)
    total_ready = sum(1 for t, m in suggestions if m["kind"] == "ready")
    assert total_ready == simple_actionable_count + complex_count

    profile_keys = set(store.get_profile_keys())
    assert {"月薪", "工龄", "解除通知时间"}.issubset(profile_keys)
