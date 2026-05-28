"""FunASR 流式 STT 包装。

增量管线:
  - 每 300ms 新音频跑一次 fsmn-vad 对累积 buffer
  - 找"稳定关闭"的 utterance(end 之后已观测到 ≥ VAD_SILENCE_MS 静默)
  - 对每个新关闭的 utterance 跑 paraformer-zh,立即 yield
  - 流末尾 flush 剩余未关闭的(强制 final)

VAD / ASR 用 asyncio.to_thread 跑,不阻塞事件循环。
"""
from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator

import numpy as np
from funasr import AutoModel

from models.utterance import ClosedBy, Utterance
from diarization.enrollment import Enrollment
from diarization.matcher import match_speaker

SR = 16000
VAD_SILENCE_MS = 400
SOFT_CAP_MS = 8000

_vad_model: AutoModel | None = None
_asr_model: AutoModel | None = None


def _get_models() -> tuple[AutoModel, AutoModel]:
    global _vad_model, _asr_model
    if _vad_model is None:
        _vad_model = AutoModel(model="fsmn-vad", disable_update=True)
    if _asr_model is None:
        _asr_model = AutoModel(model="paraformer-zh", disable_update=True)
    return _vad_model, _asr_model


def _utt_id(t_start: float, text: str) -> str:
    seed = f"{t_start:.3f}-{text[:16]}"
    return "u_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8]


def _vad_segments_ms(vad_result) -> list[tuple[int, int]]:
    """从 fsmn-vad generate 输出抠出 [(start_ms, end_ms), ...]。"""
    if not vad_result:
        return []
    raw = vad_result[0].get("value", [])
    out: list[tuple[int, int]] = []
    for seg in raw:
        if len(seg) >= 2 and seg[0] >= 0 and seg[1] > seg[0]:
            out.append((int(seg[0]), int(seg[1])))
    return out


FRAME_MS = 30
MICROPAUSE_MS = 150
ENERGY_THRESHOLD_RATIO = 0.10


def _frame_energy(audio: np.ndarray, frame_ms: int = FRAME_MS) -> np.ndarray:
    """逐帧 RMS 能量。"""
    frame_samples = SR * frame_ms // 1000
    n = len(audio) // frame_samples
    if n == 0:
        return np.zeros(0, dtype=np.float32)
    trimmed = audio[: n * frame_samples].reshape(n, frame_samples)
    return np.sqrt(np.mean(trimmed.astype(np.float32) ** 2, axis=1))


def find_micropause(
    audio: np.ndarray,
    after_ms: int,
    min_silence_ms: int = MICROPAUSE_MS,
) -> tuple[int, int] | None:
    """在 audio(单段连续语音) 里找 after_ms 之后的第一处微停顿。

    Returns: (silence_start_ms, silence_end_ms) 相对 audio 起点;找不到返回 None。
    """
    energies = _frame_energy(audio)
    if len(energies) == 0:
        return None
    threshold = energies.max() * ENERGY_THRESHOLD_RATIO
    after_frame = after_ms // FRAME_MS
    needed_frames = min_silence_ms // FRAME_MS

    run_start: int | None = None
    for i in range(after_frame, len(energies)):
        if energies[i] < threshold:
            if run_start is None:
                run_start = i
            if i - run_start + 1 >= needed_frames:
                # 扩展到 run 末尾
                end = i
                while end + 1 < len(energies) and energies[end + 1] < threshold:
                    end += 1
                return (run_start * FRAME_MS, (end + 1) * FRAME_MS)
        else:
            run_start = None
    return None


def split_soft_cap(
    seg_start_ms: int,
    seg_end_ms: int,
    audio: np.ndarray,
    soft_cap_ms: int = SOFT_CAP_MS,
) -> list[tuple[int, int, ClosedBy]]:
    """对一段连续语音应用 soft cap:超过 soft_cap_ms 后在第一处微停顿切。"""
    out: list[tuple[int, int, ClosedBy]] = []
    cur = seg_start_ms
    while seg_end_ms - cur > soft_cap_ms:
        # 在 cur..seg_end_ms 这段 audio 里找 soft_cap_ms 之后的微停顿
        sub = audio[int(cur * SR / 1000) : int(seg_end_ms * SR / 1000)]
        mp = find_micropause(sub, after_ms=soft_cap_ms)
        if mp is None:
            break  # 没有微停顿,只能让 utterance 长下去
        mp_start, mp_end = mp
        out.append((cur, cur + mp_start, "soft_cap"))
        cur = cur + mp_end
    out.append((cur, seg_end_ms, "vad"))
    return out


