from __future__ import annotations

import base64
import hashlib
import hmac
import urllib.parse

import numpy as np
import soundfile as sf

TARGET_SR = 16000


def _load_audio_as_pcm16(path: str) -> tuple[bytes, float]:
    """读取音频文件，重采样到 16kHz 单声道，转为 16bit PCM bytes。

    Returns:
        (pcm_bytes, duration_ms)
    """
    data, sr = sf.read(path, dtype="float32")
    # 转单声道
    if data.ndim > 1:
        data = data.mean(axis=1)
    # 重采样到 16kHz
    if sr != TARGET_SR:
        ratio = TARGET_SR / sr
        n = int(len(data) * ratio)
        indices = np.linspace(0, len(data) - 1, n)
        # 使用线性插值快速重采样；演示脚本不追求 Hi-Fi 音质
        data = np.interp(indices, np.arange(len(data)), data)
    # float32 [-1, 1] -> int16
    data_int16 = np.clip(data * 32767, -32768, 32767).astype(np.int16)
    pcm_bytes = data_int16.astype("<i2").tobytes()
    duration_ms = len(data_int16) / TARGET_SR * 1000
    return pcm_bytes, duration_ms


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
