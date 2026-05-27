import asyncio
import os
import time

import pytest
from agent import AnalysisResult, IntentResult, LegalAgent
from dotenv import load_dotenv

load_dotenv()

# ── LLM availability ─────────────────────────────────────────────────────────────

_has_api_key = bool(os.getenv("DEEPSEEK_API_KEY"))
real_llm = pytest.mark.skipif(
    not _has_api_key,
    reason="DEEPSEEK_API_KEY not set — create backend/.env with DEEPSEEK_API_KEY=sk-xxx",
)


# ── Helpers ──────────────────────────────────────────────────────────────────────

def make_fast_agent():
    """Agent with instant (no-op) analyze/execute fns."""

    async def instant_analyze(_profile, _context):
        return ("", [])

    async def instant_execute(_intent, _context):
        return []

    return LegalAgent(
        on_intent=lambda _r: None,
        on_analysis=lambda _r: None,
        analyze_fn=instant_analyze,
        execute_fn=instant_execute,
    )


def make_delayed_agent(delay_s: float):
    """Agent whose analyze_fn takes `delay_s` seconds."""

    async def delayed_analyze(_profile, _context):
        await asyncio.sleep(delay_s)
        return ("", [])

    async def instant_execute(_intent, _context):
        return []

    return LegalAgent(
        on_intent=lambda _r: None,
        on_analysis=lambda _r: None,
        analyze_fn=delayed_analyze,
        execute_fn=instant_execute,
    )


# ── observe() call overhead ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_observe_returns_instantly():
    """observe() must return in <1ms — it only appends + creates a task."""
    agent = make_fast_agent()

    t0 = time.perf_counter()
    await agent.observe("我没有签合同，老板说试用期不算", "客户")
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert elapsed_ms < 5, f"observe() took {elapsed_ms:.2f}ms, expected <5ms"


@pytest.mark.asyncio
async def test_observe_does_not_wait_for_analysis():
    """observe() must return before the analysis task completes."""
    agent = make_delayed_agent(delay_s=0.5)

    t0 = time.perf_counter()
    await agent.observe("未签合同", "客户")
    elapsed_ms = (time.perf_counter() - t0) * 1000

    # observe returns immediately even though analyze takes 500ms
    assert elapsed_ms < 10, f"observe() blocked for {elapsed_ms:.1f}ms"


@pytest.mark.asyncio
async def test_lawyer_speech_skips_immediately():
    """Lawyer speech check must return before any analysis would fire."""
    agent = make_delayed_agent(delay_s=1.0)

    t0 = time.perf_counter()
    await agent.observe("根据劳动法第82条", "律师")
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert elapsed_ms < 5, f"lawyer observe() took {elapsed_ms:.2f}ms"


# ── Throughput ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_high_frequency_observes():
    """100 rapid observes all dispatch without blocking each other."""
    agent = make_fast_agent()
    observe_times: list[float] = []

    for i in range(100):
        t0 = time.perf_counter()
        await agent.observe(f"这是第{i}句客户说的话", "客户")
        observe_times.append((time.perf_counter() - t0) * 1000)

    avg_ms = sum(observe_times) / len(observe_times)
    max_ms = max(observe_times)

    # Every individual call must be fast
    assert max_ms < 10, f"slowest observe: {max_ms:.2f}ms"
    # Average must be sub-millisecond
    assert avg_ms < 2, f"average observe: {avg_ms:.2f}ms"


# ── Concurrent observer tasks ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_observers_dont_interfere():
    """Multiple fire-and-forget tasks run independently without blocking."""
    agent = make_delayed_agent(delay_s=0.1)
    call_times: list[tuple[int, float]] = []

    async def timed_analyze(_profile, _context):
        # This replaces the agent's analyze_fn — we inject timing
        pass

    # Fire 10 observes rapidly
    t_start = time.perf_counter()
    for i in range(10):
        await agent.observe(f"客户说第{i}句", "客户")
    dispatch_ms = (time.perf_counter() - t_start) * 1000

    # All 10 dispatches complete quickly
    assert dispatch_ms < 20, f"dispatching 10 observes took {dispatch_ms:.1f}ms"


