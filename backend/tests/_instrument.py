"""定向埋点(诊断专用,生产代码零改动)。

钉死 "agent 并发 → STT 延迟 7x" 的机制,区分三个嫌疑:
  A. 线程池排队  → to_thread 的 "提交→线程内开始执行" 间隔(queue_s)
  B. 事件循环阻塞 → loop-lag 探针(sleep 实际睡了多久 vs 期望)
  C. CPU 饱和    → to_thread 的 "线程内执行" 纯耗时(exec_s),对比有/无 agent

用法(在 asyncio.run 之前):
    import _instrument; _instrument.patch_to_thread()
async 上下文里启动探针:
    probe = _instrument.start_loop_probe()
结束时:
    probe.cancel(); _instrument.report(rlog)
"""

from __future__ import annotations

import asyncio
import statistics
import threading
import time
from collections import defaultdict

_orig_to_thread = asyncio.to_thread
_records: dict[str, list[tuple[float, float]]] = defaultdict(list)  # label -> [(queue_s, exec_s)]
_lock = threading.Lock()
_loop_lag: list[float] = []


def _classify(func) -> str:
    """区分 vad / asr / match_speaker —— vad、asr 都是 AutoModel.generate,
    靠 __self__ 是哪个模型实例区分(运行时模型已建好)。"""
    import stt.funasr_stream as fs

    slf = getattr(func, "__self__", None)
    if slf is not None:
        if slf is getattr(fs, "_vad_model", None):
            return "vad"
        if slf is getattr(fs, "_asr_model", None):
            return "asr"
    return getattr(func, "__name__", "other")


def patch_to_thread() -> None:
    """monkeypatch asyncio.to_thread,记录每次调用的排队时长 + 纯执行时长。"""

    async def _timed(func, /, *args, **kwargs):
        submit = time.perf_counter()
        label = _classify(func)

        def wrapped(*a, **kw):
            enter = time.perf_counter()  # 线程内真正开始执行
            r = func(*a, **kw)
            done = time.perf_counter()
            with _lock:
                _records[label].append((enter - submit, done - enter))
            return r

        return await _orig_to_thread(wrapped, *args, **kwargs)

    asyncio.to_thread = _timed


async def _probe(interval: float) -> None:
    while True:
        t0 = time.perf_counter()
        await asyncio.sleep(interval)
        lag = time.perf_counter() - t0 - interval
        _loop_lag.append(max(0.0, lag))


def start_loop_probe(interval: float = 0.05) -> asyncio.Task:
    """每 interval 秒醒一次,记录被事件循环耽误的时长。"""
    return asyncio.create_task(_probe(interval))


def _stats_ms(values_s: list[float]) -> dict:
    if not values_s:
        return {}
    s = sorted(values_s)

    def pct(p: float) -> float:
        k = (len(s) - 1) * p
        f = int(k)
        c = min(f + 1, len(s) - 1)
        return s[f] if f == c else s[f] + (s[c] - s[f]) * (k - f)

    return {
        "n": len(s),
        "avg": round(statistics.mean(s) * 1000, 1),
        "p50": round(pct(0.5) * 1000, 1),
        "p95": round(pct(0.95) * 1000, 1),
        "max": round(max(s) * 1000, 1),
    }


def report(rlog=None) -> dict:
    """聚合打印 + (可选)写入 RunLogger metric。返回结构化结果。"""
    out: dict = {"to_thread": {}, "loop_lag_ms": {}}
    with _lock:
        for label, recs in _records.items():
            queues = [q for q, _ in recs]
            execs = [e for _, e in recs]
            out["to_thread"][label] = {
                "queue_ms": _stats_ms(queues),  # A:排队
                "exec_ms": _stats_ms(execs),  # C:纯执行
            }
    out["loop_lag_ms"] = _stats_ms(_loop_lag)  # B:loop 阻塞
    out["loop_lag_blocked_pct"] = (
        round(sum(1 for x in _loop_lag if x > 0.01) / len(_loop_lag) * 100, 1) if _loop_lag else 0.0
    )

    print("\n" + "=" * 80)
    print("定向埋点 — 机制定位")
    print("=" * 80)
    print("\n[A 线程池排队 / C 纯执行] to_thread 各环节(ms):")
    for label, d in out["to_thread"].items():
        print(f"  {label:>14}  queue {d['queue_ms']}  |  exec {d['exec_ms']}")
    print(f"\n[B 事件循环阻塞] loop-lag(ms): {out['loop_lag_ms']}")
    print(f"  loop 被阻塞(>10ms)占比: {out['loop_lag_blocked_pct']}%")
    print("\n读法: queue 飙=线程池排队(A); exec 飙=CPU争用(C); loop-lag 飙=事件循环阻塞(B)")
    print("=" * 80, flush=True)

    if rlog is not None:
        rlog.set_metric("instrument_to_thread", out["to_thread"])
        rlog.set_metric("instrument_loop_lag_ms", out["loop_lag_ms"])
        rlog.set_metric("instrument_loop_blocked_pct", out["loop_lag_blocked_pct"])
    return out
