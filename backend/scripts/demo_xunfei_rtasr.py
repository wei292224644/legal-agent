from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import json
import random
import string
import urllib.parse

import numpy as np
import requests
import soundfile as sf

TARGET_SR = 16000

VOICEPRINT_URL = "https://office-api-personal-dx.iflyaisol.com/res/feature/v1/register"


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


def _parse_transcription_result(data: dict) -> dict[str, object]:
    """解析讯飞转写结果中的单句数据。

    Returns:
        {"text": str, "speaker": int, "start_ms": int, "end_ms": int}
    """
    st = data.get("cn", {}).get("st", {})
    text_parts = []
    speaker = 0
    start_ms = st.get("bg", 0)
    end_ms = st.get("ed", 0)

    for rt_item in st.get("rt", []):
        for ws_item in rt_item.get("ws", []):
            for cw in ws_item.get("cw", []):
                w = cw.get("w", "")
                wp = cw.get("wp", "n")
                if wp == "n":
                    text_parts.append(w)
                elif wp == "p":
                    text_parts.append(w)
                # rl: 1/2/3... 表示切换到该说话人；0 表示继续上一说话人
                rl = cw.get("rl", 0)
                if rl > 0:
                    speaker = rl

    return {
        "text": "".join(text_parts),
        "speaker": speaker,
        "start_ms": start_ms,
        "end_ms": end_ms,
    }


def _register_voiceprint(
    audio_base64: str,
    audio_type: str,
    app_id: str,
    access_key_id: str,
    access_key_secret: str,
    uid: str | None = None,
) -> str:
    """注册声纹，返回 feature_id。

    音频要求：10s ~ 60s，base64 编码。
    """
    date_time = datetime.datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
    signature_random = "".join(random.choices(string.ascii_letters + string.digits, k=16))

    query_params = {
        "appId": app_id,
        "accessKeyId": access_key_id,
        "dateTime": date_time,
        "signatureRandom": signature_random,
    }
    signature = _generate_signature(query_params, access_key_secret)

    headers = {
        "Content-Type": "application/json",
        "signature": signature,
    }

    body: dict[str, str] = {
        "audio_data": audio_base64,
        "audio_type": audio_type,
    }
    if uid:
        body["uid"] = uid

    resp = requests.post(VOICEPRINT_URL, params=query_params, headers=headers, json=body)
    resp.raise_for_status()
    result = resp.json()
    if result.get("code") != "000000":
        raise RuntimeError(f"声纹注册失败: {result.get('code')} - {result.get('desc')}")
    raw_data = result.get("data", "{}")
    data = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
    if data.get("status") != 1:
        raise RuntimeError(f"声纹注册状态异常: {data}")
    return data["feature_id"]