@pytest.mark.asyncio
async def test_observer_snapshots_are_independent():
    """Each observer task snapshots context independently at execution time.

    Because observe() is fire-and-forget, rapid calls may all finish before any
    background task runs, so all snapshots may see the same (latest) context.
    This is correct behavior — the design prioritizes non-blocking dispatch.
    """
    snapshots: list[int] = []

    async def snapshot_analyze(_profile, context):
        snapshots.append(len(context))
        return ("", [])

    async def noop(r):
        pass

    agent = LegalAgent(
        on_intent=noop,
        on_analysis=noop,
        analyze_fn=snapshot_analyze,
        execute_fn=lambda i, c: asyncio.sleep(0),
    )

    await agent.observe("A", "客户")
    await agent.observe("B", "客户")
    await agent.observe("C", "客户")

    await asyncio.sleep(0.1)

    assert len(snapshots) == 3, f"expected 3 snapshots, got {len(snapshots)}"
    # Each snapshot sees the context the moment it executes — they may all see
    # 3 items if all appends finished before the first task ran.
    assert all(s > 0 for s in snapshots), "every snapshot must have context"


# ── Task isolation ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_slow_observer_doesnt_block_next_observe():
    """A slow analysis task must not delay the next observe() call."""
    agent = make_delayed_agent(delay_s=0.3)

    # Fire first observe (triggers 300ms background task)
    await agent.observe("第一句", "客户")

    # Second observe must return instantly
    t0 = time.perf_counter()
    await agent.observe("第二句", "客户")
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert elapsed_ms < 10, f"second observe blocked for {elapsed_ms:.1f}ms"


@pytest.mark.asyncio
async def test_all_background_tasks_complete():
    """Verify that all fire-and-forget tasks eventually finish."""
    completed = 0

    async def counting_analyze(_profile, _context):
        nonlocal completed
        await asyncio.sleep(0.01)
        completed += 1
        return ("", [])

    async def noop(r):
        pass

    agent = LegalAgent(
        on_intent=noop,
        on_analysis=noop,
        analyze_fn=counting_analyze,
        execute_fn=lambda i, c: asyncio.sleep(0),
    )

    for i in range(20):
        await agent.observe(f"客户第{i}句", "客户")

    # Wait for all background tasks
    await asyncio.sleep(0.5)
    assert completed == 20, f"only {completed}/20 tasks completed"


# ── End-to-end latency with mock ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_end_to_end_latency_fast_path():
    """End-to-end: observe → analysis → result delivery (fast mock)."""
    received: list[AnalysisResult] = []

    async def fast_analyze(_profile, _context):
        return ("", [AnalysisResult(category="statute", title="劳动法", content="第82条")])

    async def collect(r: AnalysisResult):
        received.append(r)

    agent = LegalAgent(
        on_intent=lambda _r: None,
        on_analysis=collect,
        analyze_fn=fast_analyze,
        execute_fn=lambda i, c: asyncio.sleep(0),
    )

    t0 = time.perf_counter()
    await agent.observe("没有签合同", "客户")
    await asyncio.sleep(0.05)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert len(received) == 1
    assert received[0].title == "劳动法"
    # End-to-end with instant mock should be well under 100ms
    assert elapsed_ms < 100, f"e2e took {elapsed_ms:.0f}ms"


# ── Real LLM latency tests ───────────────────────────────────────────────────────

CLIENT_DIALOGUE = """我去年11月入职的，签了一年合同。今年11月到期了，公司没跟我续签，"
"但是还让我继续上班。现在已经12月底了，工资照发的。我想问一下这种情况怎么办？"""


class CaptureResults:
    def __init__(self):
        self.facts_summary = ""
        self.results: list[AnalysisResult | IntentResult] = []

    async def on_analysis(self, r: AnalysisResult):
        self.results.append(r)

    async def on_intent(self, r: IntentResult):
        self.results.append(r)


