#!/usr/bin/env python3
"""A/B 对比 v1 与 v2 STT 管线的说话人分割效果。

详细输出：
- 每段 utterance 的延迟分布（min/max/avg/p50/p95/p99）
- V1/V2 逐段明细（段号、时间、长度、speaker、文本）
- V1 粘连逐段明细
- V2 粘连逐段明细
- 汇总统计
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections.abc import AsyncIterator
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).parent / "src"))

from diarization.enrollment import enroll_speaker
from stt.funasr_stream import stream_stt
from stt.funasr_stream_v2 import stream_stt_v2


async def _chunk_iterator(
    audio: np.ndarray, sr: int, chunk_ms: int = 100
) -> AsyncIterator[tuple[np.ndarray, float]]:
    chunk_samples = int(sr * chunk_ms / 1000)
    for i in range(0, len(audio), chunk_samples):
        yield audio[i : i + chunk_samples], i / sr


async def _run_pipeline(audio: np.ndarray, sr: int, enrollment, pipeline_fn):
    """运行管线，返回 (utts, delays_ms)。

    delay_ms 定义为：yield 的实际系统时间 - 该段音频结束的理论时间（t0 + t_end）。
    """
    chunks = _chunk_iterator(audio, sr, chunk_ms=100)
    utts = []
    delays_ms = []
    pipeline_start = time.perf_counter()

    async for utt in pipeline_fn(chunks, enrollment=enrollment):
        now = time.perf_counter()
        # t0 在 stream_stt 内部设为第一个 chunk 的 t_rel（此处为 0）
        # 所以音频结束的理论时间 = utt.t_end
        delay_s = now - pipeline_start - utt.t_end
        delays_ms.append(delay_s * 1000)
        utts.append(utt)

    return utts, delays_ms


def _load_audio(path: str) -> tuple[np.ndarray, int]:
    audio, file_sr = sf.read(path, dtype="float32", always_2d=False)
    if audio.ndim == 2:
        audio = audio.mean(axis=1)
    if file_sr != 16000:
        import librosa
        audio = librosa.resample(audio, orig_sr=file_sr, target_sr=16000)
    return audio, 16000


def _format_utt(utt) -> str:
    spk = utt.speaker or "N/A"
    return f"[{spk:7}] {utt.text[:70]}"


def _find_overlaps(utt, other_utts, tol_ms: float = 200.0):
    s, e = utt.t_start * 1000, utt.t_end * 1000
    overlaps = []
    for ou in other_utts:
        os_, oe = ou.t_start * 1000, ou.t_end * 1000
        if e + tol_ms < os_ or oe + tol_ms < s:
            continue
        overlaps.append(ou)
    return overlaps


def _detect_cross_speaker(overlaps):
    if len(overlaps) < 2:
        return False
    speakers = {o.speaker for o in overlaps if o.speaker is not None}
    return len(speakers) >= 2


def _has_adhesion(utts_list, baseline_utts, tol_ms: float = 200.0):
    adhesions = []
    for u in utts_list:
        overlaps = _find_overlaps(u, baseline_utts, tol_ms)
        if _detect_cross_speaker(overlaps):
            adhesions.append((u, overlaps))
    return adhesions


def _delay_stats(delays_ms: list[float]) -> dict[str, float]:
    if not delays_ms:
        return {"count": 0, "min": 0.0, "max": 0.0, "avg": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0}
    arr = np.array(delays_ms)
    return {
        "count": len(arr),
        "min": float(np.min(arr)),
        "max": float(np.max(arr)),
        "avg": float(np.mean(arr)),
        "p50": float(np.percentile(arr, 50)),
        "p95": float(np.percentile(arr, 95)),
        "p99": float(np.percentile(arr, 99)),
    }


def _stats(utts):
    lawyers = sum(1 for u in utts if u.speaker == "lawyer")
    clients = sum(1 for u in utts if u.speaker == "client")
    uncertain = sum(1 for u in utts if u.speaker == "uncertain")
    total_dur = sum(u.t_end - u.t_start for u in utts)
    avg_dur = total_dur / max(len(utts), 1)
    scd = sum(1 for u in utts if u.closed_by == "scd")
    long_utts = sum(1 for u in utts if u.t_end - u.t_start >= 10.0)
    return {
        "count": len(utts),
        "lawyer": lawyers,
        "client": clients,
        "uncertain": uncertain,
        "total_dur": total_dur,
        "avg_dur": avg_dur,
        "scd_splits": scd,
        "long_utts": long_utts,
    }


def main():
    parser = argparse.ArgumentParser(description="A/B 对比 v1/v2 diarization")
    parser.add_argument("--wav", required=True, help="输入 WAV 文件路径")
    parser.add_argument("--enrollment", required=True, help="律师声纹注册 WAV")
    args = parser.parse_args()

    audio, sr = _load_audio(args.wav)
    enroll_audio, _ = _load_audio(args.enrollment)
    enrollment = enroll_speaker(enroll_audio, sr)

    async def _run():
        print("=" * 100)
        print("A/B 对比: V1 (无 SCD) vs V2 (有 SCD)")
        print(f"输入音频: {args.wav}  ({len(audio)/sr:.1f}s)")
        print("=" * 100)

        # ---- V1 ----
        print("\n[1/2] 运行 V1 管线 (无 Speaker Change Detection)...")
        t1_start = time.perf_counter()
        utts_v1, delays_v1 = await _run_pipeline(audio, sr, enrollment, stream_stt)
        t1_elapsed = time.perf_counter() - t1_start
        print(f"  -> 产出 {len(utts_v1)} 条 utterance, 管线总耗时 {t1_elapsed:.2f}s")

        # ---- V2 ----
        print("\n[2/2] 运行 V2 管线 (有 Speaker Change Detection)...")
        t2_start = time.perf_counter()
        utts_v2, delays_v2 = await _run_pipeline(audio, sr, enrollment, stream_stt_v2)
        t2_elapsed = time.perf_counter() - t2_start
        print(f"  -> 产出 {len(utts_v2)} 条 utterance, 管线总耗时 {t2_elapsed:.2f}s")

        d1 = _delay_stats(delays_v1)
        d2 = _delay_stats(delays_v2)

        # ---- 1. V1 逐段明细 ----
        print("\n" + "=" * 100)
        print("一、V1 逐段 Utterance 明细")
        print("-" * 100)
        print(f"{'#':>3}  {'开始':>7}  {'结束':>7}  {'长度(s)':>8}  {'延迟(ms)':>10}  {'Speaker':>8}  文本")
        print("-" * 100)
        for i, (u, delay) in enumerate(zip(utts_v1, delays_v1, strict=True), 1):
            dur = u.t_end - u.t_start
            flag = " [长段]" if dur >= 10.0 else ""
            print(f"{i:>3}  {u.t_start:>7.2f}  {u.t_end:>7.2f}  {dur:>8.2f}  {delay:>10.1f}  {u.speaker or 'N/A':>8}  {u.text[:60]}{flag}")

        # ---- 2. V2 逐段明细 ----
        print("\n" + "=" * 100)
        print("二、V2 逐段 Utterance 明细")
        print("-" * 100)
        print(f"{'#':>3}  {'开始':>7}  {'结束':>7}  {'长度(s)':>8}  {'延迟(ms)':>10}  {'Speaker':>8}  {'ClosedBy':>9}  文本")
        print("-" * 100)
        for i, (u, delay) in enumerate(zip(utts_v2, delays_v2, strict=True), 1):
            dur = u.t_end - u.t_start
            flag = " [长段]" if dur >= 10.0 else ""
            cb = u.closed_by or "N/A"
            print(f"{i:>3}  {u.t_start:>7.2f}  {u.t_end:>7.2f}  {dur:>8.2f}  {delay:>10.1f}  {u.speaker or 'N/A':>8}  {cb:>9}  {u.text[:60]}{flag}")

        # ---- 3. 延迟分布对比 ----
        print("\n" + "=" * 100)
        print("三、逐段延迟分布对比 (ms)")
        print("-" * 100)
        print(f"{'指标':>12}  {'V1':>14}  {'V2':>14}")
        print("-" * 100)
        for k in ("count", "min", "max", "avg", "p50", "p95", "p99"):
            print(f"{k:>12}  {d1[k]:>14.1f}  {d2[k]:>14.1f}")

        # ---- 4. V1 粘连分析 ----
        print("\n" + "=" * 100)
        print("四、V1 粘连分析（V1 utterance 被 V2 拆成多说话人）")
        print("-" * 100)
        v1_adhesions = _has_adhesion(utts_v1, utts_v2)
        if v1_adhesions:
            print(f"  发现 {len(v1_adhesions)} 处粘连：\n")
            for idx, (u, overlaps) in enumerate(v1_adhesions, 1):
                dur = u.t_end - u.t_start
                print(f"  [{idx}] V1 [{u.t_start:.2f}-{u.t_end:.2f}] {dur:.1f}s  speaker={u.speaker}")
                print(f"      文本: {u.text}")
                print(f"      -> 被 V2 拆成 {len(overlaps)} 段:")
                for o in overlaps:
                    o_dur = o.t_end - o.t_start
                    print(f"         V2 [{o.t_start:.2f}-{o.t_end:.2f}] {o_dur:.1f}s  {o.speaker:7}  {o.text[:70]}")
                print()
        else:
            print("  ✅ V1 未检测到粘连（相对 V2）")

        # ---- 5. V2 粘连分析 ----
        print("=" * 100)
        print("五、V2 粘连分析（V2 utterance 被 V1 拆成多说话人）")
        print("-" * 100)
        v2_adhesions = _has_adhesion(utts_v2, utts_v1)
        if v2_adhesions:
            print(f"  发现 {len(v2_adhesions)} 处粘连：\n")
            for idx, (u, overlaps) in enumerate(v2_adhesions, 1):
                dur = u.t_end - u.t_start
                print(f"  [{idx}] V2 [{u.t_start:.2f}-{u.t_end:.2f}] {dur:.1f}s  speaker={u.speaker}")
                print(f"      文本: {u.text}")
                print(f"      -> 被 V1 拆成 {len(overlaps)} 段:")
                for o in overlaps:
                    o_dur = o.t_end - o.t_start
                    print(f"         V1 [{o.t_start:.2f}-{o.t_end:.2f}] {o_dur:.1f}s  {o.speaker:7}  {o.text[:70]}")
                print()
        else:
            print("  ✅ V2 未检测到粘连（相对 V1）")

        # ---- 6. 标签一致性 ----
        print("=" * 100)
        print("六、标签一致性（一对一区间 speaker 标注对比）")
        print("-" * 100)
        mismatches = []
        for u1 in utts_v1:
            overlaps = _find_overlaps(u1, utts_v2)
            if len(overlaps) == 1:
                u2 = overlaps[0]
                if u1.speaker != u2.speaker:
                    mismatches.append((u1, u2))
        if mismatches:
            print(f"  不一致区间数: {len(mismatches)}")
            for u1, u2 in mismatches:
                print(f"  ! [{u1.t_start:.2f}-{u1.t_end:.2f}] V1={u1.speaker or 'N/A':7} vs V2={u2.speaker or 'N/A':7}")
        else:
            print("  ✅ 一对一区间标签完全一致")

        # ---- 7. 汇总统计 ----
        s1 = _stats(utts_v1)
        s2 = _stats(utts_v2)

        print("\n" + "=" * 100)
        print("七、汇总统计")
        print("-" * 100)
        print(f"{'指标':25}  {'V1':>14}  {'V2':>14}  {'变化':>12}")
        print("-" * 100)
        print(f"{'Utterance 总数':25}  {s1['count']:>14}  {s2['count']:>14}  {s2['count']-s1['count']:>+12}")
        print(f"{'Lawyer 段数':25}  {s1['lawyer']:>14}  {s2['lawyer']:>14}  {s2['lawyer']-s1['lawyer']:>+12}")
        print(f"{'Client 段数':25}  {s1['client']:>14}  {s2['client']:>14}  {s2['client']-s1['client']:>+12}")
        print(f"{'Uncertain 段数':25}  {s1['uncertain']:>14}  {s2['uncertain']:>14}  {s2['uncertain']-s1['uncertain']:>+12}")
        print(f"{'总语音时长(s)':25}  {s1['total_dur']:>14.1f}  {s2['total_dur']:>14.1f}  {s2['total_dur']-s1['total_dur']:>+12.1f}")
        print(f"{'平均段长(s)':25}  {s1['avg_dur']:>14.1f}  {s2['avg_dur']:>14.1f}  {s2['avg_dur']-s1['avg_dur']:>+12.1f}")
        print(f"{'>=10s 长段数':25}  {s1['long_utts']:>14}  {s2['long_utts']:>14}  {s2['long_utts']-s1['long_utts']:>+12}")
        print(f"{'SCD 触发拆分':25}  {s1['scd_splits']:>14}  {s2['scd_splits']:>14}  {s2['scd_splits']-s1['scd_splits']:>+12}")
        print(f"{'管线总耗时(s)':25}  {t1_elapsed:>14.2f}  {t2_elapsed:>14.2f}  {t2_elapsed-t1_elapsed:>+12.2f}")

        # ---- 8. 结论 ----
        print("\n" + "=" * 100)
        print("八、结论")
        print("-" * 100)
        solved = len(v1_adhesions)
        new_issues = len(v2_adhesions)
        print(f"  V1 粘连数（被 V2 拆成多说话人）: {solved}")
        print(f"  V2 粘连数（被 V1 拆成多说话人）: {new_issues}")
        print(f"  V2 SCD 实际拆分次数: {s2['scd_splits']}")
        print(f"  V1 管线耗时: {t1_elapsed:.2f}s")
        print(f"  V2 管线耗时: {t2_elapsed:.2f}s")
        print(f"  V2 额外耗时: {t2_elapsed - t1_elapsed:.2f}s ({(t2_elapsed - t1_elapsed) / t1_elapsed * 100:.1f}%)")

        if solved > 0 and new_issues == 0:
            print(f"  ✅ SCD 有效：解决了 {solved} 处粘连，未引入新粘连")
        elif solved > 0 and new_issues > 0:
            print(f"  ⚠️  部分有效：解决 {solved} 处粘连，但 V1 反检出 {new_issues} 处粒度差异")
        elif solved == 0 and new_issues > 0:
            print("  ❌ 负面效果：未解决粘连")
        else:
            print("  ➖ 无粘连")

    asyncio.run(_run())


if __name__ == "__main__":
    main()
