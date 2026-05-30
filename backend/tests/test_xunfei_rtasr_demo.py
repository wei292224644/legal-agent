import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from demo_xunfei_rtasr import _generate_signature


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