def merge_with_close_reason(
    raw_segs: list[tuple[int, int]],
    audio: np.ndarray,
    vad_silence_ms: int = VAD_SILENCE_MS,
    soft_cap_ms: int = SOFT_CAP_MS,
) -> list[tuple[int, int, ClosedBy]]:
    """两阶段聚合:
    1) 把 fsmn-vad 段间 gap < vad_silence_ms 的合并(它们不算"VAD 关闭");
    2) 合并后对每个 utterance 应用 soft cap(在长段内部找微停顿)。
    """
    if not raw_segs:
        return []
    # Phase 1: merge close gaps
    merged: list[tuple[int, int]] = [raw_segs[0]]
    for s, e in raw_segs[1:]:
        if s - merged[-1][1] < vad_silence_ms:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))

    # Phase 2: soft cap within each merged segment
    result: list[tuple[int, int, ClosedBy]] = []
    for s, e in merged:
        if e - s <= soft_cap_ms:
            result.append((s, e, "vad"))
        else:
            result.extend(split_soft_cap(s, e, audio, soft_cap_ms))
    return result


VAD_RECHECK_INTERVAL_MS = 100


async def _asr_one(asr_model: AutoModel, seg_audio: np.ndarray) -> str:
    if len(seg_audio) < SR // 10:  # < 100ms,FunASR 不稳
        return ""
    asr_out = await asyncio.to_thread(asr_model.generate, input=seg_audio)
    if not asr_out:
        return ""
    return (asr_out[0].get("text") or "").strip()


async def _detect_and_transcribe(
    snapshot: np.ndarray,
    t0: float,
    yielded_until_ms: int,
    vad_model: AutoModel,
    asr_model: AutoModel,
    final: bool,
) -> tuple[list[Utterance], int]:
    """对 snapshot 跑 VAD + ASR,返回 (新 utterance 列表, 新的 yielded_until_ms)。

    无副作用:不修改外部状态,便于在 asyncio.create_task 中并发跑。
    """
    total_ms = int(len(snapshot) * 1000 / SR)
    vad_out = await asyncio.to_thread(vad_model.generate, input=snapshot)
    raw_segs = _vad_segments_ms(vad_out)
    bounds = merge_with_close_reason(raw_segs, snapshot)

    out: list[Utterance] = []
    new_until = yielded_until_ms
    for s_ms, e_ms, closed_by in bounds:
        if e_ms <= new_until + 100:
            continue
        if not final and total_ms - e_ms < VAD_SILENCE_MS:
            continue
        seg_audio = snapshot[int(s_ms * SR / 1000) : int(e_ms * SR / 1000)]
        text = await _asr_one(asr_model, seg_audio)
        if not text:
            continue
        t_start = t0 + s_ms / 1000.0
        t_end = t0 + e_ms / 1000.0
        out.append(
            Utterance(
                id=_utt_id(t_start, text),
                text=text,
                t_start=t_start,
                t_end=t_end,
                closed_by=closed_by,
            )
        )
        new_until = max(new_until, e_ms)
    return out, new_until


