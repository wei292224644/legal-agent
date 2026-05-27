"""Simulate a full legal consultation session with debounce + user profile."""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from agent import AnalysisResult, IntentResult, LegalAgent
from agno_agents import build_analyze_fn, build_execute_fn

DIALOGUE = [
    ("您好，请坐。请问您今天来是想咨询哪方面的法律问题？", "律师"),
    ("律师您好，我遇到了劳动方面的问题，想请您帮忙看看。", "客户"),
    ("我是去年三月份入职的，在一家互联网公司做产品经理。", "客户"),
    ("入职的时候公司说试用期三个月，但是到现在已经一年多了，一直没有跟我签劳动合同。", "客户"),
    ("然后上个月，我们部门换了一个新领导。他找我谈话，说公司今年效益不好，要进行人员优化。", "客户"),
    ("他说我的工作表现不达标，让我自己写辞职信走人。", "客户"),
    ("而且也不给赔偿，连上个月工资都威胁说不给了。", "客户"),
    ("好的，我了解了。那社保和公积金呢？公司有没有给您交？", "律师"),
    ("这个也是问题。入职的时候HR说试用期不交社保，转正后再交。结果一直拖到现在都没交。", "客户"),
    ("公积金也没有，公司说创业公司不交公积金。", "客户"),
    ("还有加班的情况。我们公司说是996，但实际上经常加班到晚上十点、十一点。", "客户"),
    ("每周工作时间都在60个小时以上，但是公司说弹性工作制，不算加班，没有加班费。", "客户"),
    ("年假也没有休过，我入职到现在一次年假都没休。", "客户"),
    ("了解了。那您手上有哪些证据？比如工牌、工作群聊天记录这些。", "律师"),
    ("我有工牌，还有公司邮箱，微信工作群也有很多聊天记录。", "客户"),
    ("对了，去年年底公司还让我签了一个自愿放弃社保的协议，说不签就不能转正。", "客户"),
    ("协议公司也没给我留底。", "客户"),
    ("好的。那您现在希望达到什么目的？", "律师"),
    ("我想知道公司这样做违不违法？我能要求什么赔偿？大概能赔多少？", "客户"),
    ("还有，如果我申请劳动仲裁，需要准备什么材料？流程是什么样的？", "客户"),
    ("另外我听说仲裁会影响以后找工作，是真的吗？", "客户"),
    ("明白了。您的情况涉及多个法律问题，我帮您全面分析一下。", "律师"),
    ("对了律师，还有一个事。那个领导威胁我说，如果我不主动辞职，他让我在整个行业都找不到工作。", "客户"),
    ("我当时真的很害怕，这个算不算威胁？", "客户"),
]


