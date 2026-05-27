import asyncio

import pytest
from audio_pipeline import TranscriptResult
from agent import AnalysisResult, IntentResult, LegalAgent


def make_agent(
    analyze_results=None,
    execute_results=None,
    on_intent=None,
    on_analysis=None,
):
    received_intents = []
    received_analyses = []

    async def default_on_intent(r):
        received_intents.append(r)

    async def default_on_analysis(r):
        received_analyses.append(r)

    async def fake_analyze(_context):
        return analyze_results or []

    async def fake_execute(_intent, _context):
        return execute_results or []

    agent = LegalAgent(
        on_intent=on_intent or default_on_intent,
        on_analysis=on_analysis or default_on_analysis,
        analyze_fn=fake_analyze,
        execute_fn=fake_execute,
    )
    return agent, received_intents, received_analyses


# ── Tracer bullet ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_client_speech_triggers_on_analysis():
    result = AnalysisResult(category="statute", title="劳动合同法第82条", content="...")
    agent, _, received = make_agent(analyze_results=[result])

    await agent.observe("我没有签劳动合同", "客户")
    await agent._observer_task

    assert len(received) == 1
    assert received[0].category == "statute"


# ── Lawyer speech ignored ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_lawyer_speech_does_not_trigger_analysis():
    result = AnalysisResult(category="statute", title="X", content="...")
    agent, _, received = make_agent(analyze_results=[result])

    await agent.observe("根据劳动合同法", "律师")
    await asyncio.sleep(0)

    assert received == []


# ── Observer cancel ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_second_observe_cancels_first():
    first_started = asyncio.Event()
    call_num = 0

    async def analyze(_context):
        nonlocal call_num
        call_num += 1
        n = call_num
        if n == 1:
            first_started.set()
            await asyncio.sleep(10)  # slow — will be cancelled
        return [AnalysisResult(category="statute", title=f"result-{n}", content="...")]

    received = []

    async def collect(r):
        received.append(r)

    async def no_op_execute(i, c):
        return []

    agent = LegalAgent(
        on_intent=lambda r: None,
        on_analysis=collect,
        analyze_fn=analyze,
        execute_fn=no_op_execute,
    )

    await agent.observe("第一句", "客户")
    await first_started.wait()            # first observer is sleeping
    await agent.observe("第二句", "客户") # cancels first, starts second
    await agent._observer_task            # wait for second to finish

    assert len(received) == 1
    assert received[0].title == "result-2"


# ── Complex task → intent card ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_complex_need_fires_on_intent_not_on_analysis():
    intent = IntentResult(intent_id="i-1", question="需要审查合同吗？", context="没有签合同")
    agent, received_intents, received_analyses = make_agent(analyze_results=[intent])

    await agent.observe("我没有签合同", "客户")
    await agent._observer_task

    assert len(received_intents) == 1
    assert received_intents[0].question == "需要审查合同吗？"
    assert received_analyses == []


# ── confirm_intent triggers executor ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_confirm_intent_runs_executor_and_fires_on_analysis():
    intent = IntentResult(intent_id="i-1", question="需要审查合同吗？", context="没有签合同")
    exec_result = AnalysisResult(category="contract", title="劳动合同缺失条款", content="...")
    agent, _, received = make_agent(analyze_results=[intent], execute_results=[exec_result])

    await agent.observe("我没有签合同", "客户")
    await agent._observer_task

    await agent.confirm_intent("i-1")
    await agent._executor_tasks["i-1"]

    assert len(received) == 1
    assert received[0].category == "contract"


# ── Multiple executors concurrent ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_two_confirmed_intents_run_concurrently():
    intent_a = IntentResult(intent_id="a", question="查合同？", context="...")
    intent_b = IntentResult(intent_id="b", question="查风险？", context="...")

    async def fake_analyze(_context):
        return [intent_a, intent_b]

    async def fake_execute(intent, _context):
        return [AnalysisResult(category=intent.intent_id, title="t", content="...")]

    received = []

    async def collect(r):
        received.append(r)

    async def no_op_intent(_r):
        pass

    agent = LegalAgent(
        on_intent=no_op_intent,
        on_analysis=collect,
        analyze_fn=fake_analyze,
        execute_fn=fake_execute,
    )

    await agent.observe("测试", "客户")
    await agent._observer_task

    await agent.confirm_intent("a")
    await agent.confirm_intent("b")
    task_a = agent._executor_tasks["a"]
    task_b = agent._executor_tasks["b"]
    await asyncio.gather(task_a, task_b)

    categories = {r.category for r in received}
    assert categories == {"a", "b"}


# ── dismiss_intent cleans up ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dismiss_intent_prevents_execution():
    intent = IntentResult(intent_id="i-1", question="需要查合同吗？", context="...")
    exec_called = []

    async def fake_analyze(_context):
        return [intent]

    async def fake_execute(i, c):
        exec_called.append(i.intent_id)
        return []

    async def no_op_intent(_r):
        pass

    agent = LegalAgent(
        on_intent=no_op_intent,
        on_analysis=lambda r: None,
        analyze_fn=fake_analyze,
        execute_fn=fake_execute,
    )

    await agent.observe("没有签合同", "客户")
    await agent._observer_task

    agent.dismiss_intent("i-1")
    await agent.confirm_intent("i-1")  # intent already gone, no-op
    await asyncio.sleep(0)

    assert exec_called == []
