"""Tests for child agent tools — deep_analysis (gated) + fetch_more_transcript (read-only)."""

import pytest

from agent.child_tools import make_deep_analysis_tool, make_fetch_more_transcript_tool
from agent.context_store import ContextStore, ProfileEntry
from models.utterance import Utterance


@pytest.fixture
def populated_store():
    store = ContextStore()
    for i in range(20):
        store._utterances.append(
            Utterance(
                id=f"u_{i}",
                text=f"第{i}句",
                speaker="client" if i % 2 else "lawyer",
                t_start=float(i),
                t_end=float(i + 1),
            )
        )
    store._profile.append(ProfileEntry(key="月薪", value="25000", timestamp=1.0, source_utt_id="u_1"))
    return store


def test_deep_analysis_tool_requires_confirmation(populated_store):
    """deep_analysis 必须挂 requires_confirmation=True,否则 HITL 路径不会触发。"""
    tool = make_deep_analysis_tool(populated_store)
    # Agno 的 @tool 装饰后返回 Function;requires_confirmation 标志在函数对象上
    assert tool.requires_confirmation is True, "deep_analysis 必须 gated"


def test_deep_analysis_tool_args_include_preview_fields(populated_store):
    """tool 的入参 schema 必须包含 topic + rationale,作为律师卡片预览。"""
    tool = make_deep_analysis_tool(populated_store)
    params = tool.parameters or {}
    props = params.get("properties", {})
    assert "topic" in props, "topic 用于卡片标题"
    assert "rationale" in props, "rationale 用于卡片副标题"


def test_fetch_more_transcript_returns_text(populated_store):
    tool = make_fetch_more_transcript_tool(populated_store)
    result = tool.entrypoint(start_idx=0, end_idx=4)
    assert "第0句" in result
    assert "第3句" in result
    assert "第4句" not in result, "end_idx exclusive"


def test_fetch_more_transcript_is_read_only(populated_store):
    """fetch_more_transcript 调用前后 utterances/profile 必须无任何写入。"""
    before_utts = list(populated_store._utterances)
    before_profile = list(populated_store._profile)
    tool = make_fetch_more_transcript_tool(populated_store)
    tool.entrypoint(start_idx=0, end_idx=5)
    assert populated_store._utterances == before_utts
    assert populated_store._profile == before_profile


def test_fetch_more_transcript_clamps_range(populated_store):
    """越界索引必须安全 clamp,不能让 LLM 误传负数 / 巨大索引就崩。"""
    tool = make_fetch_more_transcript_tool(populated_store)
    # 越界不抛
    result = tool.entrypoint(start_idx=-5, end_idx=999)
    assert "第0句" in result
    assert "第19句" in result
