from __future__ import annotations

import base64
import hashlib
import hmac
import urllib.parse


def _generate_signature(params: dict[str, str], secret: str) -> str:
    """按照讯飞规则生成 HmacSHA1 + Base64 签名。

    规则：
    1. 按键 ASCII 升序排序
    2. 对 key 和 value 进行 URL 编码
    3. 拼接为 "key1=value1&key2=value2&..."
    4. HmacSHA1(secret, 拼接字符串)
    5. Base64 编码
    """
    sorted_items = sorted(params.items(), key=lambda x: x[0])
    encoded_pairs = []
    for k, v in sorted_items:
        ek = urllib.parse.quote(k, safe="")
        ev = urllib.parse.quote(str(v), safe="")
        encoded_pairs.append(f"{ek}={ev}")
    base_string = "&".join(encoded_pairs)
    mac = hmac.new(secret.encode("utf-8"), base_string.encode("utf-8"), hashlib.sha1)
    return base64.b64encode(mac.digest()).decode("utf-8")
