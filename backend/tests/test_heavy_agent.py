"""Tests for HeavyAgent — 单一 arun + acontinue_run 路径。"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.context_store import ContextStore, ProfileEntry
from agent.heavy_agent import HeavyAgent
from models.utterance import Utterance


@pytest.fixture(autouse=True)
def _mock_env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    from agno.db.in_memory import InMemoryDb  # noqa: PLC0415
    from agent.db import reset_agno_db_for_tests  # noqa: PLC0415
    reset_agno_db_for_tests(replacement=InMemoryDb())


@pytest.fixture
def populated_store():
    store = ContextStore()
    store._utterances = [
        Utterance(id="u_0", text="律师你好", speaker="client", t_start=0.0, t_end=1.0),
        Utterance(id="u_1", text="月薪两万五", speaker="client", t_start=1.0, t_end=2.0),
    ]
    store._profile = [ProfileEntry(key="月薪", value="25000", timestamp=1.0, source_utt_id="u_1")]
    store._generation = 2
    return store


@pytest.mark.asyncio
async def test_arun_returns_run_output_with_status(populated_store):
    """arun 应返回 Agno RunOutput,带 status/is_paused/active_requirements。"""
    ha = HeavyAgent(populated_store, session_id="sess_1", user_id="user_1")

    fake_run = MagicMock()
    fake_run.is_paused = False
    fake_run.content = "N+1=工龄×月薪。"
    fake_run.run_id = "run_abc"

    with patch("agno.agent.Agent.arun", new=AsyncMock(return_value=fake_run)):
        utt = Utterance(id="u_2", text="N+1怎么算", speaker="client", t_start=2.0, t_end=3.0)
        result = await ha.arun(utt)

    assert result.is_paused is False
    assert "N+1" in result.content


@pytest.mark.asyncio
async def test_arun_passes_session_and_user_id_to_agno(populated_store):
    """session_id/user_id 必须传给 Agno Agent,否则 continue_run 时找不到 run。"""
    ha = HeavyAgent(populated_store, session_id="sess_x", user_id="user_x")

    captured = {}

    async def fake_arun(self, prompt, **kwargs):
        captured["session_id"] = self.session_id
        captured["user_id"] = self.user_id
        m = MagicMock()
        m.is_paused = False
        m.content = "ok"
        m.run_id = "r"
        return m

    with patch("agno.agent.Agent.arun", new=fake_arun):
        await ha.arun(Utterance(id="u_2", text="问", speaker="client", t_start=0.0, t_end=1.0))

    assert captured["session_id"] == "sess_x"
    assert captured["user_id"] == "user_x"


@pytest.mark.asyncio
async def test_acontinue_run_uses_continue_not_base(populated_store):
    """confirm 后必须走 Agno acontinue_run,而不是重新 arun(否则重复理解)。"""
    ha = HeavyAgent(populated_store, session_id="sess_1", user_id="user_1")

    fake_resumed = MagicMock()
    fake_resumed.is_paused = False
    fake_resumed.content = "深度分析:根据第87条…"
    fake_resumed.run_id = "run_abc"

    arun_mock = AsyncMock(side_effect=AssertionError("acontinue_run 不应再调 arun"))
    cont_mock = AsyncMock(return_value=fake_resumed)

    with patch("agno.agent.Agent.arun", new=arun_mock), patch(
        "agno.agent.Agent.acontinue_run", new=cont_mock
    ):
        result = await ha.acontinue_run(run_id="run_abc", requirements=[MagicMock()])

    assert "深度分析" in result.content
    cont_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_arun_when_child_pauses_returns_paused_run(populated_store):
    """child 调 gated deep_analysis → run.is_paused=True + active_requirements 非空。"""
    ha = HeavyAgent(populated_store, session_id="sess_1", user_id="user_1")

    req = MagicMock()
    req.tool_execution.tool_args = {"topic": "胜率评估", "rationale": "需要全画像"}
    fake_run = MagicMock()
    fake_run.is_paused = True
    fake_run.run_id = "run_abc"
    fake_run.active_requirements = [req]

    with patch("agno.agent.Agent.arun", new=AsyncMock(return_value=fake_run)):
        result = await ha.arun(Utterance(id="u_2", text="能赢吗", speaker="client", t_start=0.0, t_end=1.0))

    assert result.is_paused
    assert result.active_requirements[0].tool_execution.tool_args["topic"] == "胜率评估"
