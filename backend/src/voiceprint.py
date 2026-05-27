import numpy as np
from pathlib import Path
from typing import Callable

VOICEPRINTS_DIR = Path("voiceprints")

EmbeddingFn = Callable[[bytes], np.ndarray]


def _default_embed_fn(audio_bytes: bytes) -> np.ndarray:
    import io
    import torch
    import soundfile as sf
    from funasr import AutoModel

    model = AutoModel(model="cam++", hub="hf", disable_update=True)
    audio, _ = sf.read(io.BytesIO(audio_bytes))
    res = model.generate(input=audio)
    emb = res[0]["spk_embedding"]
    arr = emb.numpy() if isinstance(emb, torch.Tensor) else np.array(emb)
    return arr.flatten()   # (1, 192) → (192,)


def register(audio_bytes: bytes, session_id: str, embed_fn: EmbeddingFn = None) -> None:
    if embed_fn is None:
        embed_fn = _default_embed_fn
    embedding = embed_fn(audio_bytes)
    VOICEPRINTS_DIR.mkdir(parents=True, exist_ok=True)
    np.save(VOICEPRINTS_DIR / f"{session_id}.npy", embedding)


def load(session_id: str) -> np.ndarray | None:
    path = VOICEPRINTS_DIR / f"{session_id}.npy"
    if not path.exists():
        return None
    return np.load(path)


def compare(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))
