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
        model_fn: ModelFn | None = None,
        embedding_fn: EmbeddingFn | None = None,
    ):
        # Streaming state — for process_segment
        self._vad_model = None
        self._asr_model = None
        self._vad_cache: dict = {}
        self._vad_pending_start: int | None = None
        self._audio_buffer: list[np.ndarray] = []
        self._returned_ends: set[int] = set()  # dedup by segment end_ms

        self._lawyer_vp = lawyer_voiceprint
        self._model_fn = model_fn or self._build_model()
        self._embedding_fn = embedding_fn or (
            self._build_embedding_fn() if lawyer_voiceprint is not None else None
        )
        self._embedding_cache: dict[str, str] = {}

    # ── Model builders ───────────────────────────────────────────────────────────

    def _build_model(self) -> ModelFn:
        from funasr import AutoModel

        self._ensure_models()

        def run(audio: np.ndarray) -> list[dict]:
            sr = 16000
            vad_res = self._vad_model.generate(input=audio)
            if not vad_res:
                return []
            segs_ms: list[list[int]] = vad_res[0].get("value", [])
            if not segs_ms:
                return []

            results: list[dict] = []
            for start_ms, end_ms in segs_ms:
                seg = audio[int(start_ms * sr / 1000) : int(end_ms * sr / 1000)]
                if len(seg) < sr // 10:
                    continue
                asr_res = self._asr_model.generate(input=seg)
                if asr_res and asr_res[0].get("text", "").strip():
                    results.append({
                        "text": asr_res[0]["text"],
                        "start": start_ms,
                        "end": end_ms,
                    })
            return results

        return run

    def _build_embedding_fn(self) -> EmbeddingFn:
        import torch
        from funasr import AutoModel

        emb_model = AutoModel(model="cam++", hub="hf", disable_update=True)

        def get_embedding(audio: np.ndarray) -> np.ndarray:
            res = emb_model.generate(input=audio)
            emb = res[0]["spk_embedding"]
            arr = emb.numpy() if isinstance(emb, torch.Tensor) else np.array(emb)
            return arr.flatten()

        return get_embedding

    def _ensure_models(self):
        if self._vad_model is not None:
            return
        from funasr import AutoModel

        self._vad_model = AutoModel(
            model="fsmn-vad", hub="hf", disable_update=True,
        )
        self._vad_model.model.vad_opts.max_single_segment_time = 10000

        self._asr_model = AutoModel(
            model="paraformer-zh", punc_model="ct-punc",
            hub="hf", disable_update=True,
        )

    # ── Public API ─────────────────────────────────────────────────────────────

    async def process_segment(self, audio: np.ndarray) -> list[TranscriptResult]:
        """Feed audio chunk. Accumulates audio; runs VAD → ASR → voiceprint
        on the full buffer. Returns new sentences (dedup by end timestamp).
        """
        self._ensure_models()
        sr = 16000
        self._audio_buffer.append(audio)
        full_audio = np.concatenate(self._audio_buffer)

        # VAD
        vad_res = self._vad_model.generate(input=full_audio)
        if not vad_res:
            return []
        segs_ms: list[list[int]] = vad_res[0].get("value", [])
        if not segs_ms:
            return []

        # ASR on new segments only
        results: list[TranscriptResult] = []
        for start_ms, end_ms in segs_ms:
            if end_ms in self._returned_ends:
                continue
            self._returned_ends.add(end_ms)

            seg = full_audio[int(start_ms * sr / 1000) : int(end_ms * sr / 1000)]
            if len(seg) < sr // 10:
                continue
            asr_res = self._asr_model.generate(input=seg)
            if not (asr_res and asr_res[0].get("text", "").strip()):
                continue

            speaker = self._identify_role(seg)
            results.append(TranscriptResult(text=asr_res[0]["text"], speaker=speaker))

        return results

    # ── Internal ───────────────────────────────────────────────────────────────

    def _identify_role(self, audio: np.ndarray) -> str:
        if self._embedding_fn is None or len(audio) < 4000:
            return "客户"
        embedding = self._embedding_fn(audio)
        return self._compare_voiceprint(embedding)

    def _compare_voiceprint(self, embedding: np.ndarray | None) -> str:
        if self._lawyer_vp is None or embedding is None:
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
