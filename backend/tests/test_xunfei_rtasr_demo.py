import base64
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from demo_xunfei_rtasr import _generate_signature, _load_audio_as_pcm16, _register_voiceprint


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
    fixture_path = Path(__file__).parent / "fixtures" / "律师声纹注册_30s.wav"
    pcm_bytes, duration_ms = _load_audio_as_pcm16(str(fixture_path))
    # 16bit = 2 bytes per sample, 16kHz = 16000 samples/sec
    expected_bytes = int(duration_ms / 1000 * 16000 * 2)
    assert len(pcm_bytes) == expected_bytes
    assert isinstance(pcm_bytes, bytes)
    assert duration_ms > 0


def test_register_voiceprint():
    """验证声纹注册 HTTP 调用格式正确。"""
    mock_resp = Mock()
    mock_resp.json.return_value = {
        "code": "000000",
        "desc": "success",
        "data": '{"feature_id": "feat_123", "status": 1}',
        "sid": "sid_123",
    }
    mock_resp.raise_for_status = Mock()

    with patch("demo_xunfei_rtasr.requests.post", return_value=mock_resp) as mock_post:
        feature_id = _register_voiceprint(
            audio_base64="dGVzdA==",
            audio_type="raw",
            app_id="app_123",
            access_key_id="key_123",
            access_key_secret="secret_123",
        )

    assert feature_id == "feat_123"
    mock_post.assert_called_once()
    call_args = mock_post.call_args
    assert "register" in call_args[0][0]
    assert call_args[1]["headers"]["Content-Type"] == "application/json"
    assert "signature" in call_args[1]["headers"]
    body = call_args[1]["json"]
    assert body["audio_data"] == "dGVzdA=="
    assert body["audio_type"] == "raw"
