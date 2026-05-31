"""FunASR 流式 STT 包装 V2。

与 v1 唯一区别：在 merge_with_close_reason 之后、ASR 之前插入 SCD 拆分。
从 v1 import 共享工具函数，避免重复。
"""

from __future__ import annotations

import array
import asyncio
from collections.abc import AsyncIterator

import numpy as np

from config import SR, VAD_RECHECK_INTERVAL_MS, VAD_SILENCE_MS
from diarization.enrollment import Enrollment
from diarization.matcher import match_speaker
from diarization.speaker_change_detector import VoiceprintState, detect_speaker_changes
from models.utterance import ClosedBy, Utterance
from stt.funasr_stream import (
    _asr_one,
    _get_models,
    _utt_id,
    _vad_segments_ms,
    merge_with_close_reason,
)


def _scd_split(
    bounds: list[tuple[int, int, ClosedBy]],
    snapshot: np.ndarray,
    enrollment: Enrollment | None,
    voiceprint: VoiceprintState | None = None,
) -> list[tuple[int, int, ClosedBy]]:
    """对 bounds 中 ≥2s 的长段跑 SCD，按切换点拆成 sub-bounds。

    voiceprint 跨 bounds 共享，client 种子化后状态保持。
    """
    if enrollment is None:
        return bounds

    if voiceprint is None:
        voiceprint = VoiceprintState(lawyer=enrollment.embedding)

    sub_bounds: list[tuple[int, int, ClosedBy]] = []
    for s_ms, e_ms, closed_by in bounds:
        duration = e_ms - s_ms
        if duration < 2000:
            sub_bounds.append((s_ms, e_ms, closed_by))
            continue

        seg_audio = snapshot[int(s_ms * SR / 1000) : int(e_ms * SR / 1000)]
        changes = detect_speaker_changes(seg_audio, voiceprint, sr=SR)

        if not changes:
            sub_bounds.append((s_ms, e_ms, closed_by))
            continue

        prev = s_ms
        for cp in changes:
            cp_abs = s_ms + cp
            if cp_abs - prev >= 500:
                sub_bounds.append((prev, cp_abs, "scd"))
                prev = cp_abs

        if e_ms - prev >= 500:
            sub_bounds.append((prev, e_ms, "scd"))
        else:
            # 丢弃末尾 <500ms 碎片，延长上一段
            if sub_bounds and sub_bounds[-1][2] == "scd":
                last_s, _, _ = sub_bounds[-1]
                sub_bounds[-1] = (last_s, e_ms, "scd")
            else:
                sub_bounds.append((prev, e_ms, closed_by))

    return sub_bounds


async def stream_stt_v2(
    audio_chunks: AsyncIterator[tuple[np.ndarray, float]],
    enrollment: Enrollment | None = None,
) -> AsyncIterator[Utterance]:
    """同 stream_stt，但在 ASR 前插入 Speaker Change Detection 拆分。"""
    vad_model, asr_model = _get_models()

    t0: float | None = None
    yielded_until_ms = 0
    last_vad_audio_ms = -VAD_RECHECK_INTERVAL_MS

    audio_buffer = array.array("f")
    spec_asr: dict[tuple[int, int], asyncio.Task] = {}

    voiceprint: VoiceprintState | None = None
    if enrollment is not None:
        voiceprint = VoiceprintState(lawyer=enrollment.embedding)

    def _spec_key_match(s_ms: int, e_ms: int, tol_ms: int = 100) -> tuple[int, int] | None:
        for k_s, k_e in spec_asr:
            if abs(k_s - s_ms) <= tol_ms and abs(k_e - e_ms) <= tol_ms:
                return (k_s, k_e)
        return None

    async def _emit_stable_or_final_v2(snapshot: np.ndarray, final: bool):
        nonlocal yielded_until_ms
        if len(snapshot) == 0:
            return
        # 清理超过 10 秒未 yield 的陈旧 spec task，避免长会话中累积
        stale_threshold_ms = yielded_until_ms - 10000
        for k in list(spec_asr.keys()):
            if k[1] < stale_threshold_ms:
                old_task = spec_asr.pop(k, None)
                if old_task is not None and not old_task.done():
                    old_task.cancel()
        total_ms = int(len(snapshot) * 1000 / SR)
        window_start_ms = max(0, yielded_until_ms - 500)
        window_start_sample = int(window_start_ms * SR / 1000)
        window_audio = snapshot[window_start_sample:]
        vad_out = await asyncio.to_thread(vad_model.generate, input=window_audio)
        raw_segs_rel = _vad_segments_ms(vad_out)
        raw_segs = [(s + window_start_ms, e + window_start_ms) for s, e in raw_segs_rel]
        bounds = merge_with_close_reason(raw_segs, snapshot)

        # V2 唯一改动：SCD 拆分
        sub_bounds = _scd_split(bounds, snapshot, enrollment, voiceprint)

        for s_ms, e_ms, closed_by in sub_bounds:
            if e_ms <= yielded_until_ms + 100:
                continue
            s_ms = max(s_ms, yielded_until_ms)
            silence_after_ms = total_ms - e_ms
            ready_to_spec = silence_after_ms >= 200 or final or closed_by == "soft_cap"
            if not ready_to_spec:
                continue

            matched_key = _spec_key_match(s_ms, e_ms)
            if matched_key is None:
                seg_audio = snapshot[int(s_ms * SR / 1000) : int(e_ms * SR / 1000)].copy()
                spec_asr[(s_ms, e_ms)] = asyncio.create_task(_asr_one(asr_model, seg_audio))
                matched_key = (s_ms, e_ms)

            stable = final or closed_by == "soft_cap" or (silence_after_ms >= VAD_SILENCE_MS)
            if not stable:
                continue

            text = await spec_asr[matched_key]
            for k in list(spec_asr.keys()):
                if k[1] <= e_ms + 100:
                    spec_asr.pop(k, None)

            if not text:
                continue
            t_start = (t0 or 0.0) + s_ms / 1000.0
            t_end = (t0 or 0.0) + e_ms / 1000.0
            speaker = None
            if enrollment is not None:
                speaker_audio = snapshot[int(s_ms * SR / 1000) : int(e_ms * SR / 1000)].copy()
                speaker = await asyncio.to_thread(match_speaker, speaker_audio, SR, enrollment)
            yield Utterance(
                id=_utt_id(t_start, text),
                text=text,
                t_start=t_start,
                t_end=t_end,
                speaker=speaker,
                closed_by=closed_by,
            )
            yielded_until_ms = max(yielded_until_ms, e_ms)

    async for chunk, t_rel in audio_chunks:
        if t0 is None:
            t0 = t_rel
        audio_buffer.frombytes(chunk.astype(np.float32).tobytes())
        total_ms = int(len(audio_buffer) * 1000 / SR)

        if total_ms - last_vad_audio_ms < VAD_RECHECK_INTERVAL_MS:
            continue
        last_vad_audio_ms = total_ms

        snapshot = np.array(audio_buffer, dtype=np.float32)
        async for utt in _emit_stable_or_final_v2(snapshot, final=False):
            yield utt

    snapshot = np.array(audio_buffer, dtype=np.float32)
    async for utt in _emit_stable_or_final_v2(snapshot, final=True):
        yield utt

    for task in spec_asr.values():
        if not task.done():
            task.cancel()