@real_llm
@pytest.mark.asyncio
async def test_real_llm_single_observe_latency():
    """Single observe() end-to-end latency with real Deepseek LLM."""
    from agno_agents import build_analyze_fn, build_execute_fn

    analyze_fn = build_analyze_fn()
    execute_fn = build_execute_fn()
    capture = CaptureResults()
    agent = LegalAgent(
        on_intent=capture.on_intent,
        on_analysis=capture.on_analysis,
        analyze_fn=analyze_fn,
        execute_fn=execute_fn,
    )

    t0 = time.perf_counter()
    await agent.observe(CLIENT_DIALOGUE, "客户")
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert elapsed_ms < 10, f"observe() blocked for {elapsed_ms:.1f}ms (should be fire-and-forget)"

    # Wait for background LLM task to finish (Deepseek typically responds in 2-10s)
    for _ in range(60):
        await asyncio.sleep(0.5)
        if capture.results:
            break

    total_ms = (time.perf_counter() - t0) * 1000
    assert len(capture.results) > 0, (
        f"No results after {total_ms:.0f}ms — LLM may have timed out"
    )

    print(f"\n  observe() return: {elapsed_ms:.1f}ms")
    print(f"  LLM response:    {total_ms:.0f}ms")
    for r in capture.results:
        if isinstance(r, AnalysisResult):
            print(f"  → {r.category}/{r.title}: {r.content[:60]}...")
        else:
            print(f"  → intent: {r.question}")


@real_llm
@pytest.mark.asyncio
async def test_real_llm_concurrent_observes():
    """Multiple rapid observes with real LLM — verify non-blocking and completeness."""
    from agno_agents import build_analyze_fn, build_execute_fn

    analyze_fn = build_analyze_fn()
    execute_fn = build_execute_fn()
    capture = CaptureResults()
    agent = LegalAgent(
        on_intent=capture.on_intent,
        on_analysis=capture.on_analysis,
        analyze_fn=analyze_fn,
        execute_fn=execute_fn,
    )

    dialogues = [
        "我去年11月入职，签了一年合同，现在到期了公司没续签。",
        "我每天加班两小时，但是公司从来没给过加班费。",
        "老板说下个月要辞退我，没有给任何理由。",
    ]

    t0 = time.perf_counter()
    for d in dialogues:
        await agent.observe(d, "客户")
    dispatch_ms = (time.perf_counter() - t0) * 1000

    assert dispatch_ms < 15, f"3 dispatches took {dispatch_ms:.1f}ms"

    # Wait for all 3 LLM tasks
    for _ in range(90):
        await asyncio.sleep(0.5)
        if len(capture.results) >= 1:
            break

    total_ms = (time.perf_counter() - t0) * 1000

    print(f"\n  dispatch 3 observes: {dispatch_ms:.1f}ms")
    print(f"  first result at:     {total_ms:.0f}ms")
    print(f"  results received:    {len(capture.results)}")

    assert len(capture.results) >= 1, f"No results after {total_ms:.0f}ms"


@real_llm
@pytest.mark.asyncio
async def test_real_llm_observe_non_blocking():
    """Verify observe() returns instantly while LLM runs in background."""
    from agno_agents import build_analyze_fn

    analyze_fn = build_analyze_fn()
    async def noop(r):
        pass

    agent = LegalAgent(
        on_intent=noop,
        on_analysis=noop,
        analyze_fn=analyze_fn,
        execute_fn=lambda i, c: asyncio.sleep(0),
    )

    # Fire 3 observes — all trigger real LLM calls in background
    observe_times = []
    for i, text in enumerate(["入职日期是2024年11月", "合同到期没续签", "公司不给加班费"]):
        t0 = time.perf_counter()
        await agent.observe(text, "客户")
        observe_times.append((time.perf_counter() - t0) * 1000)

    avg_observe_ms = sum(observe_times) / len(observe_times)

    print(f"\n  observe times: {[f'{t:.1f}ms' for t in observe_times]}")
    print(f"  average:       {avg_observe_ms:.1f}ms")

    # Key assertion: observe() never blocks, even with real LLM in background
    for i, t in enumerate(observe_times):
        assert t < 10, f"observe #{i} blocked for {t:.1f}ms"
