"""多剧本端到端测试 runner。

用法:
    uv run python tests/e2e_multi_dialogue.py              # 运行全部剧本
    uv run python tests/e2e_multi_dialogue.py labor        # 运行 labor_dispute_long
    uv run python tests/e2e_multi_dialogue.py traffic      # 运行 traffic_accident_short
    uv run python tests/e2e_multi_dialogue.py theft        # 运行 criminal_theft_long
"""

import argparse
import asyncio
import importlib.util
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__)))

from judgment_logger import JudgmentLogger

from agent.context_store import ContextStore
from agent.heavy_agent import HeavyAgent
from agent.intent_router import IntentRouter
from agent.orchestrator import Orchestrator
from agent.profile_agent import ProfileAgent
from models.utterance import Utterance

DIALOGUE_DIR = Path(__file__).parent / "dialogues"

SCRIPTS = {
    "labor": "labor_dispute_long.py",
    "traffic": "traffic_accident_short.py",
    "probation": "labor_probation_short.py",
    "house": "house_dispute_medium.py",
    "loan": "loan_dispute_medium.py",
    "divorce": "divorce_property_long.py",
    "theft": "criminal_theft_long.py",
}


def load_dialogue(name: str):
    """加载剧本模块，返回 turns 列表。"""
    path = DIALOGUE_DIR / SCRIPTS[name]
    spec = importlib.util.spec_from_file_location(f"dialogue_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.turns


def discover_scripts():
    """发现所有可用剧本。"""
    available = {}
    for key, filename in SCRIPTS.items():
        if (DIALOGUE_DIR / filename).exists():
            available[key] = filename
    return available


async def run_single_dialogue(name: str, turns: list, logger: JudgmentLogger):
    """运行单个剧本，返回统计结果。"""
    print(f"\n{'=' * 80}")
    print(f"剧本: {name} ({len(turns)} 轮)")
    print(f"{'=' * 80}")

    ctx = ContextStore()
    orch = Orchestrator(
        ctx,
        ir=logger.wrap_ir(IntentRouter()),
        pa=logger.wrap_pa(ProfileAgent()),
        ha=logger.wrap_ha(HeavyAgent(ctx)),
    )

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
            print(f"    [建议] PENDING | {severity}/{intent_type} req={req_id}")
        elif kind == "ready":
            snippet = (text or "")[:50].replace("\n", " ")
            print(f"    [建议] READY | {severity}/{intent_type}")
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
        print(f"\n[{i:02d}/{len(turns)}] {prefix}: {text}")
        print(f"    [期望] {exp_sev}/{exp_intent}")

        t0 = time.monotonic()
        generation = await orch.handle_utterance(utt)
        elapsed = time.monotonic() - t0
        await asyncio.sleep(0.2)
        print(f"    耗时: {elapsed:.2f}s | gen={generation}")

    # 确认所有 pending
    print(f"\n{'=' * 80}")
    print(f"确认 {len(pending_requests)} 个 pending...")
    print(f"{'=' * 80}")
    for req_id in pending_requests:
        print(f"\n[确认] {req_id}")
        t0 = time.monotonic()
        ok = await orch.confirm_analysis(req_id)
        await asyncio.sleep(0.2)
        print(f"       结果: {'成功' if ok else '失败'} | 耗时: {time.monotonic() - t0:.2f}s")

    # 收集统计
    await asyncio.sleep(0.3)

    profile = ctx.get_profile()
    history = ctx.get_full_history()
    ready_count = sum(1 for _, m in all_suggestions if m.get("kind") == "ready")
    pending_count = sum(1 for _, m in all_suggestions if m.get("kind") == "pending")

    print(f"\n{'=' * 80}")
    print(f"剧本 {name} 总结")
    print(f"{'=' * 80}")
    print(f"画像提取: {len(profile)} 条")
    print(f"对话轮数: {len(history)}")
    print(f"建议统计: ready={ready_count}, pending={pending_count}")

    await orch.shutdown()

    return {
        "name": name,
        "turns": len(turns),
        "profile_count": len(profile),
        "ready_count": ready_count,
        "pending_count": pending_count,
    }


async def main():
    parser = argparse.ArgumentParser(description="多剧本端到端测试")
    parser.add_argument("scripts", nargs="*", help=f"剧本名: {', '.join(SCRIPTS.keys())}")
    parser.add_argument("--all", action="store_true", help="运行全部剧本")
    args = parser.parse_args()

    available = discover_scripts()
    if not available:
        print("没有找到剧本文件")
        return

    if args.all:
        to_run = list(available.keys())
    elif args.scripts:
        to_run = []
        for s in args.scripts:
            if s in available:
                to_run.append(s)
            else:
                print(f"未知剧本: {s}，可用: {', '.join(available.keys())}")
                return
    else:
        to_run = list(available.keys())

    print("=" * 80)
    print("多剧本端到端测试")
    print(f"开始时间: {datetime.now().strftime('%H:%M:%S')}")
    print(f"运行剧本: {', '.join(to_run)}")
    print("=" * 80)

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = Path(__file__).parent / "runs" / f"judgments_multi_{run_id}.jsonl"
    logger = JudgmentLogger(
        log_path,
        session_meta={"script": "e2e_multi_dialogue", "run_count": len(to_run)},
    )
    print(f"判断落盘 -> {log_path}\n")

    results = []
    t_start = time.monotonic()

    for name in to_run:
        turns = load_dialogue(name)
        result = await run_single_dialogue(name, turns, logger)
        results.append(result)

        # 剧本间间隔
        if name != to_run[-1]:
            await asyncio.sleep(2)

    logger.close()

    # 全局总结
    print(f"\n{'=' * 80}")
    print("全局总结")
    print(f"{'=' * 80}")
    print(f"总耗时: {time.monotonic() - t_start:.1f}s")
    print(f"剧本数: {len(results)}")
    print(f"总轮数: {sum(r['turns'] for r in results)}")
    print(f"总画像: {sum(r['profile_count'] for r in results)} 条")
    print(f"总 ready: {sum(r['ready_count'] for r in results)}")
    print(f"总 pending: {sum(r['pending_count'] for r in results)}")
    print("\n各剧本明细:")
    for r in results:
        print(
            f"  {r['name']:<12s}: {r['turns']:>3d}轮  画像={r['profile_count']:>2d}  ready={r['ready_count']:>2d}  pending={r['pending_count']:>2d}"
        )
    print(f"\n落盘文件: {log_path}")
    print(f"结束时间: {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
