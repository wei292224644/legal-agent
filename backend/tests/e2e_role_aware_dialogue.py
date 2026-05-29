"""端到端真实对话测试 — 角色感知意图路由完整流程验证。

使用真实 LLM API（千问 + DeepSeek），逐句模拟 30 轮律师-客户劳动法律咨询，
验证 IntentRouter → ProfileAgent → Orchestrator → HeavyAgent 全链路。
"""

import asyncio
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# 加载 .env
load_dotenv(Path(__file__).parent.parent / ".env")

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from judgment_logger import JudgmentLogger

from agent.context_store import ContextStore
from agent.heavy_agent import HeavyAgent
from agent.intent_router import IntentRouter
from agent.orchestrator import Orchestrator
from agent.profile_agent import ProfileAgent
from models.utterance import Utterance

# 30 轮真实对话场景 — 括号内为预设期望分类 (speaker, text, expected_severity, expected_intent_type)
turns = [
    ("lawyer", "你好，请坐。今天想咨询什么问题？", "ignore", "none"),
    ("client", "王律师您好，我被公司违法解除了。", "complex", "query_law"),
    ("lawyer", "您在公司工作多久了？", "ignore", "none"),
    ("client", "两年三个月。", "simple", "record_only"),
    ("lawyer", "月薪是多少，税前还是税后？", "ignore", "none"),
    ("client", "税前两万五。", "simple", "record_only"),
    ("lawyer", "解除通知是什么时候收到的？", "ignore", "none"),
    ("client", "5月1号口头通知的。", "simple", "record_only"),
    ("lawyer", "有书面解除通知吗？", "ignore", "none"),
    ("client", "还没有，只是主管口头说的。", "ignore", "none"),
    ("lawyer", "劳动合同签了吗，几年期？", "ignore", "none"),
    ("client", "签了，三年期的。", "simple", "record_only"),
    ("lawyer", "公司给出的解除理由是什么？", "ignore", "none"),
    ("client", "说我不胜任工作。", "simple", "record_only"),
    ("lawyer", "之前有没有绩效考核记录？", "ignore", "none"),
    ("client", "有的，但都是合格的。", "ignore", "none"),
    ("client", "我能拿多少赔偿？", "simple", "compute_compensation"),
    ("lawyer", "违法解除的话一般是2N。", "ignore", "none"),
    ("client", "N+1怎么算？", "simple", "compute_compensation"),
    ("lawyer", "N是工作年限，每满一年一个月工资。", "ignore", "none"),
    ("client", "那我该怎么跟公司谈？", "complex", "strategy_advice"),
    ("lawyer", "先准备证据清单。", "ignore", "none"),
    ("client", "需要准备哪些证据？", "complex", "query_law"),
    ("lawyer", "劳动合同、工资流水、解除通知、考勤记录。", "ignore", "none"),
    ("client", "竞业限制最长多久？", "simple", "query_law"),
    ("lawyer", "两年。", "ignore", "none"),
    ("client", "加班费按什么标准？", "simple", "query_law"),
    ("lawyer", "工作日1.5倍，周末2倍，法定节假日3倍。", "ignore", "none"),
    ("client", "能赢吗？", "complex", "risk_evaluation"),
    ("lawyer", "证据充分的话胜率很高，不用太担心。", "ignore", "none"),
    ("client", "谢谢王律师，我回去准备材料。", "ignore", "none"),
]


async def main():
    print("=" * 80)
    print("角色感知意图路由 — 端到端真实对话测试")
    print(f"开始时间: {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 80)

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = Path(__file__).parent / "runs" / f"judgments_e2e_{run_id}.jsonl"
    logger = JudgmentLogger(log_path, session_meta={"script": "e2e_role_aware_dialogue", "turns": len(turns)})
    print(f"判断落盘 → {log_path}")

    ctx = ContextStore()
    orch = Orchestrator(
        ctx,
        ir=logger.wrap_ir(IntentRouter()),
        pa=logger.wrap_pa(ProfileAgent()),
        ha=logger.wrap_ha(HeavyAgent(ctx)),
    )
    await orch.start()

    all_suggestions = []
    pending_requests = []

    async def on_suggestion(text, meta):
        all_suggestions.append((text, meta))
        kind = meta.get("kind", "unknown")
        severity = meta.get("severity", "")
        intent_type = meta.get("intent_type", "")
        req_id = meta.get("request_id", "")

        if kind == "pending":
            pending_requests.append(req_id)
            print(f"    [建议] 🟡 PENDING 等待确认 | severity={severity} intent={intent_type} req={req_id}")
        elif kind == "ready":
            snippet = (text or "")[:60].replace("\n", " ")
            print(f"    [建议] 🟢 READY | severity={severity} intent={intent_type}")
            print(f"           {snippet}...")

    orch.set_suggestion_callback(on_suggestion)

    # 逐句处理
    for i, (speaker, text, exp_sev, exp_intent) in enumerate(turns, 1):
        utt = Utterance(
            id=f"u_{i:02d}",
            text=text,
            speaker=speaker,
            t_start=float(i) * 1.5,
            t_end=float(i + 1) * 1.5,
            timestamp=datetime.now(),
        )

        prefix = "律师" if speaker == "lawyer" else "客户"
        print(f"\n[{i:02d}/31] {prefix}: {text}")
        print(f"    [期望] severity={exp_sev} intent={exp_intent}")

        t0 = time.monotonic()
        generation = await orch.handle_utterance(utt)
        elapsed = time.monotonic() - t0

        # 等待 suggestion callback 完成
        await asyncio.sleep(0.3)

        print(f"    处理耗时: {elapsed:.2f}s | generation={generation}")

        # 每句话间隔 1.5s
        if i < len(turns):
            await asyncio.sleep(1.5)

    print("\n" + "=" * 80)
    print("对话结束，开始确认所有 pending 请求...")
    print("=" * 80)

    # 确认所有 pending
    for req_id in pending_requests:
        print(f"\n[确认] request_id={req_id}")
        t0 = time.monotonic()
        ok = await orch.confirm_analysis(req_id)
        await asyncio.sleep(0.3)
        print(f"       结果: {'成功' if ok else '失败'} | 耗时: {time.monotonic() - t0:.2f}s")

    # 最终总结
    await asyncio.sleep(0.5)

    print("\n" + "=" * 80)
    print("最终总结")
    print("=" * 80)

    profile = ctx.get_profile()
    print(f"\n📋 用户画像（共 {len(profile)} 条）:")
    for e in profile:
        print(f"   - {e.key}: {e.value}")

    history = ctx.get_full_history()
    print(f"\n🗣️ 对话历史（共 {len(history)} 轮）:")
    for u in history:
        sp = "律" if u.speaker == "lawyer" else "客"
        print(f"   [{sp}] {u.text}")

    ready_count = sum(1 for _, m in all_suggestions if m.get("kind") == "ready")
    pending_count = sum(1 for _, m in all_suggestions if m.get("kind") == "pending")
    print(f"\n📊 建议统计: ready={ready_count}, pending={pending_count}")

    print(f"\n结束时间: {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 80)

    # 清理
    await orch.shutdown()
    logger.close()
    print(f"判断落盘完成 → {log_path}")


if __name__ == "__main__":
    asyncio.run(main())
