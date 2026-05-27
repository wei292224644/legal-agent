import numpy as np
import pytest
from audio_pipeline import AudioPipeline


def make_pipeline(lawyer_vp=None, sentences=None, embedding_results=None):
    """
    sentences: list of {text, start, end}  — matches real funASR sentence_info shape
    embedding_results: list of np.ndarray, one per sentence (returned in order)
    """
    def model_fn(_audio):
        return sentences or []

    if embedding_results is not None:
        call_iter = iter(embedding_results)
        embedding_fn = lambda _seg: next(call_iter)
    else:
        embedding_fn = None

    return AudioPipeline(
        lawyer_voiceprint=lawyer_vp,
        model_fn=model_fn,
        embedding_fn=embedding_fn,
    )


# ── Tracer bullet ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_process_segment_extracts_text():
    pipeline = make_pipeline(sentences=[{"text": "您好", "start": 0, "end": 1000}])
    results = await pipeline.process_segment(np.zeros(16000))
    assert len(results) == 1
    assert results[0].text == "您好"


# ── Speaker identification ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_voiceprint_defaults_to_client():
    pipeline = make_pipeline(
        lawyer_vp=None,
        sentences=[{"text": "我想咨询", "start": 0, "end": 1000}],
    )
    results = await pipeline.process_segment(np.zeros(16000))
    assert results[0].speaker == "客户"


@pytest.mark.asyncio
async def test_high_similarity_identified_as_lawyer():
    lawyer_vp = np.array([1.0, 0.0, 0.0])
    pipeline = make_pipeline(
        lawyer_vp=lawyer_vp,
        sentences=[{"text": "根据劳动法", "start": 0, "end": 1000}],
        embedding_results=[np.array([0.99, 0.1, 0.0])],
    )
    results = await pipeline.process_segment(np.zeros(16000))
    assert results[0].speaker == "律师"


@pytest.mark.asyncio
async def test_low_similarity_identified_as_client():
    lawyer_vp = np.array([1.0, 0.0, 0.0])
    pipeline = make_pipeline(
        lawyer_vp=lawyer_vp,
        sentences=[{"text": "我没有签合同", "start": 0, "end": 1000}],
        embedding_results=[np.array([0.0, 1.0, 0.0])],
    )
    results = await pipeline.process_segment(np.zeros(16000))
    assert results[0].speaker == "客户"


@pytest.mark.asyncio
async def test_middle_similarity_marked_unknown():
    lawyer_vp = np.array([1.0, 0.0, 0.0])
    # sim ≈ 0.707, between 0.50 and 0.85
    pipeline = make_pipeline(
        lawyer_vp=lawyer_vp,
        sentences=[{"text": "嗯", "start": 0, "end": 500}],
        embedding_results=[np.array([1.0, 1.0, 0.0])],
    )
    results = await pipeline.process_segment(np.zeros(16000))
    assert results[0].speaker == "未知"


@pytest.mark.asyncio
async def test_same_timestamps_reuses_cached_role():
    lawyer_vp = np.array([1.0, 0.0, 0.0])
    call_count = 0

    def counting_embed(_seg):
        nonlocal call_count
        call_count += 1
        return np.array([0.99, 0.1, 0.0])  # → 律师

    pipeline = AudioPipeline(
        lawyer_voiceprint=lawyer_vp,
        model_fn=lambda _: [
            {"text": "第一句", "start": 0,    "end": 1000},
            {"text": "第二句", "start": 0,    "end": 1000},  # same timestamps → cache hit
        ],
        embedding_fn=counting_embed,
    )
    results = await pipeline.process_segment(np.zeros(16000))
    assert results[0].speaker == "律师"
    assert results[1].speaker == "律师"
    assert call_count == 1  # second sentence served from cache
