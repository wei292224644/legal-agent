"""声纹注册:输入律师注册音频,产出 Enrollment(embedding + 双阈值)。

τ_high / τ_low 用 cam++ 文献参考值起步;不达准确率时由 test_streaming_match_accuracy
反推校准。τ_high - τ_low 之间是 uncertain 中间带,跨说话人 utt 大概率落进这里。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from diarization.voiceprint import extract_embedding


@dataclass
class Enrollment:
    embedding: np.ndarray  # L2 归一化的 1D float32
    tau_high: float = 0.5
    tau_low: float = 0.3


def enroll_speaker(audio: np.ndarray, sr: int) -> Enrollment:
    """从注册音频产出 Enrollment。"""
    emb = extract_embedding(audio, sr)
    return Enrollment(embedding=emb)
