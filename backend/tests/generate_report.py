"""从 e2e 测试日志生成详细报告。"""

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

RUNS_DIR = Path(__file__).parent / "runs"


def _percentile(values, p):
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def load_jsonl(path):
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def analyze_ir(records, expected_turns=None):
    """分析 IntentRouter 数据。"""
    ir_records = [r for r in records if r.get("agent") == "intent_router" and r.get("event") == "classify"]
    latencies = [r["latency_ms"] for r in ir_records]

    results = []
    for r in ir_records:
        out = r.get("output", {})
        results.append({
            "text": r.get("input", {}).get("text", "")[:40],
            "speaker": r.get("input", {}).get("speaker", ""),
            "severity": out.get("severity", "unknown"),
            "intent_type": out.get("intent_type", "unknown"),
            "law_domain": out.get("law_domain", ""),
            "latency_ms": r["latency_ms"],
        })

    # 准确性：如果有期望数据则对比
    accuracy = None
    if expected_turns:
        matched = 0
        total = min(len(results), len(expected_turns))
        for i in range(total):
            exp_sev, exp_intent = expected_turns[i]
            if results[i]["severity"] == exp_sev and results[i]["intent_type"] == exp_intent:
                matched += 1
        accuracy = {"matched": matched, "total": total, "rate": matched / total if total else 0}

    # 分类分布
    severity_dist = Counter(r["severity"] for r in results)
    intent_dist = Counter(r["intent_type"] for r in results)
    domain_dist = Counter(r["law_domain"] for r in results if r["law_domain"])

    return {
        "count": len(ir_records),
        "latency": {
            "min": min(latencies) if latencies else 0,
            "max": max(latencies) if latencies else 0,
            "avg": statistics.mean(latencies) if latencies else 0,
            "p50": _percentile(latencies, 0.5),
            "p95": _percentile(latencies, 0.95),
            "p99": _percentile(latencies, 0.99),
        },
        "accuracy": accuracy,
        "severity_dist": dict(severity_dist),
        "intent_dist": dict(intent_dist),
        "domain_dist": dict(domain_dist),
        "results": results,
    }


def analyze_pa(records):
    """分析 ProfileAgent 数据。"""
    pa_records = [r for r in records if r.get("agent") == "profile_agent" and r.get("event") == "extract"]
    latencies = [r["latency_ms"] for r in pa_records]

    total_entries = 0
    empty_count = 0
    key_dist = Counter()

    for r in pa_records:
        out = r.get("output", [])
        if not out:
            empty_count += 1
        else:
            total_entries += len(out)
            for e in out:
                key_dist[e.get("key", "unknown")] += 1

    return {
        "count": len(pa_records),
        "latency": {
            "min": min(latencies) if latencies else 0,
            "max": max(latencies) if latencies else 0,
            "avg": statistics.mean(latencies) if latencies else 0,
            "p50": _percentile(latencies, 0.5),
            "p95": _percentile(latencies, 0.95),
            "p99": _percentile(latencies, 0.99),
        },
        "total_entries": total_entries,
        "empty_count": empty_count,
        "empty_rate": empty_count / len(pa_records) if pa_records else 0,
        "entries_per_call": total_entries / len(pa_records) if pa_records else 0,
        "key_dist": dict(key_dist.most_common(20)),
    }


def analyze_ha(records):
    """分析 HeavyAgent 数据。"""
    ha_records = [r for r in records if r.get("agent") == "heavy_agent"]
    latencies = [r["latency_ms"] for r in ha_records]

    event_dist = Counter(r.get("event", "unknown") for r in ha_records)
    intent_dist = Counter(r.get("input", {}).get("intent_type", "unknown") for r in ha_records)

    # 分析输出长度
    output_lengths = []
    for r in ha_records:
        out = r.get("output", "")
        if isinstance(out, str):
            output_lengths.append(len(out))
        elif isinstance(out, dict):
            output_lengths.append(len(json.dumps(out, ensure_ascii=False)))
        else:
            output_lengths.append(len(str(out)))

    return {
        "count": len(ha_records),
        "latency": {
            "min": min(latencies) if latencies else 0,
            "max": max(latencies) if latencies else 0,
            "avg": statistics.mean(latencies) if latencies else 0,
            "p50": _percentile(latencies, 0.5),
            "p95": _percentile(latencies, 0.95),
            "p99": _percentile(latencies, 0.99),
        },
        "event_dist": dict(event_dist),
        "intent_dist": dict(intent_dist),
        "output_length": {
            "min": min(output_lengths) if output_lengths else 0,
            "max": max(output_lengths) if output_lengths else 0,
            "avg": statistics.mean(output_lengths) if output_lengths else 0,
            "p50": _percentile(output_lengths, 0.5),
            "p95": _percentile(output_lengths, 0.95),
        },
    }