class LoggingAgent(LegalAgent):
    """Wraps LegalAgent with real-time logging for simulation."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._obs_count = 0
        self._exec_count = 0

    async def observe(self, text: str, speaker: str) -> None:
        if speaker == "客户":
            self._obs_count += 1
            action = "重置" if self._debounce_timer and not self._debounce_timer.done() else "启动"
            ts = time.strftime("%H:%M:%S")
            print(f"  [{ts}] 📥 debounce {action} (timer={self._debounce_s}s): 「{text[:60]}」")
        await super().observe(text, speaker)

    async def _run_observer(self) -> None:
        ts = time.strftime("%H:%M:%S")
        profile_count = sum(len(v) for v in self._user_profile.values())
        print(f"\n  {'─' * 55}")
        print(f"  🔍 [{ts}] 分析 Agent 启动")
        print(f"  📊 画像 {profile_count} 条事实 | 上下文 {len(self._context_window)} 句")
        print(f"     prev_facts: {self._facts_summary[:120] if self._facts_summary else '(空)'}")
        print(f"  🤖 Deepseek 分析中...")

        t0 = time.time()
        await super()._run_observer()
        elapsed = time.time() - t0

        ts = time.strftime("%H:%M:%S")
        pending = len(self._pending_intents)
        print(f"  ✅ [{ts}] 完成 ({elapsed:.1f}s)")
        new_facts = self._facts_summary[:150] if self._facts_summary else "(空)"
        print(f"  📝 facts_summary: {new_facts}...")
        if pending:
            intents_preview = [self._pending_intents[k][0].question for k in self._pending_intents]
            print(f"  💡 intents: {intents_preview}")

    async def _run_executor(self, intent, context):
        self._exec_count += 1
        ts = time.strftime("%H:%M:%S")
        print(f"\n  {'─' * 55}")
        print(f"  ⚙️  [{ts}] 编排 Agent #{self._exec_count}: 「{intent.question[:60]}」")
        t0 = time.time()
        result_count_before = len([r for r in []])   # we track via callback
        await super()._run_executor(intent, context)
        elapsed = time.time() - t0
        ts = time.strftime("%H:%M:%S")
        print(f"  ✅ [{ts}] 完成 ({elapsed:.1f}s)")


async def main():
    print("=" * 65)
    print("  模拟法律咨询会谈 — Debounce + 用户画像")
    print("  ▸ 客户每句 → 重置 debounce timer（2s）")
    print("  ▸ 停顿 2s → 分析 Agent 启动（事实提取 + 需求判断）")
    print("  ▸ 不 cancel → 画像跨次传递 → 事实不丢失")
    print("=" * 65)

    analyze_fn = build_analyze_fn()
    execute_fn = build_execute_fn()

    intent_log = []
    analysis_log = []

    async def on_intent(r):
        intent_log.append(r)
        print(f"  💡 [INTENT] {r.question}")

    async def on_analysis(r):
        analysis_log.append(r)
        icon = {"statute": "📋", "contract": "📝", "risk": "⚠️"}.get(r.category, "📌")
        level_str = f" [{r.level}]" if r.level else ""
        print(f"  {icon} [AUTO-PUSH] [{r.category}{level_str}] {r.title}")

    agent = LoggingAgent(
        on_intent=on_intent,
        on_analysis=on_analysis,
        analyze_fn=analyze_fn,
        execute_fn=execute_fn,
        debounce_s=2.0,
    )

    # ── Phase 1: Dialogue with real-time speech ──────────────────────────────
    print(f"\n{'─' * 65}")
    print("  Phase 1: 实时对话（每句 ~800ms）")
    print(f"{'─' * 65}\n")

    for i, (text, speaker) in enumerate(DIALOGUE):
        icon = "🧑‍⚖️" if speaker == "律师" else "👤"
        ts = time.strftime("%H:%M:%S")
        print(f"  [{ts}] {icon} {speaker}: {text}")
        await agent.observe(text, speaker)
        await asyncio.sleep(0.8)

    # Wait for debounce to fire + analysis to complete
    print(f"\n  ⏳ 等 debounce 触发 + 分析完成...")
    await asyncio.sleep(3.5)  # debounce is 2s, wait for it to fire
    # Then wait for observer to finish
    deadline = time.time() + 120
    while agent._observer_running or agent._needs_reanalysis:
        await asyncio.sleep(0.5)
        if time.time() > deadline:
            print("  ⚠️ 分析超时")
            break
    print(f"  ✅ 分析完成")

    # ── Phase 1 results ──────────────────────────────────────────────────────
    print(f"\n{'─' * 65}")
    print(f"  Phase 1 完成")
    print(f"  ├─ Intent:         {len(intent_log)}")
    print(f"  ├─ Auto-push:      {len(analysis_log)}")
    print(f"  ├─ Pending:        {len(agent._pending_intents)}")
    print(f"  └─ 画像事实数:      {sum(len(v) for v in agent._user_profile.values())}")
    print(f"{'─' * 65}")

    # ── Phase 2: Confirm intents ─────────────────────────────────────────────
    pending = list(agent._pending_intents.keys())
    if pending:
        print(f"\n{'─' * 65}")
        print(f"  Phase 2: 确认 {len(pending)} 个 Intent")
        print(f"{'─' * 65}")
        for intent_id in pending:
            stored = agent._pending_intents.get(intent_id)
            if not stored:
                continue
            intent, _ = stored
            print(f"\n  🖱️  确认: 「{intent.question}」")
            await agent.confirm_intent(intent_id)
            task = agent._executor_tasks.get(intent_id)
            if task:
                await asyncio.wait_for(task, timeout=60)

    for pid in list(agent._pending_intents.keys()):
        agent.dismiss_intent(pid)

    # ── Final ─────────────────────────────────────────────────────────────────
    print(f"\n{'=' * 65}")
    print(f"  总结")
    print(f"  ├─ 对话轮次: {len(DIALOGUE)}")
    print(f"  ├─ Intent:   {len(intent_log)}")
    print(f"  └─ 分析结果: {len(analysis_log)}")

    if intent_log:
        print(f"\n  所有 Intent:")
        for r in intent_log:
            print(f"    💡 {r.question}")
    if analysis_log:
        print(f"\n  所有分析结果:")
        for r in analysis_log:
            level = f" [{r.level}]" if r.level else ""
            print(f"    [{r.category}{level}] {r.title}")

    print(f"\n  ✅ 完成")


if __name__ == "__main__":
    asyncio.run(main())
