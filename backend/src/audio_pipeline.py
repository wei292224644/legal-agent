import asyncio
from dataclasses import dataclass
from typing import Callable

import numpy as np

ModelFn = Callable[[np.ndarray], list[dict]]
EmbeddingFn = Callable[[np.ndarray], np.ndarray]


@dataclass
class TranscriptResult:
    text: str
    speaker: str  # "律师" | "客户" | "未知"


class AudioPipeline:
    def __init__(
        self,
        lawyer_voiceprint: np.ndarray | None = None,
    ):
        self._lawyer_vp = lawyer_voiceprint
        self._model = None
        self._emb_fn = None
        self._spk_role_map: dict[str, str] = {}  # spk_label → 律师/客户

    # ── Lazy init ─────────────────────────────────────────────────────────────

    def _ensure_model(self):
        if self._model is not None:
            return
        from funasr import AutoModel

        self._model = AutoModel(
            model="paraformer-zh",
            vad_model="fsmn-vad",
            punc_model="ct-punc",
            spk_model="cam++",
            disable_update=True,
        )
        self._model.vad_model.vad_opts.max_single_segment_time = 10000

    def _ensure_emb_fn(self):
        if self._emb_fn is not None or self._lawyer_vp is None:
            return
        import torch
        from funasr import AutoModel

        emb_model = AutoModel(model="cam++", hub="hf", disable_update=True)

        def get_embedding(audio: np.ndarray) -> np.ndarray:
            res = emb_model.generate(input=audio)
            emb = res[0]["spk_embedding"]
            arr = emb.numpy() if isinstance(emb, torch.Tensor) else np.array(emb)
            return arr.flatten()

        self._emb_fn = get_embedding

    # ── Public API ─────────────────────────────────────────────────────────────

    async def process_segment(self, audio: np.ndarray) -> list[TranscriptResult]:
        self._ensure_model()
        self._ensure_emb_fn()

        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(None, self._model.generate, audio)

        out: list[TranscriptResult] = []
        for r in results:
            text = r.get("text", "").strip()
            if not text:
                continue
            spk_label = r.get("spk", "未知")
            out.append(TranscriptResult(
                text=text,
                speaker=self._map_speaker(spk_label, audio, r),
            ))
        return out

    # ── Internal ───────────────────────────────────────────────────────────────

    def _map_speaker(self, label: str, full_audio: np.ndarray, result: dict) -> str:
        if self._lawyer_vp is None or self._emb_fn is None:
            return label  # no voiceprint → return raw label

        if label in self._spk_role_map:
            return self._spk_role_map[label]

        # Extract this segment's audio for embedding
        sr = 16000
        start_ms = result.get("start", 0)
        end_ms = result.get("end", len(full_audio) * 1000 // sr)
        seg = full_audio[int(start_ms * sr / 1000) : int(end_ms * sr / 1000)]
        if len(seg) < sr // 4:
            seg = full_audio

        embedding = self._emb_fn(seg)
        role = self._compare_voiceprint(embedding)
        self._spk_role_map[label] = role
        return role

    def _compare_voiceprint(self, embedding: np.ndarray) -> str:
        if self._lawyer_vp is None:
            return "客户"
        sim = float(
            np.dot(embedding, self._lawyer_vp)
            / (np.linalg.norm(embedding) * np.linalg.norm(self._lawyer_vp))
        )
        if sim > 0.85:
            return "律师"
        if sim < 0.50:
            return "客户"
        return "未知"
