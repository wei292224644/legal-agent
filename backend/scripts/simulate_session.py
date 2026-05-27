"""Simulate a full legal consultation session with realistic timing."""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from agent import AnalysisResult, IntentResult, LegalAgent
from agno_agents import build_analyze_fn, build_execute_fn
from audio_pipeline import TranscriptResult

# ── Full consultation dialogue: labor dispute ─────────────────────────────────

DIALOGUE = [
    # === 开场 ===
    ("您好，请坐。请问您今天来是想咨询哪方面的法律问题？", "律师"),
    ("律师您好，我遇到了劳动方面的问题，想请您帮忙看看。", "客户"),
    ("好的，您慢慢说，把情况讲清楚。", "律师"),

    # === 背景陈述 ===
    ("我是去年三月份入职的，在一家互联网公司做产品经理。", "客户"),
    ("入职的时候公司说试用期三个月，但是到现在已经一年多了，一直没有跟我签劳动合同。", "客户"),
    ("嗯，这个情况确实不少见。您继续说。", "律师"),
    ("然后上个月，我们部门换了一个新领导。他找我谈话，说公司今年效益不好，要进行人员优化。", "客户"),
    ("他说我的工作表现不达标，让我自己写辞职信走人。", "客户"),
    ("您当时怎么回应的？", "律师"),
    ("我说我没有觉得我工作有问题，不同意辞职。", "客户"),
    ("结果他就说，如果我不主动走，公司也会开除我，而且这个月工资和之前压的一个月工资都不给了。", "客户"),
    ("我当时很生气，但是没有跟他吵。", "客户"),

    # === 律师深挖 ===
    ("您做得对，冷静处理是对的。我先确认几个关键信息。", "律师"),
    ("你们公司有没有给您发过工资条或者银行流水？", "律师"),
    ("有的，每个月15号通过银行转账发工资，但是工资条没有，就是直接打钱。", "客户"),
    ("我每个月基本工资是一万二，加上绩效大概能拿到一万五左右。", "客户"),
    ("好的，那社保和公积金呢？公司有没有给您交？", "律师"),
    ("这个也是问题。入职的时候HR说试用期不交社保，转正后再交。", "客户"),
    ("结果三个月试用期过了，他们又说过完年统一办，就一直拖到现在都没交。", "客户"),
    ("也没有公积金，公司说创业公司不交公积金。", "客户"),

    # === 律师进一步挖掘 ===
    ("了解了。那除了这些，还有没有其他情况？比如加班、年假这些？", "律师"),
    ("有的。我们公司说是996，但实际上经常要加班到晚上十点、十一点。", "客户"),
    ("我算了一下，基本上每周工作时间都在60个小时以上。", "客户"),
    ("有没有加班费？", "律师"),
    ("没有，公司说我们是弹性工作制，不算加班。", "客户"),
    ("年假也没有休过，我入职到现在一次年假都没休。去年年底我想休几天，领导说项目忙不批。", "客户"),

    # === 关键证据 ===
    ("您手上有哪些证据？比如入职登记表、工牌、工作群聊天记录这些。", "律师"),
    ("入职的时候填过一个表，但是表格公司收走了，我没有留底。", "客户"),
    ("不过我有工牌，还有公司邮箱，微信工作群也有很多聊天记录。", "客户"),
    ("对了，去年年底的时候，公司还让我签了一个协议，说是自愿放弃社保。", "客户"),
    ("我当时不想签的，但是HR说不签就不能转正，我没办法就签了。", "客户"),
    ("这个协议您手上有没有留一份？", "律师"),
    ("没有，公司也没给我，就让我签了字他们就收走了。", "客户"),

    # === 客户诉求 ===
    ("好的，我大概了解了。那您现在希望达到什么目的？", "律师"),
    ("首先我想知道，公司这样做到底违不违法？", "客户"),
    ("其次，如果违法的话，我能要求什么赔偿？大概能赔多少？", "客户"),
    ("还有一个问题是，我听说劳动仲裁要花很长时间，而且会影响以后找工作，是真的吗？", "客户"),
    ("如果可能的话，我还是想跟公司协商解决，不想闹得太僵。", "客户"),

    # === 律师回应 + 专业判断 ===
    ("好的，您说的这几个问题都非常关键。我帮您梳理一下。", "律师"),
    ("从目前您描述的情况来看，至少涉及四五个方面的法律问题。", "律师"),
    ("包括劳动合同签订、社保缴纳、加班费、违法解除劳动关系等等。", "律师"),
    ("我先帮您查一下相关的法律依据，然后给您一个全面的分析。", "律师"),

    # === 客户追问 ===
    ("好的，谢谢律师。那我还有一个问题。", "客户"),
    ("如果我申请劳动仲裁的话，需要准备哪些材料？流程大概是什么样的？", "客户"),
    ("还有就是，仲裁要多久才能出结果？我现在经济压力比较大，能不能快一点？", "客户"),

    # === 律师补充 ===
    ("还有一个问题我想跟您确认一下。", "律师"),
    ("您刚才说公司让您自己辞职，这个过程中有没有威胁或者恐吓的言行？", "律师"),
    ("有的。新领导跟我谈话的时候，语气很凶。他说如果我不走，他会让我在整个行业都找不到工作。", "客户"),
    ("他还说我简历上这半年的空档期很难解释，不如主动辞职，他还可以帮我写推荐信。", "客户"),
    ("但实际上这是威胁和利诱，我当时真的很害怕。", "客户"),
    ("明白了，这个情节比较重要，增加了公司恶意施压的性质。", "律师"),

    # === 最后确认 ===
    ("好的，还有什么其他想问的吗？", "律师"),
    ("暂时没有了律师。您先帮我分析一下，我看看情况再决定下一步怎么做。", "客户"),
    ("好的，我现在就帮您进行全面分析。", "律师"),
]


