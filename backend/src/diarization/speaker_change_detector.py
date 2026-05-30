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
    """EMA 更新 client embedding，保持 L2 归一化。"""
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
    return []
