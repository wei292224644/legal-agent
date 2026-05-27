import asyncio
from dataclasses import dataclass
from typing import Callable

import numpy as np

# (audio: np.ndarray) -> list[{text, start, end}]  — ASR + VAD, no spk_model
ModelFn = Callable[[np.ndarray], list[dict]]
# (audio segment: np.ndarray) -> np.ndarray  — standalone cam++ per sentence
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
        self._lawyer_vp = lawyer_voiceprint
        self._model_fn = model_fn or self._build_model()
        self._embedding_fn = embedding_fn or (
            self._build_embedding_fn() if lawyer_voiceprint is not None else None
        )
        self._embedding_cache: dict[str, str] = {}

    # ── Model builders ───────────────────────────────────────────────────────────

    def _build_model(self) -> ModelFn:
        from funasr import AutoModel

        # Streaming VAD with forced max segment duration to bound latency.
        # fsmn-vad waits for silence to cut segments, but continuous speech
        # has no silence — max_single_segment_time forces a cut every 10s.
        vad_model = AutoModel(
            model="fsmn-vad",
            hub="hf",
            disable_update=True,
        )
        vad_model.model.vad_opts.max_single_segment_time = 10000  # 10s hard cap

        asr_model = AutoModel(
            model="paraformer-zh",
            punc_model="ct-punc",
            hub="hf",
            disable_update=True,
        )

        def run(audio: np.ndarray) -> list[dict]:
            sr = 16000
            chunk_size = 200  # ms
            chunk_stride = int(chunk_size * sr / 1000)
            total_chunks = int((len(audio) - 1) / chunk_stride + 1)
            cache: dict = {}
            segments: list[list[int]] = []  # collected complete [[start_ms, end_ms], ...]
            pending_start: int | None = None

            for i in range(total_chunks):
                chunk = audio[i * chunk_stride : (i + 1) * chunk_stride]
                is_final = (i == total_chunks - 1)
                res = vad_model.generate(
                    input=chunk,
                    cache=cache,
                    is_final=is_final,
                    chunk_size=chunk_size,
                    disable_pbar=True,
                )
                values: list = res[0].get("value", [])
                for v in values:
                    if not isinstance(v, list) or len(v) != 2:
                        continue
                    start_ms, end_ms = int(v[0]), int(v[1])
                    if end_ms == -1:
                        # speech start, hold until end arrives
                        pending_start = start_ms
                    elif start_ms == -1:
                        # speech end, pair with pending start
                        if pending_start is not None:
                            segments.append([pending_start, end_ms])
                            pending_start = None
                    else:
                        # complete segment delivered at once
                        segments.append([start_ms, end_ms])

            # ASR + punctuation on each complete segment
            results: list[dict] = []
            for start_ms, end_ms in segments:
                seg = audio[int(start_ms * sr / 1000) : int(end_ms * sr / 1000)]
                if len(seg) < sr // 10:  # < 100ms, skip noise
                    continue
                asr_res = asr_model.generate(input=seg)
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
            return arr.flatten()  # (1, 192) → (192,)

        return get_embedding

    # ── Public API ─────────────────────────────────────────────────────────────

    async def process_segment(self, audio: np.ndarray) -> list[TranscriptResult]:
        loop = asyncio.get_event_loop()
        sentences = await loop.run_in_executor(None, self._model_fn, audio)
        return [self._to_result(s, audio) for s in sentences]

    # ── Internal ───────────────────────────────────────────────────────────────

    def _to_result(self, sentence: dict, full_audio: np.ndarray) -> TranscriptResult:
        speaker = self._identify_role(sentence, full_audio)
        return TranscriptResult(text=sentence["text"], speaker=speaker)

    def _identify_role(self, sentence: dict, full_audio: np.ndarray) -> str:
        if self._embedding_fn is None:
            return "客户"

        start_ms = sentence.get("start", 0)
        end_ms = sentence.get("end", len(full_audio) // 16)
        sr = 16000
        seg = full_audio[int(start_ms * sr / 1000) : int(end_ms * sr / 1000)]
        if len(seg) < sr // 4:  # < 250ms — too short to embed reliably
            seg = full_audio

        cache_key = f"{start_ms}-{end_ms}"
        if cache_key in self._embedding_cache:
            return self._embedding_cache[cache_key]

        embedding = self._embedding_fn(seg)
        role = self._compare_voiceprint(embedding)
        self._embedding_cache[cache_key] = role
        return role

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
