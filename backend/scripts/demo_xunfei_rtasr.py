from __future__ import annotations

import asyncio
import base64
import datetime
import hashlib
import hmac
import json
import os
import random
import string
import urllib.parse
import uuid as uuid_mod
from pathlib import Path

import numpy as np
import requests
import soundfile as sf
import websockets

TARGET_SR = 16000

WS_URL = "wss://office-api-ast-dx.iflyaisol.com/ast/communicate/v1"

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
                if wp in ("n", "s"):
                    text_parts.append(w)
                elif wp == "p":
                    text_parts.append(w)
                # rl: 1/2/3... 表示切换到该说话人；0 表示继续上一说话人
                _rl = cw.get("rl", 0)
                try:
                    rl = int(_rl) if _rl is not None else 0
                except (ValueError, TypeError):
                    rl = 0
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


def _build_ws_url(
    app_id: str,
    access_key_id: str,
    access_key_secret: str,
    feature_ids: str | None = None,
    role_type: int = 2,
    pd: str = "court",
    lang: str = "autodialect",
    audio_encode: str = "pcm_s16le",
    samplerate: int = 16000,
) -> str:
    """构建带签名的 WebSocket 握手 URL。"""
    utc = datetime.datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
    # 签名基于不含 signature 的参数集生成
    uid = str(uuid_mod.uuid4())

    params: dict[str, str] = {
        "accessKeyId": access_key_id,
        "appId": app_id,
        "audio_encode": audio_encode,
        "lang": lang,
        "role_type": str(role_type),
        "samplerate": str(samplerate),
        "utc": utc,
        "uuid": uid,
    }
    if feature_ids:
        params["feature_ids"] = feature_ids
    params["pd"] = pd

    signature = _generate_signature(params, access_key_secret)
    params["signature"] = signature

    encoded = []
    for k, v in sorted(params.items(), key=lambda x: x[0]):
        encoded.append(f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(str(v), safe='')}")
    return f"{WS_URL}?{'&'.join(encoded)}"


async def _transcribe(
    pcm_bytes: bytes,
    app_id: str,
    access_key_id: str,
    access_key_secret: str,
    feature_ids: str | None = None,
    role_type: int = 2,
    pd: str = "court",
) -> list[dict[str, object]]:
    """通过 WebSocket 发送音频并收集转写结果。

    按 40ms / 1280 字节分块发送。
    """
    url = _build_ws_url(app_id, access_key_id, access_key_secret, feature_ids, role_type, pd)
    sentences: list[dict[str, object]] = []
    sid = ""

    async with websockets.connect(url, ping_interval=None) as ws:
        # 等待握手响应
        handshake = await ws.recv()
        hs_data = json.loads(handshake)
        # 讯飞 RTASR 握手消息格式为 {"msg_type": "action", "data": {"action": "started", ...}}
        data = hs_data.get("data", hs_data)
        if data.get("action") == "started":
            sid = data.get("sessionId", data.get("sid", ""))
            print(f"[握手成功] sid={sid}")
        else:
            raise RuntimeError(f"WebSocket 握手失败: {handshake}")

        # 发送和接收并行：一个 task 发音频，一个 task 收结果
        chunk_size = int(TARGET_SR * 0.04 * 2)

        async def _send_audio() -> None:
            for i in range(0, len(pcm_bytes), chunk_size):
                chunk = pcm_bytes[i : i + chunk_size]
                await ws.send(chunk)
                await asyncio.sleep(0.04)  # 模拟实时流
            # 发送结束标识
            await ws.send(json.dumps({"end": True, "sessionId": sid}))

        async def _receive_results() -> None:
            nonlocal sentences
            try:
                async for message in ws:
                    if isinstance(message, bytes):
                        continue
                    payload = json.loads(message)
                    # 讯飞 RTASR 结果格式: {"msg_type": "result", "data": {...}}
                    msg_type = payload.get("msg_type", "")
                    data = payload.get("data", {})
                    if msg_type == "result":
                        sentence = _parse_transcription_result(data)
                        if sentence["text"]:
                            sentences.append(sentence)
                            _print_sentence(sentence)
                    elif msg_type == "error":
                        print(f"[错误] code={data.get('code')} desc={data.get('desc')}")
                        break
            except websockets.exceptions.ConnectionClosed:
                pass

        await asyncio.gather(_send_audio(), _receive_results())

    return sentences


