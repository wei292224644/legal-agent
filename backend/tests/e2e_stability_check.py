"""IntentRouter 稳定性 + 延迟测试 — 同一对话跑 N 次，同时统计分类一致性和单步耗时。

为什么：
- 准确度：LLM 在 temperature=0.1 下仍有抖动，单次跑出来的"错误模式"未必稳定。
- 延迟：prompt 越写越长可能拖慢推理。准确度和延迟必须一起看，不能只优化一个。

输出：
- 每行 N 次的分类一致性（stable / unstable）
- 每行 N 次的延迟分布（min / median / max / avg）
- 全局延迟分布（P50 / P95 / max）
- 抖动行 + 高延迟行（>P95）双重高亮

不影响 CI，需要手动运行。环境变量 STABILITY_ROUNDS 控制轮次（默认 5）。
"""

import asyncio
import os
import statistics
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from judgment_logger import JudgmentLogger

from agent.intent_router import IntentRouter

ROUNDS = int(os.getenv("STABILITY_ROUNDS", "5"))

# 与 e2e_role_aware_dialogue.py 保持一致的对话脚本
turns = [
    ("lawyer", "你好，请坐。今天想咨询什么问题？"),
    ("client", "王律师您好，我被公司违法解除了。"),
    ("lawyer", "您在公司工作多久了？"),
    ("client", "两年三个月。"),
    ("lawyer", "月薪是多少，税前还是税后？"),
    ("client", "税前两万五。"),
    ("lawyer", "解除通知是什么时候收到的？"),
    ("client", "5月1号口头通知的。"),
    ("lawyer", "有书面解除通知吗？"),
    ("client", "还没有，只是主管口头说的。"),
    ("lawyer", "劳动合同签了吗，几年期？"),
    ("client", "签了，三年期的。"),
    ("lawyer", "公司给出的解除理由是什么？"),
    ("client", "说我不胜任工作。"),
    ("lawyer", "之前有没有绩效考核记录？"),
    ("client", "有的，但都是合格的。"),
    ("client", "我能拿多少赔偿？"),
    ("lawyer", "违法解除的话一般是2N。"),
    ("client", "N+1怎么算？"),
    ("lawyer", "N是工作年限，每满一年一个月工资。"),
    ("client", "那我该怎么跟公司谈？"),
    ("lawyer", "先准备证据清单。"),
    ("client", "需要准备哪些证据？"),
    ("lawyer", "劳动合同、工资流水、解除通知、考勤记录。"),
    ("client", "竞业限制最长多久？"),
    ("lawyer", "两年。"),
    ("client", "加班费按什么标准？"),
    ("lawyer", "工作日1.5倍，周末2倍，法定节假日3倍。"),
    ("client", "能赢吗？"),
    ("lawyer", "证据充分的话胜率很高，不用太担心。"),
    ("client", "谢谢王律师，我回去准备材料。"),
]


async def run_once(ir: IntentRouter) -> list[tuple[tuple[str, str], float]]:
    """跑一轮完整对话，返回每行 ((severity, intent_type), elapsed_seconds)。"""
    out = []
    for speaker, text in turns:
        t0 = time.monotonic()
        res = await ir.classify(text=text, speaker=speaker)
        elapsed = time.monotonic() - t0
        out.append(((res.severity, res.intent_type), elapsed))
    return out


def _fmt_ms(s: float) -> str:
    return f"{s * 1000:6.0f}ms"


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    sorted_v = sorted(values)
    k = (len(sorted_v) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_v) - 1)
    if f == c:
        return sorted_v[f]
    return sorted_v[f] + (sorted_v[c] - sorted_v[f]) * (k - f)


