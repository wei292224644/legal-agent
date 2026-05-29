"""Tests for HeavyAgent — Agno-based analysis agent."""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from agent.context_store import ContextStore, ProfileEntry
from agent.heavy_agent import HeavyAgent
from models.utterance import Utterance


@pytest.fixture(autouse=True)
def _mock_env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")


@pytest.fixture
def store():
    return ContextStore()


@pytest.fixture
def populated_store(store):
    store._utterances = [
        Utterance(id="u_0", text="律师你好", speaker="client", t_start=0.0, t_end=1.0, timestamp=datetime.now()),
        Utterance(id="u_1", text="月薪两万五", speaker="client", t_start=1.0, t_end=2.0, timestamp=datetime.now()),
    ]
    store._profile = [
        ProfileEntry(key="月薪", value="25000", timestamp=1.0, source_utt_id="u_1"),
        ProfileEntry(key="工龄", value="2年3个月", timestamp=1.0, source_utt_id="u_1"),
    ]
    store._generation = 2
    return store


@pytest.mark.asyncio
async def test_analyze_returns_analysis_text(populated_store):
    """complex 确认后 analyze 返回结果，不受 generation 影响。"""
    agent = HeavyAgent(populated_store)

    with patch("agno.agent.Agent.arun", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = AsyncMock(content="根据劳动法第87条，违法解除应支付2N赔偿金。")

        trigger = Utterance(
            id="u_2",
            text="违法解除赔多少？",
            speaker="client",
            t_start=2.0,
            t_end=3.0,
            timestamp=datetime.now(),
        )
        # generation=1（stale），但 analyze 不检查 generation
        result = await agent.analyze(trigger, intent_type="query_law", generation=1)

        assert result is not None
        assert "劳动法" in result
        mock_run.assert_called_once()


@pytest.mark.asyncio
async def test_analyze_quick_skips_when_stale(populated_store):
    """simple 自动触发时如果 generation 过期则跳过。"""
    agent = HeavyAgent(populated_store)

    trigger = Utterance(
        id="u_2",
        text="违法解除赔多少？",
        speaker="client",
        t_start=2.0,
        t_end=3.0,
        timestamp=datetime.now(),
    )
    # generation=1，ctx 是 2 → stale，应跳过
    result = await agent.analyze_quick(trigger, intent_type="query_law", generation=1)

    assert result is None


@pytest.mark.asyncio
async def test_analyze_quick_returns_short_response(populated_store):
    """simple 触发快速分析。"""
    agent = HeavyAgent(populated_store)

    with patch("agno.agent.Agent.arun", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = AsyncMock(content="N+1补偿：工作每满一年支付一个月工资。")

        trigger = Utterance(
            id="u_2",
            text="N+1怎么算",
            speaker="client",
            t_start=2.0,
            t_end=3.0,
            timestamp=datetime.now(),
        )
        result = await agent.analyze_quick(trigger, intent_type="compute_compensation", generation=2)

        assert result is not None
        assert "N+1" in result
        mock_run.assert_called_once()


def test_heavy_agent_uses_window(populated_store):
    """HeavyAgent 的 get_user_context tool 应调用 get_recent_window(10) 而非切片。"""
    from unittest.mock import patch

    with patch.object(populated_store, "get_recent_window") as mock_window:
        mock_window.return_value = populated_store.get_full_history()
        agent = HeavyAgent(populated_store)
        tool = agent._make_get_context_tool()
        # Agno 的 @tool 返回 Function 对象，原始函数在 .entrypoint
        result = tool.entrypoint()
        mock_window.assert_called_once_with(10)
        assert "律师你好" in result
