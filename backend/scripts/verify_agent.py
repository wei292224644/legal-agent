"""Verify agent works with real Deepseek API."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from agno_agents import build_analyze_fn, build_execute_fn
from agent import IntentResult
from audio_pipeline import TranscriptResult

SAMPLE_DIALOGUE = [
    TranscriptResult(text="我去年三月份入职的，到现在公司一直没跟我签劳动合同", speaker="客户"),
    TranscriptResult(text="您这个情况确实不太合理，能说说具体什么时候入职的吗", speaker="律师"),
    TranscriptResult(text="去年三月十五号，到现在都快一年半了", speaker="客户"),
    TranscriptResult(text="而且上个月老板说我业绩不好，让我自己走人，也不给赔偿", speaker="客户"),
]


async def test_analyze():
    print("=" * 60)
    print("Testing analyze_fn with real Deepseek...")
    print("=" * 60)

    analyze = build_analyze_fn()
    results = await analyze(SAMPLE_DIALOGUE)

    print(f"\nGot {len(results)} results:\n")
    for r in results:
        if isinstance(r, IntentResult):
            print(f"  [INTENT] {r.intent_id}")
            print(f"    question: {r.question}")
            print(f"    context:  {r.context}")
        else:
            print(f"  [ANALYSIS] {r.category}")
            print(f"    title:    {r.title}")
            print(f"    content:  {r.content[:80]}...")
            print(f"    citation: {r.citation}")
            print(f"    level:    {r.level}")
        print()

    return results


async def test_execute(intent: IntentResult):
    print("=" * 60)
    print("Testing execute_fn with real Deepseek...")
    print("=" * 60)

    execute = build_execute_fn()
    results = await execute(intent, SAMPLE_DIALOGUE)

    print(f"\nGot {len(results)} results:\n")
    for r in results:
        print(f"  [{r.category}] {r.title}")
        print(f"    {r.content[:100]}...")
        if r.citation:
            print(f"    citation: {r.citation}")
        if r.level:
            print(f"    level: {r.level}")
        print()

    return results


async def main():
    # Step 1: Analyze
    results = await test_analyze()

    # Step 2: If got an intent, test execute
    intents = [r for r in results if isinstance(r, IntentResult)]
    if intents:
        await test_execute(intents[0])
    else:
        print("No intent found, skipping execute test.")


if __name__ == "__main__":
    asyncio.run(main())
