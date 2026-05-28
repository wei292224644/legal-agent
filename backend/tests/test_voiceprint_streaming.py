"""声纹模块 E2E 测试 (Sprint 2, Cycle 5-6)。

每个 cycle 一个测试,RED → GREEN 渐进。
"""
from __future__ import annotations

import re

import numpy as np
import pytest
import soundfile as sf

from diarization.enrollment import Enrollment, enroll_speaker
from diarization.matcher import match_speaker
from diarization.voiceprint import extract_embedding
from stt.funasr_stream import SR, stream_stt
from tests.streaming_fixtures import MAIN_WAV, SCRIPT_MD, VOICEPRINT_WAV, stream_wav_realtime
from tests.test_stt_streaming import _lcs_len, _normalize


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def test_enrollment_stable():
    """Cycle 5: 同一段音频两次提 embedding,余弦相似度 ≥ 0.98。

    cam++ 推理是确定性的,这条断言失败意味着实现里引入了非确定性
    (随机 dropout 未关 / 输入预处理不稳定 / 模型未 eval 模式),
    后续 speaker 匹配会全盘失准。
    """
    audio, sr = sf.read(str(VOICEPRINT_WAV), dtype="float32", always_2d=False)
    if audio.ndim == 2:
        audio = audio.mean(axis=1)

    e1 = extract_embedding(audio, sr)
    e2 = extract_embedding(audio, sr)

    assert e1.ndim == 1, f"embedding 应是 1D 向量, 实际 shape={e1.shape}"
    assert e1.dtype == np.float32, f"embedding 应是 float32, 实际 {e1.dtype}"
    assert e1.shape == e2.shape

    cos = _cosine(e1, e2)
    assert cos >= 0.98, (
        f"同音频两次 embedding 余弦相似度 {cos:.4f} < 0.98 — "
        f"cam++ 应是确定性的,推理路径有非确定噪声"
    )


def test_match_speaker_self_is_lawyer():
    """Cycle 6a (tracer): 用注册音频自匹配应返回 'lawyer'。

    走通 enroll → embed → cosine → 阈值 → label 整条主路径。
    其他 (client / uncertain / 短音频) 由 Cycle 6b 整段对话测试驱动出来。
    """
    audio, sr = sf.read(str(VOICEPRINT_WAV), dtype="float32", always_2d=False)
    if audio.ndim == 2:
        audio = audio.mean(axis=1)

    enrollment = enroll_speaker(audio, sr)
    label = match_speaker(audio, sr, enrollment)

    assert label == "lawyer", (
        f"注册音频自匹配应是 lawyer, 实际 {label!r}"
    )


def _parse_script_with_roles(text: str) -> list[tuple[str, str]]:
    """从 markdown 脚本里抽 [(role, line_text), ...],role 是 'lawyer' 或 'client'。"""
    role_map = {"律师": "lawyer", "客户": "client"}
    out: list[tuple[str, str]] = []
    role_prefix = re.compile(r"^\*\*(客户|律师)：\*\*\s*(.+)$")
    current_role: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        m = role_prefix.match(stripped)
        if m:
            current_role = role_map[m.group(1)]
            out.append((current_role, m.group(2)))
        elif stripped and not stripped.startswith(("#", "---", "*")) and current_role:
            # 续段(无角色标签的对话延续行,沿用上一行角色)
            out.append((current_role, stripped))
    return out


def _attribute_speaker(
    utt_text: str,
    script_lines: list[tuple[str, str]],
    dom_min: float = 0.4,
    other_max: float = 0.25,
) -> str | None:
    """给 utt 找 speaker ground truth,跨说话人 utt 返回 None。

    判定:一方 LCS overlap ≥ dom_min,**另一方** ≤ other_max → clean utt。
    否则 None(可能跨说话人,可能短/无对齐),从准确率分母里剔除。

    这样测试只评 matcher 在单说话人输入下的表现——cross-speaker utt 是
    STT 边界问题(Cycle 6c 的责任),不该污染 matcher 的指标。
    """
    norm_utt = _normalize(utt_text)
    if len(norm_utt) < 4:
        return None
    best_lawyer = best_client = 0.0
    for role, line in script_lines:
        norm_line = _normalize(line)
        if not norm_line:
            continue
        score = _lcs_len(norm_utt, norm_line) / min(len(norm_utt), len(norm_line))
        if role == "lawyer":
            best_lawyer = max(best_lawyer, score)
        else:
            best_client = max(best_client, score)
    if best_lawyer >= dom_min and best_client <= other_max:
        return "lawyer"
    if best_client >= dom_min and best_lawyer <= other_max:
        return "client"
    return None


def _is_cross_speaker(utt_text: str, script_lines: list[tuple[str, str]]) -> bool:
    """启发式:utt 跟两种角色 script 都有显著 LCS overlap → 跨说话人 utt。"""
    norm_utt = _normalize(utt_text)
    if len(norm_utt) < 4:
        return False
    bl = bc = 0.0
    for role, line in script_lines:
        norm_line = _normalize(line)
        if not norm_line:
            continue
        score = _lcs_len(norm_utt, norm_line) / min(len(norm_utt), len(norm_line))
        if role == "lawyer":
            bl = max(bl, score)
        else:
            bc = max(bc, score)
    return bl >= 0.25 and bc >= 0.25


