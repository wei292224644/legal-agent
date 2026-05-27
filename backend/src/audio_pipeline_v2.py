import asyncio
from dataclasses import dataclass
from typing import Callable

import numpy as np

# (audio: np.ndarray) -> (sentences, spk_embeddings)
# sentences: [{text, start_ms, end_ms, spk_id}]
# spk_embeddings: {spk_id: mean_embedding (192,)}
ModelFn = Callable[[np.ndarray], tuple[list[dict], dict[int, np.ndarray]]]


@dataclass
class TranscriptResult:
    text: str
    speaker: str  # "律师" | "客户" | "未知"


class AudioPipelineV2:
    def __init__(
        self,
        lawyer_voiceprint: np.ndarray | None = None,
        model_fn: ModelFn | None = None,
    ):
        self._lawyer_vp = lawyer_voiceprint
        self._model_fn = model_fn or self._build_model()
        self._spk_role_map: dict[int, str] = {}

    # ── Model builder ──────────────────────────────────────────────────────────

    def _build_model(self) -> ModelFn:
        import torch
        from funasr import AutoModel
        from funasr.models.campplus.cluster_backend import ClusterBackend
        from funasr.models.campplus.utils import sv_chunk, postprocess

        vad_model = AutoModel(model="fsmn-vad", hub="hf", disable_update=True)
        asr_model = AutoModel(
            model="paraformer-zh",
            punc_model="ct-punc",
            hub="hf",
            disable_update=True,
        )
        emb_model = AutoModel(model="cam++", hub="hf", disable_update=True)
        cluster = ClusterBackend()

        def run(audio: np.ndarray) -> tuple[list[dict], dict[int, np.ndarray]]:
            sr = 16000

            # Step 1: VAD
            vad_res = vad_model.generate(input=audio)
            if not vad_res:
                return [], {}
            segs_ms: list[list[int]] = vad_res[0].get("value", [])
            if not segs_ms:
                return [], {}

            # Step 2: sv_chunk — 1.5s 滑窗
            vad_segs = [
                [s[0] / 1000, s[1] / 1000, audio[int(s[0] * sr / 1000):int(s[1] * sr / 1000)]]
                for s in segs_ms
            ]
            chunks = sv_chunk(vad_segs, fs=sr)

            # Step 3: cam++ 批量推理（一次）
            emb_res = emb_model.generate(input=[c[2] for c in chunks])
            embeddings = np.stack([
                (r["spk_embedding"].numpy() if isinstance(r["spk_embedding"], torch.Tensor)
                 else np.array(r["spk_embedding"])).flatten()
                for r in emb_res
            ])

            # Step 4: 聚类，固定 2 人
            labels = cluster(embeddings, oracle_num=2)

            # Step 5: postprocess → [[start_s, end_s, spk_id], ...]
            spk_segments = postprocess(
                [[c[0], c[1]] for c in chunks], vad_segs, labels, embeddings
            )

            # Step 6: mean embedding per spk_id
            spk_embeddings: dict[int, np.ndarray] = {}
            for spk_id in sorted(set(int(s[2]) for s in spk_segments)):
                mask = labels == spk_id
                spk_embeddings[spk_id] = embeddings[mask].mean(axis=0)

            # Step 7: ASR per VAD segment + 按时间戳匹配 spk_id
            sentences = []
            for start_ms, end_ms in segs_ms:
                seg = audio[int(start_ms * sr / 1000):int(end_ms * sr / 1000)]
                if len(seg) < sr // 10:
                    continue
                asr_res = asr_model.generate(input=seg)
                if not (asr_res and asr_res[0].get("text", "").strip()):
                    continue
                mid_s = (start_ms + end_ms) / 2000
                spk_id = _find_speaker(mid_s, spk_segments)
                sentences.append({
                    "text": asr_res[0]["text"],
                    "start": start_ms,
                    "end": end_ms,
                    "spk_id": spk_id,
                })

            return sentences, spk_embeddings

        return run

    # ── Public API ─────────────────────────────────────────────────────────────

    async def process_segment(self, audio: np.ndarray) -> list[TranscriptResult]:
        loop = asyncio.get_event_loop()
        sentences, spk_embeddings = await loop.run_in_executor(None, self._model_fn, audio)
        for spk_id, emb in spk_embeddings.items():
            if spk_id not in self._spk_role_map:
                self._spk_role_map[spk_id] = self._compare_voiceprint(emb)
        return [
            TranscriptResult(
                text=s["text"],
                speaker=self._spk_role_map.get(s["spk_id"], "客户"),
            )
            for s in sentences
        ]

    # ── Internal ───────────────────────────────────────────────────────────────

    def _compare_voiceprint(self, embedding: np.ndarray) -> str:
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


def _find_speaker(mid_s: float, spk_segments: list) -> int:
    for seg in spk_segments:
        if seg[0] <= mid_s <= seg[1]:
            return int(seg[2])
    return int(spk_segments[-1][2])
