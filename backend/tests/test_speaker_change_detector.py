"""Speaker Change Detector 单元测试。

所有测试 mock extract_embedding，避免加载 cam++ 模型。
"""

from __future__ import annotations

import numpy as np
import pytest

from diarization.speaker_change_detector import VoiceprintState, detect_speaker_changes


@pytest.fixture
def lawyer_emb() -> np.ndarray:
    return np.array([1.0, 0.0, 0.0], dtype=np.float32)


@pytest.fixture
def client_emb() -> np.ndarray:
    return np.array([0.0, 1.0, 0.0], dtype=np.float32)


def _make_fake_extractor(sequence: list[np.ndarray]):
    """按顺序返回 embedding 的 mock 工厂。"""
    idx = 0

    def fake_extract(audio: np.ndarray, sr: int) -> np.ndarray:
        nonlocal idx
        emb = sequence[idx]
        idx += 1
        return emb

    return fake_extract


def test_phase1_detects_lawyer_to_nonlawyer(monkeypatch, lawyer_emb):
    """阶段1：律师→非律师切换应被检测。"""
    from diarization import speaker_change_detector as scd

    nonlawyer = np.array([0.0, 0.0, 1.0], dtype=np.float32)
    fake = _make_fake_extractor([lawyer_emb, lawyer_emb, nonlawyer, nonlawyer])
    monkeypatch.setattr(scd, "extract_embedding", fake)

    seg = np.full(16000 * 4, 0.01, dtype=np.float32)
    vp = VoiceprintState(lawyer=lawyer_emb)
    changes = detect_speaker_changes(seg, vp, sr=16000, window_ms=1000, step_ms=1000)

    assert len(changes) == 1
    assert changes[0] == 2000


def test_phase1_no_false_positive(monkeypatch, lawyer_emb):
    """阶段1：无跳变时不应误报切换。"""
    from diarization import speaker_change_detector as scd

    fake = _make_fake_extractor([lawyer_emb, lawyer_emb, lawyer_emb])
    monkeypatch.setattr(scd, "extract_embedding", fake)

    seg = np.full(16000 * 3, 0.01, dtype=np.float32)
    vp = VoiceprintState(lawyer=lawyer_emb)
    changes = detect_speaker_changes(seg, vp, sr=16000, window_ms=1000, step_ms=1000)
    assert changes == []


def test_short_segment_returns_empty(monkeypatch, lawyer_emb):
    """短于 window_ms 的段直接返回空。"""
    from diarization import speaker_change_detector as scd

    fake = _make_fake_extractor([lawyer_emb])
    monkeypatch.setattr(scd, "extract_embedding", fake)

    seg = np.full(16000 * 1, 0.01, dtype=np.float32)
    vp = VoiceprintState(lawyer=lawyer_emb)
    changes = detect_speaker_changes(seg, vp, sr=16000, window_ms=1500, step_ms=500)
    assert changes == []


def test_energy_gate_skips_silent_window(monkeypatch, lawyer_emb):
    """能量 < 0.001 的静默窗口被跳过，不调用 extract_embedding。"""
    from diarization import speaker_change_detector as scd

    call_count = 0
    def counting_extract(audio, sr):
        nonlocal call_count
        call_count += 1
        return lawyer_emb
    monkeypatch.setattr(scd, "extract_embedding", counting_extract)

    seg = np.zeros(16000 * 2, dtype=np.float32)
    vp = VoiceprintState(lawyer=lawyer_emb)
    changes = detect_speaker_changes(seg, vp, sr=16000, window_ms=1000, step_ms=1000)
    assert changes == []
    assert call_count == 0, "静默窗口不应调用 extract_embedding"


def test_small_delta_no_switch(monkeypatch, lawyer_emb):
    """跳变小于 delta_threshold 时不触发切换。"""
    from diarization import speaker_change_detector as scd

    # s_l 序列: 0.50, 0.50, 0.30（跳变 0.20 < 0.25 delta_threshold）
    emb_50 = np.array([0.50, float(np.sqrt(1 - 0.50**2)), 0.0], dtype=np.float32)
    emb_30 = np.array([0.30, float(np.sqrt(1 - 0.30**2)), 0.0], dtype=np.float32)
    fake = _make_fake_extractor([emb_50, emb_50, emb_30])
    monkeypatch.setattr(scd, "extract_embedding", fake)

    seg = np.full(16000 * 3, 0.01, dtype=np.float32)
    vp = VoiceprintState(lawyer=lawyer_emb)
    changes = detect_speaker_changes(seg, vp, sr=16000, window_ms=1000, step_ms=1000)
    assert changes == []
