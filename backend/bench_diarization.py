#!/usr/bin/env python3
"""A/B 对比 v1 与 v2 STT 管线的说话人分割效果。"""

from __future__ import annotations

import argparse
import asyncio
import sys
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
    """无真实时间延迟的顺序 chunk 迭代器。"""
    chunk_samples = int(sr * chunk_ms / 1000)
    for i in range(0, len(audio), chunk_samples):
        yield audio[i : i + chunk_samples], i / sr


async def _run_pipeline(audio: np.ndarray, sr: int, enrollment, pipeline_fn):
    chunks = _chunk_iterator(audio, sr, chunk_ms=100)
    utts = []
    async for utt in pipeline_fn(chunks, enrollment=enrollment):
        utts.append(utt)
    return utts


def _load_audio(path: str) -> np.ndarray:
    audio, sr = sf.read(path, dtype="float32", always_2d=False)
    if audio.ndim == 2:
        audio = audio.mean(axis=1)
    if sr != 16000:
        import librosa

        audio = librosa.resample(audio, orig_sr=sr, target_sr=16000)
    return audio


def _format_utt(utt) -> str:
    spk = utt.speaker or "N/A"
    return f"[{spk}] {utt.text[:50]}"


def _find_overlaps(utt, other_utts, tol_ms: float = 200.0):
    s, e = utt.t_start * 1000, utt.t_end * 1000
    overlaps = []
    for ou in other_utts:
        os_, oe = ou.t_start * 1000, ou.t_end * 1000
        if e + tol_ms < os_ or oe + tol_ms < s:
            continue
        overlaps.append(ou)
    return overlaps


def _detect_cross_speaker(utt, overlaps):
    if len(overlaps) < 2:
        return False
    speakers = {o.speaker for o in overlaps if o.speaker is not None}
    return len(speakers) >= 2


def main():
    parser = argparse.ArgumentParser(description="A/B 对比 v1/v2 diarization")
    parser.add_argument("--wav", required=True, help="输入 WAV 文件路径")
    parser.add_argument("--enrollment", required=True, help="律师声纹注册 WAV")
    args = parser.parse_args()

    audio = _load_audio(args.wav)
    enroll_audio = _load_audio(args.enrollment)
    sr = 16000
    enrollment = enroll_speaker(enroll_audio, sr)

    async def _run():
        print("=" * 70)
        print("Running V1 pipeline...")
        utts_v1 = await _run_pipeline(audio, sr, enrollment, stream_stt)
        print(f"  V1 产出 {len(utts_v1)} 条 utterance")

        print("Running V2 pipeline...")
        utts_v2 = await _run_pipeline(audio, sr, enrollment, stream_stt_v2)
        print(f"  V2 产出 {len(utts_v2)} 条 utterance")

        # 1. 时间轴并排表
        print("\n" + "=" * 70)
        print("Timeline comparison")
        print("-" * 70)
        all_events = []
        for u in utts_v1:
            all_events.append((u.t_start, u.t_end, "v1", u))
        for u in utts_v2:
            all_events.append((u.t_start, u.t_end, "v2", u))
        all_events.sort(key=lambda x: x[0])
        for s, e, ver, u in all_events:
            print(f"{ver:3} {s:7.2f}-{e:7.2f}s  {_format_utt(u)}")

        # 2. 粘连检测
        print("\n" + "=" * 70)
        print("Cross-speaker adhesion check (V1 as baseline)")
        print("-" * 70)
        cross_count = 0
        for u in utts_v1:
            overlaps = _find_overlaps(u, utts_v2)
            if _detect_cross_speaker(u, overlaps):
                cross_count += 1
                print(
                    f"  ⚠ V1 [{u.t_start:.2f}-{u.t_end:.2f}] {u.speaker} "
                    f"split into multiple V2 speakers:"
                )
                for o in overlaps:
                    print(
                        f"      V2 [{o.t_start:.2f}-{o.t_end:.2f}] {o.speaker}  {o.text[:40]}"
                    )
            elif len(overlaps) == 1 and overlaps[0].speaker != u.speaker:
                print(
                    f"  ! label mismatch V1={u.speaker} vs "
                    f"V2={overlaps[0].speaker} [{u.t_start:.2f}-{u.t_end:.2f}]"
                )

        # 3. 汇总统计
        def _stats(utts):
            lawyers = sum(1 for u in utts if u.speaker == "lawyer")
            clients = sum(1 for u in utts if u.speaker == "client")
            uncertain = sum(1 for u in utts if u.speaker == "uncertain")
            avg_dur = sum(u.t_end - u.t_start for u in utts) / max(len(utts), 1)
            scd = sum(1 for u in utts if u.closed_by == "scd")
            return len(utts), lawyers, clients, uncertain, avg_dur, scd

        n1, l1, c1, u1, d1, s1 = _stats(utts_v1)
        n2, l2, c2, u2, d2, s2 = _stats(utts_v2)

        print("\n" + "=" * 70)
        print("Summary")
        print("-" * 70)
        print(f"{'':20}  {'V1':>10}  {'V2':>10}")
        print(f"{'Utterances:':20}  {n1:>10}  {n2:>10}")
        print(f"{'Lawyer:':20}  {l1:>10}  {l2:>10}")
        print(f"{'Client:':20}  {c1:>10}  {c2:>10}")
        print(f"{'Uncertain:':20}  {u1:>10}  {u2:>10}")
        print(f"{'Avg duration:':20}  {d1:>10.1f}s  {d2:>10.1f}s")
        print(f"{'SCD splits:':20}  {s1:>10}  {s2:>10}")
        print(f"{'Cross-speaker (V1):':20}  {cross_count:>10}")

    asyncio.run(_run())


if __name__ == "__main__":
    main()
