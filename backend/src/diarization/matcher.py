"""speaker 三态分类:lawyer / client / uncertain。

cos sim ≥ τ_high → lawyer
cos sim ≤ τ_low  → client
其它              → uncertain(典型情形:跨说话人 utt,embedding 落在两人之间)
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
    """对单段音频判 speaker(三态)。"""
    emb = extract_embedding(audio, sr)
    s = float(np.dot(emb, enrollment.embedding))
    if s >= enrollment.tau_high:
        return "lawyer"
    if s <= enrollment.tau_low:
        return "client"
    return "uncertain"