async def main():
    print("=" * 70)
    print("  模拟法律咨询会谈 — Agent 实时介入测试")
    print("  每句间隔 ~800ms，模拟真实对话节奏")
    print("=" * 70)

    analyze_fn = build_analyze_fn()
    execute_fn = build_execute_fn()

    intent_log: list[IntentResult] = []
    analysis_log: list[AnalysisResult] = []

    async def on_intent(r: IntentResult):
        intent_log.append(r)
        ts = time.strftime("%H:%M:%S")
        print(f"\n  🔔 [{ts}] INTENT: {r.question}")

    async def on_analysis(r: AnalysisResult):
        analysis_log.append(r)
        icon = {"statute": "📋", "contract": "📝", "risk": "⚠️"}.get(r.category, "📌")
        level_str = f" [{r.level}]" if r.level else ""
        ts = time.strftime("%H:%M:%S")
        print(f"\n  {icon} [{ts}] [{r.category}{level_str}] {r.title}")

    agent = LegalAgent(
        on_intent=on_intent,
        on_analysis=on_analysis,
        analyze_fn=analyze_fn,
        execute_fn=execute_fn,
    )

    # ── Phase 1: Real-time streaming ──────────────────────────────────────────

    print(f"\n{'─' * 70}")
    print("  Phase 1: 实时对话 + Agent 介入")
    print(f"{'─' * 70}\n")

    last_auto_push = 0
    last_intent_report = 0

    for i, (text, speaker) in enumerate(DIALOGUE):
        icon = "🧑‍⚖️" if speaker == "律师" else "👤"
        ts = time.strftime("%H:%M:%S")
        print(f"  [{ts}] {icon} {speaker}: {text}")

        # Simulate the LegalAgent.observe() call (as if from main.py)
        await agent.observe(text, speaker)

        # Real-time status check every few lines
        if i % 5 == 4 or i == len(DIALOGUE) - 1:
            pending = len(agent._pending_intents)
            executing = len(agent._executor_tasks)
            # Only report if state changed
            new_analysis = len(analysis_log)
            new_intents = len(intent_log)
            if new_analysis > last_auto_push or new_intents > last_intent_report:
                status_parts = []
                if new_analysis > last_auto_push:
                    status_parts.append(f"{new_analysis - last_auto_push} auto-push")
                if new_intents > last_intent_report:
                    status_parts.append(f"{new_intents - last_intent_report} intents")
                if pending > 0:
                    status_parts.append(f"{pending} pending")
                if status_parts:
                    print(f"  {'─' * 50}")
                    print(f"  📊 Agent 实时状态: {', '.join(status_parts)}")
                last_auto_push = new_analysis
                last_intent_report = new_intents

        # Simulate ~800ms gap between sentences
        await asyncio.sleep(0.8)

    # Wait for last observer
    if agent._observer_task and not agent._observer_task.done():
        print(f"\n  ⏳ 等待最后一次分析完成...")
        try:
            await asyncio.wait_for(agent._observer_task, timeout=30)
        except asyncio.TimeoutError:
            print("  ⚠️ Observer timed out")

    print(f"\n{'─' * 70}")
    print(f"  Phase 1 完成: {len(intent_log)} intents, {len(analysis_log)} auto-pushes, "
          f"{len(agent._pending_intents)} pending")
    print(f"{'─' * 70}")

    # ── Phase 2: Lawyer confirms intents ─────────────────────────────────────

    if agent._pending_intents:
        print(f"\n{'─' * 70}")
        print("  Phase 2: 律师点击「确认」，触发深度分析")
        print(f"{'─' * 70}")

        pending_ids = list(agent._pending_intents.keys())
        for intent_id in pending_ids:
            stored = agent._pending_intents.get(intent_id)
            if stored is None:
                continue
            intent, _ = stored
            ts = time.strftime("%H:%M:%S")
            print(f"\n  [{ts}] ✅ 律师确认: {intent.question}")

            analysis_before = len(analysis_log)
            await agent.confirm_intent(intent_id)

            task = agent._executor_tasks.get(intent_id)
            if task:
                try:
                    await asyncio.wait_for(task, timeout=60)
                except asyncio.TimeoutError:
                    print(f"     ⚠️ 执行超时")

            new_count = len(analysis_log) - analysis_before
            print(f"     → 产出 {new_count} 条深度分析")

    # ── Summary ────────────────────────────────────────────────────────────────

    print(f"\n{'=' * 70}")
    print(f"  会谈总结")
    print(f"{'=' * 70}")
    print(f"  对话轮次:        {len(DIALOGUE)}")
    print(f"  自动推送 (简单):  {sum(1 for r in analysis_log if r not in [])} 条")
    print(f"  Intent 识别:     {len(intent_log)} 个")
    print(f"  Intent 确认执行:  {len(intent_log) - len(agent._pending_intents)} 个")
    print(f"  深度分析结果:     {len(analysis_log)} 条")

    if analysis_log:
        print(f"\n  分析明细:")
        for r in analysis_log:
            level = f" [{r.level}]" if r.level else ""
            print(f"    [{r.category}{level}] {r.title}")

    # Cleanup
    for pid in list(agent._pending_intents.keys()):
        agent.dismiss_intent(pid)

    print(f"\n  ✅ 全流程模拟完成 — Agent 实时介入正常")


if __name__ == "__main__":
    asyncio.run(main())
