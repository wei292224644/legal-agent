import numpy as np
import pytest
import voiceprint


def test_compare_identical_vectors_returns_1():
    v = np.array([1.0, 0.0, 0.0])
    assert voiceprint.compare(v, v) == pytest.approx(1.0)


def test_compare_orthogonal_vectors_returns_0():
    a = np.array([1.0, 0.0, 0.0])
    b = np.array([0.0, 1.0, 0.0])
    assert voiceprint.compare(a, b) == pytest.approx(0.0)


def test_register_and_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(voiceprint, "VOICEPRINTS_DIR", tmp_path)
    expected = np.array([0.1, 0.2, 0.3])
    fake_embed = lambda _audio: expected

    voiceprint.register(b"audio_bytes", "session-abc", embed_fn=fake_embed)
    loaded = voiceprint.load("session-abc")

    assert loaded is not None
    np.testing.assert_array_equal(loaded, expected)


def test_load_missing_session_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(voiceprint, "VOICEPRINTS_DIR", tmp_path)
    assert voiceprint.load("nonexistent") is None