async def main():
    print("=" * 90)
    print(f"IntentRouter 稳定性 + 延迟测试 — {ROUNDS} 轮 × {len(turns)} 行 = {ROUNDS * len(turns)} 次调用")
    print(f"开始时间: {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 90)

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = Path(__file__).parent / "runs" / f"judgments_stability_{run_id}.jsonl"
    logger = JudgmentLogger(
        log_path, session_meta={"script": "e2e_stability_check", "rounds": ROUNDS, "turns": len(turns)}
    )
    print(f"判断落盘 → {log_path}")

    ir = logger.wrap_ir(IntentRouter())

    # all_runs[run_idx][row_idx] = ((severity, intent_type), elapsed)
    all_runs: list[list[tuple[tuple[str, str], float]]] = []
    for r in range(ROUNDS):
        print(f"\n--- Run {r + 1}/{ROUNDS} ---")
        t0 = time.monotonic()
        run = await run_once(ir)
        total = time.monotonic() - t0
        print(f"完成 {len(run)} 行 | 总耗时 {total:.2f}s | 平均 {total / len(run) * 1000:.0f}ms/行")
        all_runs.append(run)

    logger.close()
    print(f"\n判断落盘完成 → {log_path}")

    # 全局延迟统计
    all_latencies = [lat for run in all_runs for _, lat in run]
    p50 = _percentile(all_latencies, 0.5)
    p95 = _percentile(all_latencies, 0.95)
    mean = statistics.mean(all_latencies)
    max_lat = max(all_latencies)

    print("\n" + "=" * 90)
    print("全局延迟分布")
    print("=" * 90)
    print(f"  平均: {_fmt_ms(mean)}")
    print(f"  P50:  {_fmt_ms(p50)}")
    print(f"  P95:  {_fmt_ms(p95)}")
    print(f"  Max:  {_fmt_ms(max_lat)}")

    # 逐行分析
    print("\n" + "=" * 90)
    print("逐行: 准确度(N 次一致性) + 延迟(min / median / max)")
    print("=" * 90)
    print(
        f"{'状态':<4} {'行':<4} {'角色':<4} {'内容':<28} "
        f"{'分类(多数)':<28} {'一致':<6} {'min':<8} {'med':<8} {'max':<8}"
    )
    print("-" * 90)

    stable_count = 0
    unstable_rows: list[tuple[int, str, str, Counter, list[float]]] = []
    high_latency_rows: list[tuple[int, str, str, float]] = []

    for i, (speaker, text) in enumerate(turns):
        classes = [run[i][0] for run in all_runs]
        latencies = [run[i][1] for run in all_runs]
        counter = Counter(classes)
        (most_class, count) = counter.most_common(1)[0]
        is_stable = count == ROUNDS

        row_min = min(latencies)
        row_med = statistics.median(latencies)
        row_max = max(latencies)

        sp = "律" if speaker == "lawyer" else "客"
        snippet = (text[:26] + "…") if len(text) > 26 else text
        cls_label = f"{most_class[0]}/{most_class[1]}"
        marker = "✓" if is_stable else "✗"

        # max 延迟超过全局 P95 标记
        high_lat = row_max > p95
        lat_marker = "⚠" if high_lat else " "

        print(
            f"{marker:<4} {i + 1:<4} {sp:<4} {snippet:<28} {cls_label:<28} "
            f"{count}/{ROUNDS:<4} {_fmt_ms(row_min)} {_fmt_ms(row_med)} {_fmt_ms(row_max)}{lat_marker}"
        )

        if is_stable:
            stable_count += 1
        else:
            unstable_rows.append((i + 1, speaker, text, counter, latencies))

        if high_lat:
            high_latency_rows.append((i + 1, speaker, text, row_max))

    print("\n" + "=" * 90)
    print(f"准确度: 稳定 {stable_count}/{len(turns)} | 抖动 {len(unstable_rows)}/{len(turns)}")
    print(f"延迟: 平均 {_fmt_ms(mean)} | P95 {_fmt_ms(p95)} | 高延迟行 (>P95) {len(high_latency_rows)} 个")
    print("=" * 90)

    if unstable_rows:
        print("\n【抖动行详情】")
        for row_num, speaker, text, counter, latencies in unstable_rows:
            sp = "律" if speaker == "lawyer" else "客"
            print(f"\n  [{row_num:02d}] [{sp}] {text}")
            for (sev, it), c in counter.most_common():
                print(f"      {c}× → {sev}/{it}")
            print(
                f"      延迟: min={_fmt_ms(min(latencies))} "
                f"med={_fmt_ms(statistics.median(latencies))} "
                f"max={_fmt_ms(max(latencies))}"
            )

    if high_latency_rows:
        print("\n【高延迟行（max > 全局 P95）】")
        for row_num, speaker, text, lat in high_latency_rows:
            sp = "律" if speaker == "lawyer" else "客"
            print(f"  [{row_num:02d}] [{sp}] max={_fmt_ms(lat)} | {text}")

    print(f"\n结束时间: {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 90)


if __name__ == "__main__":
    asyncio.run(main())
