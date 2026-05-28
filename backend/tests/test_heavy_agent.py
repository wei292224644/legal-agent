"""Tests for HeavyAgent — Agno-based analysis agent."""
import pytest
from unittest.mock import AsyncMock, patch

from agent.context_store import ContextStore, ProfileEntry
from models.utterance import Utterance
from agent.heavy_agent import HeavyAgent
from datetime import datetime


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
        ProfileEntry(key="月薪", value="25000", timestamp=datetime.now(), source_utt_id="u_1"),
        ProfileEntry(key="工龄", value="2年3个月", timestamp=datetime.now(), source_utt_id="u_1"),
    ]
    store._generation = 2
    return store


@pytest.mark.asyncio
async def test_returns_analysis_text(populated_store):
    """Tracer bullet: HeavyAgent analyzes and returns text."""
    agent = HeavyAgent(populated_store)

    with patch.object(agent._agent, "arun", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = AsyncMock(content="根据劳动法第87条，违法解除应支付2N赔偿金。")

        trigger = Utterance(
            id="u_2",
            text="违法解除赔多少？",
            speaker="client",
            t_start=2.0,
            t_end=3.0,
            timestamp=datetime.now(),
        )
        result = await agent.analyze(trigger, intent="simple", generation=2)

        assert result is not None
        assert "劳动法" in result
        mock_run.assert_called_once()


@pytest.mark.asyncio
async def test_returns_none_when_generation_stale(populated_store):
    """Discard result if generation changed during analysis."""
    agent = HeavyAgent(populated_store)

    trigger = Utterance(
        id="u_2",
        text="违法解除赔多少？",
        speaker="client",
        t_start=2.0,
        t_end=3.0,
        timestamp=datetime.now(),
    )
    result = await agent.analyze(trigger, intent="simple", generation=1)

    assert result is None
