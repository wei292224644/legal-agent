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
    embedding: np.ndarray  # 律师 L2 归一化的 1D float32
    tau_high: float = 0.5
    tau_low: float = 0.3
    # Cycle 7: 双声纹自举。client_embedding 从对话流里第一个低相似度段提取,
    # 之后用相对差值判定。失败可回滚:删掉以下四字段 + matcher 双模式分支。
    client_embedding: np.ndarray | None = None
    margin: float = 0.10  # 双声纹相对差值判定边距
    seed_threshold: float = 0.50  # cos sim 低于此阈值的段被取为 client seed
    seed_min_duration_s: float = 3.0  # 短段不稳定,不作为 seed


def enroll_speaker(audio: np.ndarray, sr: int) -> Enrollment:
    """从注册音频产出 Enrollment。"""
    emb = extract_embedding(audio, sr)
    return Enrollment(embedding=emb)
