"""cam++ 声纹 embedding 提取。

模块单例 AutoModel,L2 归一化的 1D float32 输出,供下游做余弦相似度比对。
"""

from __future__ import annotations

import threading

import numpy as np
import torch
import torchaudio.functional as torchaudio_f
from funasr import AutoModel

from config import SR as CAMPP_SR

_model: AutoModel | None = None
_model_lock = threading.Lock()


def _get_model() -> AutoModel:
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                _model = AutoModel(model="cam++", hub="ms", disable_update=True)
    return _model


def extract_embedding(audio: np.ndarray, sr: int = 16000) -> np.ndarray:
    """对单段音频提 cam++ embedding,返回 L2 归一化后的 1D float32 向量。

    任意采样率输入,内部重采样到 16kHz(cam++ 训练采样率)。

    Args:
        audio: 单通道 PCM,float32 [-1, 1]
        sr: 输入采样率

    Returns:
        L2 归一化后的 1D float32 embedding(典型 192 维)
    """
    if sr != CAMPP_SR:
        x = torch.from_numpy(np.ascontiguousarray(audio, dtype=np.float32))
        audio = torchaudio_f.resample(x, sr, CAMPP_SR).numpy()

    result = _get_model().generate(input=audio)
    raw = result[0]["spk_embedding"]
    arr = raw.cpu().numpy() if isinstance(raw, torch.Tensor) else np.asarray(raw)
    emb = arr.astype(np.float32).flatten()
    norm = float(np.linalg.norm(emb))
    if norm > 0:
        emb = emb / norm
    return emb
