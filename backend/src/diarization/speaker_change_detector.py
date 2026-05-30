"""Speaker Change Detection：对单段长音频滑窗提取 cam++ embedding，检测说话人切换点。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from config import SR
from diarization.voiceprint import extract_embedding


@dataclass
class VoiceprintState:
    """SCD 内部维护的动态声纹状态。"""

    lawyer: np.ndarray
    client: np.ndarray | None = None


def _ema_update(current: np.ndarray, new: np.ndarray, weight: float = 0.15) -> np.ndarray:
    """EMA 更新 client embedding，保持 L2 归一化。Phase 3 使用。"""
    updated = current * (1 - weight) + new * weight
    norm = float(np.linalg.norm(updated))
    if norm > 0:
        updated = updated / norm
    return updated


def detect_speaker_changes(
    seg_audio: np.ndarray,
    voiceprint: VoiceprintState,
    sr: int = SR,
    window_ms: int = 1500,
    step_ms: int = 500,
    delta_threshold: float = 0.25,
    lawyer_threshold: float = 0.40,
    margin: float = 0.10,
) -> list[int]:
    """检测 seg_audio 内的说话人切换点，返回毫秒切分位置列表（相对 seg_audio 起点）。"""
    # margin: used by Phase 3 dual comparison (implemented in next task)
    window_samples = int(sr * window_ms / 1000)
    step_samples = int(sr * step_ms / 1000)

    if len(seg_audio) < window_samples:
        return []

    embeddings: list[np.ndarray | None] = []
    window_starts_ms: list[int] = []

    for start in range(0, len(seg_audio) - window_samples + 1, step_samples):
        w = seg_audio[start : start + window_samples]
        energy = float(np.sqrt(np.mean(w.astype(np.float64) ** 2)))
        if energy < 0.001:
            embeddings.append(None)
        else:
            embeddings.append(extract_embedding(w, sr))
        window_starts_ms.append(int(start * 1000 / sr))

    n = len(embeddings)
    if n < 2:
        return []

    s_ls: list[float | None] = [None] * n
    for i, emb in enumerate(embeddings):
        if emb is not None:
            s_ls[i] = float(np.dot(emb, voiceprint.lawyer))

    changes_idx: list[int] = []
    prev_state: str | None = None
    prev_s: float | None = None
    seeded = voiceprint.client is not None

    for i in range(n):
        emb = embeddings[i]
        s_l = s_ls[i]
        if emb is None or s_l is None:
            continue

        if not seeded:
            cur_state = "lawyer" if s_l >= lawyer_threshold else "other"
        else:
            s_c = float(np.dot(emb, voiceprint.client))
            diff = s_l - s_c
            if diff > margin:
                cur_state = "lawyer"
            elif diff < -margin:
                cur_state = "client"
            else:
                cur_state = "uncertain"

        state_changed = prev_state is not None and prev_state != cur_state
        phase1_cross = (
            not seeded
            and prev_s is not None
            and abs(prev_s - s_l) > delta_threshold
            and (
                (prev_s >= lawyer_threshold and s_l < lawyer_threshold)
                or (prev_s < lawyer_threshold and s_l >= lawyer_threshold)
            )
        )
        phase3_cross = seeded and {prev_state, cur_state} == {"lawyer", "client"}

        if state_changed and phase1_cross:
            changes_idx.append(i)
            if prev_s > 0.50 and s_l < 0.20:
                voiceprint.client = emb.copy()
                seeded = True
        elif state_changed and phase3_cross:
            changes_idx.append(i)
            s_c = float(np.dot(emb, voiceprint.client))
            diff = s_l - s_c
            if diff < -0.30:
                voiceprint.client = _ema_update(voiceprint.client, emb, weight=0.15)

        if seeded and cur_state == "client" and prev_state == "client":
            s_c = float(np.dot(emb, voiceprint.client))
            diff = s_l - s_c
            if diff < -0.30:
                voiceprint.client = _ema_update(voiceprint.client, emb, weight=0.15)

        prev_state = cur_state
        prev_s = s_l

    result_ms: list[int] = []
    for idx in changes_idx:
        if idx == 0:
            continue
        split_ms = int(
            (window_starts_ms[idx - 1] + window_starts_ms[idx]) / 2 + window_ms / 2
        )
        result_ms.append(split_ms)

    if not result_ms:
        return []
    merged = [result_ms[0]]
    for cp in result_ms[1:]:
        if cp - merged[-1] < window_ms:
            continue
        merged.append(cp)
    return merged
