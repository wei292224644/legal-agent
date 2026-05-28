"""speaker 三态分类:lawyer / client / uncertain。

单声纹模式(client_embedding=None):
  cos sim ≥ τ_high → lawyer
  cos sim ≤ τ_low  → client
  其它              → uncertain

Cycle 7 双声纹自举:
  - 单声纹模式下,(tau_low, tau_high) 中间带的足够长段 + cos < seed_threshold
    时,把本段 embedding 写回 enrollment 作为 client seed,本段视为 client
  - 一旦 client_embedding 存在,切换为相对差值判定:
      s_l - s_c >  margin → lawyer
      s_l - s_c < -margin → client
      其它                 → uncertain

  失败可回滚:删 Enrollment.client_embedding/margin/seed_threshold + 这里的
  双声纹分支,行为退回单声纹纯阈值。
"""
from __future__ import annotations

from typing import Literal

import numpy as np

from diarization.enrollment import Enrollment
from diarization.voiceprint import extract_embedding

SpeakerLabel = Literal["lawyer", "client", "uncertain"]


def match_speaker(
    audio: np.ndarray,
    sr: int,
    enrollment: Enrollment,
) -> SpeakerLabel:
    """对单段音频判 speaker(三态)。可能写回 enrollment.client_embedding。"""
    emb = extract_embedding(audio, sr)
    s_l = float(np.dot(emb, enrollment.embedding))

    if enrollment.client_embedding is None:
        if s_l >= enrollment.tau_high:
            return "lawyer"
        if s_l <= enrollment.tau_low:
            return "client"
        # uncertain 区间: 时长足够且 cos 偏低 → 取为 client seed
        duration_s = len(audio) / sr
        if (
            duration_s >= enrollment.seed_min_duration_s
            and s_l < enrollment.seed_threshold
        ):
            enrollment.client_embedding = emb
            return "client"
        return "uncertain"

    s_c = float(np.dot(emb, enrollment.client_embedding))
    diff = s_l - s_c
    if diff > enrollment.margin:
        return "lawyer"
    if diff < -enrollment.margin:
        return "client"
    return "uncertain"