def generate_report():
    """生成完整报告。"""
    # e2e_role_aware 期望数据
    expected_turns = [
        ("ignore", "none"),
        ("complex", "query_law"),
        ("ignore", "none"),
        ("simple", "record_only"),
        ("ignore", "none"),
        ("simple", "record_only"),
        ("ignore", "none"),
        ("simple", "record_only"),
        ("ignore", "none"),
        ("ignore", "none"),
        ("ignore", "none"),
        ("simple", "record_only"),
        ("ignore", "none"),
        ("simple", "record_only"),
        ("ignore", "none"),
        ("ignore", "none"),
        ("simple", "compute_compensation"),
        ("ignore", "none"),
        ("simple", "compute_compensation"),
        ("ignore", "none"),
        ("complex", "strategy_advice"),
        ("ignore", "none"),
        ("complex", "query_law"),
        ("ignore", "none"),
        ("simple", "query_law"),
        ("ignore", "none"),
        ("simple", "query_law"),
        ("ignore", "none"),
        ("complex", "risk_evaluation"),
        ("ignore", "none"),
        ("ignore", "none"),
    ]

    stability_records = load_jsonl(RUNS_DIR / "judgments_stability_20260529_112311.jsonl")
    e2e_records = load_jsonl(RUNS_DIR / "judgments_e2e_20260529_112952.jsonl")
    multi_records = load_jsonl(RUNS_DIR / "judgments_multi_20260529_113218.jsonl")

    # 合并所有 IR 记录
    all_ir = [r for r in stability_records + e2e_records + multi_records if r.get("agent") == "intent_router"]
    all_pa = [r for r in e2e_records + multi_records if r.get("agent") == "profile_agent"]
    all_ha = [r for r in e2e_records + multi_records if r.get("agent") == "heavy_agent"]

    report = {
        "IntentRouter": {
            "stability_test": analyze_ir(stability_records),
            "e2e_test": analyze_ir(e2e_records, expected_turns),
            "multi_test": analyze_ir(multi_records),
            "overall": analyze_ir(all_ir),
        },
        "ProfileAgent": {
            "e2e_test": analyze_pa(e2e_records),
            "multi_test": analyze_pa(multi_records),
            "overall": analyze_pa(all_pa),
        },
        "HeavyAgent": {
            "e2e_test": analyze_ha(e2e_records),
            "multi_test": analyze_ha(multi_records),
            "overall": analyze_ha(all_ha),
        },
    }

    return report


def print_report(report):
    """打印格式化报告。"""
    print("=" * 80)
    print("Agent E2E 测试详细报告")
    print("=" * 80)
    print()

    # IntentRouter
    print("## 一、IntentRouter（角色感知意图路由器）")
    print()
    for test_name, data in report["IntentRouter"].items():
        label = {"stability_test": "稳定性测试", "e2e_test": "端到端测试", "multi_test": "多剧本测试", "overall": "总体"}[test_name]
        print(f"### {label}")
        print(f"  调用次数: {data['count']}")
        lat = data["latency"]
        print(f"  延迟(ms): min={lat['min']:.0f} | avg={lat['avg']:.0f} | p50={lat['p50']:.0f} | p95={lat['p95']:.0f} | p99={lat['p99']:.0f} | max={lat['max']:.0f}")
        if data.get("accuracy"):
            acc = data["accuracy"]
            print(f"  准确率:   {acc['matched']}/{acc['total']} = {acc['rate']*100:.1f}%")
        if data.get("severity_dist"):
            print(f"  severity 分布: {data['severity_dist']}")
        if data.get("intent_dist"):
            print(f"  intent 分布:   {data['intent_dist']}")
        if data.get("domain_dist"):
            print(f"  domain 分布:   {dict(list(data['domain_dist'].items())[:10])}")
        print()

    # ProfileAgent
    print("## 二、ProfileAgent（法律事实提取器）")
    print()
    for test_name, data in report["ProfileAgent"].items():
        label = {"e2e_test": "端到端测试", "multi_test": "多剧本测试", "overall": "总体"}[test_name]
        print(f"### {label}")
        print(f"  调用次数:    {data['count']}")
        lat = data["latency"]
        print(f"  延迟(ms):    min={lat['min']:.0f} | avg={lat['avg']:.0f} | p50={lat['p50']:.0f} | p95={lat['p95']:.0f} | p99={lat['p99']:.0f} | max={lat['max']:.0f}")
        print(f"  提取条目:    {data['total_entries']} 条（平均每轮 {data['entries_per_call']:.2f} 条）")
        print(f"  空返回:      {data['empty_count']}/{data['count']} = {data['empty_rate']*100:.1f}%")
        print(f"  高频 key TOP10: {dict(list(data['key_dist'].items())[:10])}")
        print()

    # HeavyAgent
    print("## 三、HeavyAgent（法律深度分析）")
    print()
    for test_name, data in report["HeavyAgent"].items():
        label = {"e2e_test": "端到端测试", "multi_test": "多剧本测试", "overall": "总体"}[test_name]
        print(f"### {label}")
        print(f"  调用次数:    {data['count']}")
        lat = data["latency"]
        print(f"  延迟(ms):    min={lat['min']:.0f} | avg={lat['avg']:.0f} | p50={lat['p50']:.0f} | p95={lat['p95']:.0f} | p99={lat['p99']:.0f} | max={lat['max']:.0f}")
        print(f"  事件分布:    {data['event_dist']}")
        print(f"  意图分布:    {dict(list(data['intent_dist'].items())[:10])}")
        out = data["output_length"]
        print(f"  输出长度:    min={out['min']:.0f} | avg={out['avg']:.0f} | p50={out['p50']:.0f} | p95={out['p95']:.0f} | max={out['max']:.0f} (字符)")
        print()


if __name__ == "__main__":
    report = generate_report()
    print_report(report)
