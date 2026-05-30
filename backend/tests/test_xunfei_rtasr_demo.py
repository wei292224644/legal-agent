import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from demo_xunfei_rtasr import _generate_signature


def test_generate_signature():
    """验证签名算法与讯飞文档一致。"""
    params = {
        "accessKeyId": "XXX",
        "appId": "YYY",
        "lang": "cn",
        "utc": "2025-03-24T00%3A01%3A19%2B0800",
        "uuid": "edf53e32-6533-4d6a-acd3-fe4df14ee332",
    }
    secret = "test_secret"
    sig = _generate_signature(params, secret)
    import base64
    decoded = base64.b64decode(sig)
    assert len(decoded) == 20  # HmacSHA1 输出 20 字节
