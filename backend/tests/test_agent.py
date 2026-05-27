import asyncio

import pytest
from agent import AnalysisResult, IntentResult, LegalAgent


def make_agent(analyze_results=None, execute_results=None, on_intent=None, on_analysis=None):
    received_intents = []
    received_analyses = []

    async def default_on_intent(r):
        received_intents.append(r)

    async def default_on_analysis(r):
        received_analyses.append(r)

    async def fake_analyze(_profile, _context):
        return ("", analyze_results or [])

    async def fake_execute(_intent, _context):
        return execute_results or []

    agent = LegalAgent(
        on_intent=on_intent or default_on_intent,
        on_analysis=on_analysis or default_on_analysis,
        analyze_fn=fake_analyze,
        execute_fn=fake_execute,
    )
    return agent, received_intents, received_analyses


# ── Fire-and-forget triggers analysis ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_client_speech_fires_observer():
    result = AnalysisResult(category="statute", title="劳动法", content="...")
    agent, _, received = make_agent(analyze_results=[result])

    await agent.observe("我没有签合同", "客户")
    # let fire-and-forget task complete
    await asyncio.sleep(0.05)

    assert len(received) == 1


# ── Lawyer speech ignored ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_lawyer_speech_does_not_trigger():
    result = AnalysisResult(category="statute", title="X", content="...")
    agent, _, received = make_agent(analyze_results=[result])

    await agent.observe("根据劳动法", "律师")
    await asyncio.sleep(0.05)

    assert received == []


# ── Multiple observes fire independent tasks ────────────────────────────────────

@pytest.mark.asyncio
async def test_multiple_observes_all_complete():
    call_count = 0

    async def counting_analyze(_profile, _context):
        nonlocal call_count
        call_count += 1
        return ("", [])

    agent = LegalAgent(
        on_intent=lambda r: None,
        on_analysis=lambda r: None,
        analyze_fn=counting_analyze,
        execute_fn=lambda i, c: asyncio.sleep(0) or [],
    )

    await agent.observe("第一句", "客户")
    await agent.observe("第二句", "客户")
    await agent.observe("第三句", "客户")

    # wait for all tasks
    await asyncio.sleep(0.1)
    assert call_count == 3


# ── Complex task → intent card ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_complex_fires_intent_not_analysis():
    intent = IntentResult(intent_id="i-1", question="需要审查合同吗？", context="...")
    agent, received_intents, received_analyses = make_agent(analyze_results=[intent])

    await agent.observe("我没有签合同", "客户")
    await asyncio.sleep(0.05)

    assert len(received_intents) == 1
    assert received_intents[0].question == "需要审查合同吗？"
    assert received_analyses == []


# ── confirm_intent triggers executor ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_confirm_intent_runs_executor():
    intent = IntentResult(intent_id="i-1", question="需要审查合同吗？", context="...")
    exec_result = AnalysisResult(category="contract", title="X", content="...")
    agent, _, received = make_agent(analyze_results=[intent], execute_results=[exec_result])

    await agent.observe("我没有签合同", "客户")
    await asyncio.sleep(0.05)

    await agent.confirm_intent("i-1")
    task = agent._executor_tasks.get("i-1")
    if task:
        await task

    assert len(received) >= 1


# ── Multiple executors concurrent ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_two_confirmed_intents_run_concurrently():
    intent_a = IntentResult(intent_id="a", question="查合同？", context="...")
    intent_b = IntentResult(intent_id="b", question="查风险？", context="...")

    async def fake_analyze(_profile, _context):
        return ("", [intent_a, intent_b])

    async def fake_execute(intent, _context):
        return [AnalysisResult(category=intent.intent_id, title="t", content="...")]

    received = []

    async def collect(r):
        received.append(r)

    async def no_op(_r):
        pass

    agent = LegalAgent(
        on_intent=no_op,
        on_analysis=collect,
        analyze_fn=fake_analyze,
        execute_fn=fake_execute,
    )

    await agent.observe("测试", "客户")
    await asyncio.sleep(0.05)

    await agent.confirm_intent("a")
    await agent.confirm_intent("b")
    tasks = [agent._executor_tasks[k] for k in ["a", "b"] if k in agent._executor_tasks]
    await asyncio.gather(*tasks)

    categories = {r.category for r in received}
    assert categories == {"a", "b"}


# ── dismiss_intent cleans up ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dismiss_intent_prevents_execution():
    intent = IntentResult(intent_id="i-1", question="需要查合同吗？", context="...")
    exec_called = []

    async def fake_analyze(_profile, _context):
        return ("", [intent])

    async def fake_execute(i, c):
        exec_called.append(i.intent_id)
        return []

    async def no_op(_r):
        pass

    agent = LegalAgent(
        on_intent=no_op,
        on_analysis=lambda r: None,
        analyze_fn=fake_analyze,
        execute_fn=fake_execute,
    )

    await agent.observe("没有签合同", "客户")
    await asyncio.sleep(0.05)

    agent.dismiss_intent("i-1")
    await agent.confirm_intent("i-1")
    await asyncio.sleep(0.02)

    assert exec_called == []
