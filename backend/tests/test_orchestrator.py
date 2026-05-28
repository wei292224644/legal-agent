"""Tests for Orchestrator."""
import asyncio
import pytest
import pytest_asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from agent.context_store import ContextStore
from models.utterance import Utterance
from agent.heavy_agent import HeavyAgent
from agent.intent_router import IntentRouter
from agent.orchestrator import Orchestrator
from agent.profile_agent import ProfileAgent


@pytest.fixture(autouse=True)
def _mock_deepseek_env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")


@pytest_asyncio.fixture
async def store():
    ctx = ContextStore()
    await ctx.start_profile_worker()
    return ctx


@pytest.mark.asyncio
async def test_routes_simple_intent_to_hw(store, mock_llm_client):
    ir_client = mock_llm_client('{"intent": "simple", "rationale": "赔偿问题"}')
    pa_client = mock_llm_client('{"entries": [{"key": "测试", "value": "值"}]}')

    ha = HeavyAgent(store)
    with patch.object(ha._agent, "arun", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = AsyncMock(content="根据法律第X条，应支付赔偿金。")

        orch = Orchestrator(
            store,
            ir=IntentRouter(client=ir_client),
            pa=ProfileAgent(client=pa_client),
            ha=ha,
        )

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
        assert len(hw_results[0][0]) > 10


@pytest.mark.asyncio
async def test_ignore_does_not_trigger_suggestion(store, mock_llm_client):
    ir_client = mock_llm_client('{"intent": "ignore", "rationale": "问候"}')
    pa_client = mock_llm_client('{"entries": []}')

    ha = HeavyAgent(store)
    with patch.object(ha._agent, "arun", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = AsyncMock(content="分析")

        orch = Orchestrator(
            store,
            ir=IntentRouter(client=ir_client),
            pa=ProfileAgent(client=pa_client),
            ha=ha,
        )

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
async def test_pa_extracts_facts_to_profile(store, mock_llm_client):
    ir_client = mock_llm_client('{"intent": "ignore", "rationale": "陈述"}')
    pa_client = mock_llm_client('{"entries": [{"key": "月薪", "value": "两万五"}]}')

    ha = HeavyAgent(store)
    with patch.object(ha._agent, "arun", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = AsyncMock(content="分析")

        orch = Orchestrator(
            store,
            ir=IntentRouter(client=ir_client),
            pa=ProfileAgent(client=pa_client),
            ha=ha,
        )
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
async def test_ten_turn_dialogue_stability_and_completeness(store):
    """10轮短对话回归: 验证架构在连续输入下的稳定性与完成度。"""

    class StubIntentRouter:
        def __init__(self, mapping):
            self._mapping = mapping

        async def classify(self, text: str):
            intent = self._mapping.get(text, "ignore")
            return MagicMock(intent=intent, rationale="stub")

    class StubProfileAgent:
        async def extract(self, text: str, speaker: str, existing_keys: list[str], utt_id=None):
            entries = []
            if "月薪" in text and "月薪" not in existing_keys:
                entries.append(MagicMock(key="月薪", value="25000", source_utt_id=utt_id or ""))
            if "工龄" in text and "工龄" not in existing_keys:
                entries.append(MagicMock(key="工龄", value="2年3个月", source_utt_id=utt_id or ""))
            if "解除通知" in text and "解除通知时间" not in existing_keys:
                entries.append(MagicMock(key="解除通知时间", value="2026-05-01", source_utt_id=utt_id or ""))
            return entries

    class StubHeavyAgent:
        async def analyze(self, utt: Utterance, intent: str, generation: int):
            return f"[{intent}] 建议: {utt.text[:20]} (g={generation})"

    turns = [
        ("u_1", "律师你好", "client", "ignore"),
        ("u_2", "我被公司违法解除了", "client", "complex"),
        ("u_3", "先确认解除通知时间", "lawyer", "ignore"),
        ("u_4", "解除通知是5月1号口头说的", "client", "simple"),
        ("u_5", "月薪两万五，税前", "client", "simple"),
        ("u_6", "工龄2年3个月", "client", "simple"),
        ("u_7", "能拿多少赔偿", "client", "simple"),
        ("u_8", "还要不要继续上班", "client", "complex"),
        ("u_9", "先准备证据清单", "lawyer", "ignore"),
        ("u_10", "好的我会整理合同和工资流水", "client", "ignore"),
    ]
    intent_mapping = {text: intent for _, text, _, intent in turns}

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
            Utterance(
                id=utt_id,
                text=text,
                speaker=speaker,
                t_start=0.0,
                t_end=1.0,
                timestamp=datetime.now(),
            )
        )
        generations.append(generation)

    await asyncio.sleep(0.1)

    # 稳定性: 10轮全部处理且 generation 严格递增
    assert generations == list(range(1, 11))

    # 完成度: simple/complex 均触发建议, ignore 不触发
    expected_trigger_count = sum(1 for _, _, _, intent in turns if intent in ("simple", "complex"))
    assert len(suggestions) == expected_trigger_count
    assert all(isinstance(text, str) and text for text, _ in suggestions)
    assert all("intent" in meta and "utt_id" in meta for _, meta in suggestions)

    # 完成度: profile 能从对话中累计关键事实
    profile_keys = set(store.get_profile_keys())
    assert {"月薪", "工龄", "解除通知时间"}.issubset(profile_keys)