def _format_time(ms: int) -> str:
    """毫秒转为 MM:SS.mmm 格式。"""
    total_seconds = ms // 1000
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    millis = ms % 1000
    return f"{minutes:02d}:{seconds:02d}.{millis:03d}"


def _print_sentence(sentence: dict[str, object]) -> None:
    """打印单句转写结果。"""
    speaker = sentence["speaker"]
    start = _format_time(sentence["start_ms"])
    end = _format_time(sentence["end_ms"])
    text = sentence["text"]
    print(f"[说话人{speaker}] {start} - {end}")
    print(f"  {text}")


def main() -> None:
    """Demo 入口。"""
    import dotenv
    dotenv.load_dotenv(Path(__file__).parent.parent / ".env")

    app_id = os.getenv("XUNFEI_APPID", "").strip()
    access_key_id = os.getenv("XUNFEI_APIKEY", "").strip()
    access_key_secret = os.getenv("XUNFEI_APISECRET", "").strip()

    if not all([app_id, access_key_id, access_key_secret]):
        print("错误：请设置环境变量 XUNFEI_APPID、XUNFEI_APIKEY、XUNFEI_APISECRET")
        print("或在 backend/.env 文件中配置：")
        print("  XUNFEI_APPID=xxx")
        print("  XUNFEI_APIKEY=xxx")
        print("  XUNFEI_APISECRET=xxx")
        raise SystemExit(1)

    # 声纹注册音频（律师声纹，需 10s~60s）
    enroll_path = Path(__file__).parent.parent / "tests" / "fixtures" / "律师声纹注册_30s.wav"
    if not enroll_path.exists():
        print(f"错误：找不到声纹注册音频 {enroll_path}")
        raise SystemExit(1)

    # 实时转写音频（会谈对话）
    fixture_path = Path(__file__).parent.parent / "tests" / "fixtures" / "two_utterances.wav"
    if not fixture_path.exists():
        print(f"错误：找不到测试音频 {fixture_path}")
        raise SystemExit(1)

    print(f"[加载声纹音频] {enroll_path.name}")
    enroll_pcm, enroll_duration_ms = _load_audio_as_pcm16(str(enroll_path))
    print(f"[声纹音频信息] 时长 {enroll_duration_ms / 1000:.1f}s")

    print(f"[加载转写音频] {fixture_path.name}")
    pcm_bytes, duration_ms = _load_audio_as_pcm16(str(fixture_path))
    print(f"[转写音频信息] 时长 {duration_ms / 1000:.1f}s, PCM 大小 {len(pcm_bytes)} bytes")

    if enroll_duration_ms < 10_000:
        print("警告：声纹音频时长不足 10s，注册可能失败。")

    # 声纹注册：截断到 60s
    register_pcm = enroll_pcm
    if enroll_duration_ms > 60_000:
        print("警告：声纹音频超过 60s，只取前 60s")
        register_pcm = enroll_pcm[: int(60_000 / 1000 * TARGET_SR * 2)]

    print("[声纹注册] 正在上传...")
    audio_base64 = base64.b64encode(register_pcm).decode("utf-8")

    try:
        feature_id = _register_voiceprint(
            audio_base64=audio_base64,
            audio_type="raw",
            app_id=app_id,
            access_key_id=access_key_id,
            access_key_secret=access_key_secret,
        )
        print(f"[声纹注册] 成功，feature_id={feature_id}")

        # 实时转写
        print("[实时转写] 开始发送音频...")
        sentences = asyncio.run(
            _transcribe(
                pcm_bytes=pcm_bytes,
                app_id=app_id,
                access_key_id=access_key_id,
                access_key_secret=access_key_secret,
                feature_ids=feature_id,
                role_type=2,
                pd="court",
            )
        )
        print(f"[完成] 共 {len(sentences)} 句")
    except Exception as e:
        print(f"[错误] {e}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