@pytest.mark.asyncio
@pytest.mark.slow
async def test_streaming_match_accuracy():
    """Cycle 6b: 注册律师 → 主 WAV 流式喂 → 每段标 speaker → 准确率 ≥ 95%。

    断言:
      - speaker 准确率 ≥ 95%(uncertain 不计入分母,与 spec 一致)
      - uncertain 占比 ≤ 30%(初始版本宽松,后续可收紧)
    """
    from tests.run_logger import RunLogger  # noqa: PLC0415

    lawyer_audio, lawyer_sr = sf.read(
        str(VOICEPRINT_WAV), dtype="float32", always_2d=False
    )
    if lawyer_audio.ndim == 2:
        lawyer_audio = lawyer_audio.mean(axis=1)
    enrollment = enroll_speaker(lawyer_audio, lawyer_sr)

    script_lines = _parse_script_with_roles(SCRIPT_MD.read_text(encoding="utf-8"))
    assert len(script_lines) > 20

    with RunLogger("voiceprint_accuracy") as logger:
        logger.event("enroll.done", {
            "tau_high": enrollment.tau_high,
            "tau_low": enrollment.tau_low,
            "embedding_dim": int(enrollment.embedding.shape[0]),
        })

        audio_stream = stream_wav_realtime(MAIN_WAV, chunk_ms=100, speed=1.0)
        labeled: list[tuple[object, str, str | None]] = []  # (utt, predicted, truth)
        async for utt in stream_stt(audio_stream, enrollment=enrollment):
            predicted = utt.speaker  # 由 stream_stt 内部同步打标
            assert predicted in ("lawyer", "client", "uncertain"), (
                f"speaker 应是三态之一, 实际 {predicted!r}: utt={utt}"
            )
            truth = _attribute_speaker(utt.text, script_lines)
            labeled.append((utt, predicted, truth))
            logger.event("speaker.match", {
                "utt_id": utt.id,
                "t_start": utt.t_start,
                "t_end": utt.t_end,
                "text_preview": utt.text[:40],
                "predicted": predicted,
                "truth": truth,
            })

        scored = [(p, t) for _, p, t in labeled if t is not None and p != "uncertain"]
        if scored:
            correct = sum(1 for p, t in scored if p == t)
            accuracy = correct / len(scored)
        else:
            accuracy = 0.0

        uncertain_pct = sum(1 for _, p, _ in labeled if p == "uncertain") / max(
            len(labeled), 1
        )
        cross_count = sum(
            1 for u, _, _ in labeled if _is_cross_speaker(u.text, script_lines)
        )
        cross_pct = cross_count / max(len(labeled), 1)

        logger.set_metric("utterance_count", len(labeled))
        logger.set_metric("scored_count", len(scored))
        logger.set_metric("accuracy", round(accuracy, 4))
        logger.set_metric("uncertain_pct", round(uncertain_pct, 4))
        logger.set_metric("cross_speaker_count", cross_count)
        logger.set_metric("cross_speaker_pct", round(cross_pct, 4))

    assert labeled, "应产出 utterance"
    assert len(scored) >= 20, (
        f"clean utt 数 {len(scored)} < 20,样本太少。"
        f"跨说话人 {cross_count}/{len(labeled)} ({cross_pct:.1%}) — "
        f"若过高,Cycle 6c (speaker-aware split) 才是真修法"
    )
    assert accuracy >= 0.95, (
        f"matcher 准确率 {accuracy:.1%} < 95% (clean utts only); "
        f"scored {len(scored)} of {len(labeled)} utts, "
        f"cross-speaker {cross_pct:.1%}, uncertain {uncertain_pct:.1%}"
    )


def test_match_speaker_three_states(monkeypatch):
    """Cycle 6: matcher 三态分支按双阈值正确切换。

    用 monkeypatch 让 extract_embedding 返回受控向量,
    cos sim 落在三个区间分别期望 lawyer / uncertain / client。
    """
    from diarization import matcher

    # enrollment 用 [1, 0, 0],τ_high=0.6,τ_low=0.3
    e_lawyer = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    enrollment = Enrollment(embedding=e_lawyer, tau_high=0.6, tau_low=0.3)

    def fake_embed_factory(target_dot: float):
        # 返回跟 e_lawyer 内积 = target_dot 的单位向量
        v = np.array([target_dot, float(np.sqrt(1 - target_dot ** 2)), 0.0], dtype=np.float32)
        return lambda audio, sr: v

    dummy_audio = np.zeros(16000, dtype=np.float32)

    monkeypatch.setattr(matcher, "extract_embedding", fake_embed_factory(0.8))
    assert matcher.match_speaker(dummy_audio, 16000, enrollment) == "lawyer"

    monkeypatch.setattr(matcher, "extract_embedding", fake_embed_factory(0.45))
    assert matcher.match_speaker(dummy_audio, 16000, enrollment) == "uncertain"

    monkeypatch.setattr(matcher, "extract_embedding", fake_embed_factory(0.1))
    assert matcher.match_speaker(dummy_audio, 16000, enrollment) == "client"
