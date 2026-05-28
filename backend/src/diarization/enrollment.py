"""声纹注册:输入律师注册音频,产出 Enrollment(embedding + 阈值)。

最小实现 (Cycle 6a):只提整段 embedding,阈值留默认。Cycle 6b 整段对话
测试会驱动出 τ_high 自校准 / 长度筛选 等细化逻辑。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from diarization.voiceprint import extract_embedding


@dataclass
class Enrollment:
    embedding: np.ndarray  # L2 归一化的 1D float32
    tau_high: float = 0.5
    tau_low: float = 0.5


def enroll_speaker(audio: np.ndarray, sr: int) -> Enrollment:
    """从注册音频产出 Enrollment。"""
    emb = extract_embedding(audio, sr)
    return Enrollment(embedding=emb)
