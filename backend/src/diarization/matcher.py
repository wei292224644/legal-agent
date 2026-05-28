"""speaker 三态分类:lawyer / client / uncertain。

最小实现 (Cycle 6a):cos sim ≥ τ_high → lawyer,否则 client。
Cycle 6b 集成测试 < 95% 时驱动出 uncertain 中间带 + 短音频跳过。
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
    """对单段音频判 speaker。"""
    emb = extract_embedding(audio, sr)
    s = float(np.dot(emb, enrollment.embedding))
    if s >= enrollment.tau_high:
        return "lawyer"
    return "client"
