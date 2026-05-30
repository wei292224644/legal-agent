import base64
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from demo_xunfei_rtasr import _generate_signature, _load_audio_as_pcm16


def test_generate_signature():
    """验证签名算法与讯飞文档一致。"""
    params = {
        "accessKeyId": "test_key",
        "appId": "test_app",
        "utc": "2025-03-24T00:01:19+0800",
    }
    secret = "test_secret"
    sig = _generate_signature(params, secret)
    expected_sig = "wFXx9aK7jMUS4tMyAbx/LztabDo="
    assert sig == expected_sig


def test_load_audio_as_pcm16():
    """验证音频被正确加载为 16kHz 16bit 单声道 PCM bytes。"""
    fixture_path = Path(__file__).parent / "fixtures" / "律师声纹注册.wav"
    pcm_bytes, duration_ms = _load_audio_as_pcm16(str(fixture_path))
    # 16bit = 2 bytes per sample, 16kHz = 16000 samples/sec
    expected_bytes = int(duration_ms / 1000 * 16000 * 2)
    assert len(pcm_bytes) == expected_bytes
    assert isinstance(pcm_bytes, bytes)
    assert duration_ms > 0
