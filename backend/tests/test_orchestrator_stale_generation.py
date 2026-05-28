"""Generation 防 stale 单元测试 — analyze_quick 路径的并发安全。

为什么：原 e2e 测试只跑顺序对话，无法验证"旧请求被新 utterance 推进后丢弃"的 race path。
本测试通过 mock Agent.arun 的慢响应，并在调用中途推进 ContextStore.generation，
精确验证 HeavyAgent.analyze_quick 的前置 / 后置 generation 检查。
"""

import asyncio
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from agent.context_store import ContextStore
from agent.heavy_agent import HeavyAgent
from models.utterance import Utterance


def _make_utt(id_: str, text: str = "测试句") -> Utterance:
    return Utterance(
        id=id_,
        text=text,
        speaker="client",
        t_start=0.0,
        t_end=1.0,
        timestamp=datetime.now(),
    )


@pytest.mark.asyncio
async def test_analyze_quick_drops_stale_response_after_generation_bump():
    """analyze_quick 调用中途新 utterance 进入，旧响应必须被丢弃。

    时序：
      t0  append utt1 → generation=1，启动 analyze_quick(generation=1)
      t1  Agent.arun 进入慢响应（sleep 模拟 LLM 延迟）
      t2  append utt2 → generation=2（主线程推进）
      t3  Agent.arun 返回 → analyze_quick 后置检查发现 1≠2 → 返回 None
    """
    ctx = ContextStore()
    ha = HeavyAgent(ctx, model=MagicMock())

    utt1 = _make_utt("u1")
    gen1 = await ctx.append_utterance(utt1)
    assert gen1 == 1

    stale_response = MagicMock()
    stale_response.content = "应被丢弃的旧响应"

    async def slow_arun(_prompt):
        await asyncio.sleep(0.05)
        return stale_response

    fake_agent = MagicMock()
    fake_agent.arun = slow_arun

    with patch("agent.heavy_agent.Agent", return_value=fake_agent):
        task = asyncio.create_task(ha.analyze_quick(utt1, "query_law", gen1))
        # 等 analyze_quick 进入 arun 的 sleep
        await asyncio.sleep(0.01)
        # 主线程推进 generation
        gen2 = await ctx.append_utterance(_make_utt("u2"))
        assert gen2 == 2
        result = await task

    assert result is None, "generation 推进后旧响应必须被丢弃"


@pytest.mark.asyncio
async def test_analyze_quick_rejects_before_calling_agent_when_already_stale():
    """调用 analyze_quick 时 generation 已经过时，应直接返回 None，不应触达 Agent。"""
    ctx = ContextStore()
    ha = HeavyAgent(ctx, model=MagicMock())

    utt1 = _make_utt("u1")
    gen_stale = await ctx.append_utterance(utt1)  # =1
    # 第二句推进 generation → ctx._generation == 2，但 gen_stale 仍是 1
    await ctx.append_utterance(_make_utt("u2"))

    arun_calls = 0

    async def should_not_be_called(_prompt):
        nonlocal arun_calls
        arun_calls += 1
        return MagicMock(content="不该被调用")

    fake_agent = MagicMock()
    fake_agent.arun = should_not_be_called

    with patch("agent.heavy_agent.Agent", return_value=fake_agent):
        result = await ha.analyze_quick(utt1, "query_law", gen_stale)

    assert result is None
    assert arun_calls == 0, "前置 generation 检查必须在调用 Agent 之前生效"


@pytest.mark.asyncio
async def test_analyze_quick_returns_content_when_generation_matches():
    """生命周期内 generation 全程匹配，analyze_quick 应正常返回内容。"""
    ctx = ContextStore()
    ha = HeavyAgent(ctx, model=MagicMock())

    utt = _make_utt("u1")
    gen = await ctx.append_utterance(utt)

    response = MagicMock()
    response.content = "正常响应"

    async def fast_arun(_prompt):
        return response

    fake_agent = MagicMock()
    fake_agent.arun = fast_arun

    with patch("agent.heavy_agent.Agent", return_value=fake_agent):
        result = await ha.analyze_quick(utt, "query_law", gen)

    assert result == "正常响应"