async def stream_stt(
    audio_chunks: AsyncIterator[tuple[np.ndarray, float]],
    enrollment: Enrollment | None = None,
) -> AsyncIterator[Utterance]:
    """消费音频块流,在 utterance 稳定关闭时产出 Utterance。

    优化:
      - VAD 短间隔(100ms)轮询,fsmn-vad RTF<<1 几乎免费
      - 一旦 VAD 报告一个 segment,就 **投机式启动 ASR**(asyncio task),
        与 1.5s 静默稳定性等待并行。稳定时 await cache,延迟 ≈ 0。
      - 投机 cache 按 (s_ms, e_ms) 索引;边界在不同 VAD 轮次的微抖动用 ±100ms 容忍
    """
    vad_model, asr_model = _get_models()

    pieces: list[np.ndarray] = []
    t0: float | None = None
    yielded_until_ms = 0
    last_vad_audio_ms = -VAD_RECHECK_INTERVAL_MS

    audio_buffer = np.zeros(0, dtype=np.float32)
    # 投机 ASR 缓存:(s_ms, e_ms) → Task[str]
    spec_asr: dict[tuple[int, int], asyncio.Task] = {}

    def _spec_key_match(
        s_ms: int, e_ms: int, tol_ms: int = 100
    ) -> tuple[int, int] | None:
        """已有 cache 中匹配 (s±tol, e±tol) 的键。"""
        for k_s, k_e in spec_asr:
            if abs(k_s - s_ms) <= tol_ms and abs(k_e - e_ms) <= tol_ms:
                return (k_s, k_e)
        return None

    async def _emit_stable_or_final(snapshot: np.ndarray, final: bool):
        nonlocal yielded_until_ms
        if len(snapshot) == 0:
            return
        total_ms = int(len(snapshot) * 1000 / SR)
        # 只对"未确认尾段"跑 VAD,避免 O(n²) 重复扫已 yield 的历史音频。
        # 留 500ms overlap 兜底边界抖动。
        window_start_ms = max(0, yielded_until_ms - 500)
        window_start_sample = int(window_start_ms * SR / 1000)
        window_audio = snapshot[window_start_sample:]
        vad_out = await asyncio.to_thread(vad_model.generate, input=window_audio)
        raw_segs_rel = _vad_segments_ms(vad_out)
        # 把相对窗口的时间戳翻译回绝对时间轴
        raw_segs = [(s + window_start_ms, e + window_start_ms) for s, e in raw_segs_rel]
        bounds = merge_with_close_reason(raw_segs, snapshot)

        for s_ms, e_ms, closed_by in bounds:
            if e_ms <= yielded_until_ms + 100:
                continue
            # 钳制起点到已 yield 边界,避免 windowed VAD 的 500ms overlap
            # 让新 utterance 倒回到上段尾部、把同一段音频再次转录
            s_ms = max(s_ms, yielded_until_ms)
            # 只在已观测到至少 200ms 静默后才启动投机 ASR——否则 e_ms 还在
            # 随说话延伸,每次都创建新 cache 项,会把线程池堵死
            silence_after_ms = total_ms - e_ms
            ready_to_spec = silence_after_ms >= 200 or final or closed_by == "soft_cap"
            if not ready_to_spec:
                continue

            matched_key = _spec_key_match(s_ms, e_ms)
            if matched_key is None:
                seg_audio = snapshot[
                    int(s_ms * SR / 1000) : int(e_ms * SR / 1000)
                ].copy()
                spec_asr[(s_ms, e_ms)] = asyncio.create_task(
                    _asr_one(asr_model, seg_audio)
                )
                matched_key = (s_ms, e_ms)

            # soft_cap 立即 yield(不等 silence)——切分点已经由能量微停顿确定,
            # 等静默无意义。vad 关闭需等 silence 满 VAD_SILENCE_MS。
            stable = (
                final
                or closed_by == "soft_cap"
                or (silence_after_ms >= VAD_SILENCE_MS)
            )
            if not stable:
                continue

            text = await spec_asr[matched_key]
            # 清理已 yield 的 cache 项(以及小于 e_ms 的陈旧 spec)
            for k in list(spec_asr.keys()):
                if k[1] <= e_ms + 100:
                    spec_asr.pop(k, None)

            if not text:
                continue
            t_start = (t0 or 0.0) + s_ms / 1000.0
            t_end = (t0 or 0.0) + e_ms / 1000.0
            speaker = None
            if enrollment is not None:
                speaker_audio = snapshot[
                    int(s_ms * SR / 1000) : int(e_ms * SR / 1000)
                ].copy()  # 跟 spec_asr 的 seg_audio 一致,防御后续并发改写
                speaker = await asyncio.to_thread(
                    match_speaker, speaker_audio, SR, enrollment
                )
            yield Utterance(
                id=_utt_id(t_start, text),
                text=text,
                t_start=t_start,
                t_end=t_end,
                speaker=speaker,
                closed_by=closed_by,
            )
            yielded_until_ms = max(yielded_until_ms, e_ms)

    async for chunk, t_rel in audio_chunks:
        if t0 is None:
            t0 = t_rel
        pieces.append(chunk)
        audio_buffer = np.concatenate(pieces).astype(np.float32)
        total_ms = int(len(audio_buffer) * 1000 / SR)

        if total_ms - last_vad_audio_ms < VAD_RECHECK_INTERVAL_MS:
            continue
        last_vad_audio_ms = total_ms

        async for utt in _emit_stable_or_final(audio_buffer, final=False):
            yield utt

    # 流末尾 flush
    async for utt in _emit_stable_or_final(audio_buffer, final=True):
        yield utt

    # 取消未消费的 spec task(避免资源泄漏)
    for task in spec_asr.values():
        if not task.done():
            task.cancel()
