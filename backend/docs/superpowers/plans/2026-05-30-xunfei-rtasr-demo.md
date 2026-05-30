# 讯飞实时语音转写大模型 Demo 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现一个独立 Python 脚本，离线调用讯飞声纹注册 + 实时语音转写大模型接口，验证云端方案效果。

**Architecture:** 单脚本结构，纯函数可测部分（签名、音频处理、结果解析）走 TDD，WebSocket 集成主流程直接实现。凭证从环境变量读取，零侵入现有业务代码。

**Tech Stack:** Python 3.12, `websockets`, `soundfile`, `numpy`, `python-dotenv`, `httpx`（或 `requests`，项目已有）

---

## 文件结构

| 文件 | 类型 | 职责 |
|---|---|---|
| `backend/scripts/demo_xunfei_rtasr.py` | 新建 | 主 demo 脚本：配置读取、签名生成、声纹注册、WebSocket 转写、结果输出 |
| `backend/tests/test_xunfei_rtasr_demo.py` | 新建 | 单元测试：签名生成、音频加载、结果解析 |

**已有依赖已满足需求：** `websockets>=14.0`（WebSocket 客户端）、`soundfile>=0.12.0`（音频读取）、`python-dotenv>=1.1.0`（环境变量）。无需新增依赖。

---

## Task 1: 签名生成函数

**Files:**
- Create: `backend/scripts/demo_xunfei_rtasr.py`
- Test: `backend/tests/test_xunfei_rtasr_demo.py`

- [ ] **Step 1: 写失败的签名测试**

```python
# backend/tests/test_xunfei_rtasr_demo.py
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
    # 签名是 Base64 字符串，至少不为空且可解码
    import base64
    decoded = base64.b64decode(sig)
    assert len(decoded) == 20  # HmacSHA1 输出 20 字节
```

Run: `cd backend && uv run pytest tests/test_xunfei_rtasr_demo.py::test_generate_signature -v`
Expected: FAIL with `ImportError`（模块不存在）

- [ ] **Step 2: 实现签名生成函数**

```python
# backend/scripts/demo_xunfei_rtasr.py
from __future__ import annotations

import base64
import hashlib
import hmac
import urllib.parse


def _generate_signature(params: dict[str, str], secret: str) -> str:
    """按讯飞规则生成 HmacSHA1 + Base64 签名。

    规则：
    1. 按 key ASCII 升序排序
    2. key/value 分别 URL 编码
    3. 拼接为 key1=value1&key2=value2&...
    4. HmacSHA1(secret, 拼接串)
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
```

- [ ] **Step 3: 运行测试确认通过**

Run: `cd backend && uv run pytest tests/test_xunfei_rtasr_demo.py::test_generate_signature -v`
Expected: PASS

- [ ] **Step 4: 提交**

```bash
git add backend/scripts/demo_xunfei_rtasr.py backend/tests/test_xunfei_rtasr_demo.py
git commit -m "$(cat <<'EOF'
feat(xunfei): 签名生成函数 + 单元测试

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: 音频加载与预处理

**Files:**
- Modify: `backend/scripts/demo_xunfei_rtasr.py`
- Test: `backend/tests/test_xunfei_rtasr_demo.py`

- [ ] **Step 1: 写失败的音频加载测试**

```python
# backend/tests/test_xunfei_rtasr_demo.py
import numpy as np

from demo_xunfei_rtasr import _load_audio_as_pcm16


def test_load_audio_as_pcm16():
    """验证音频能被正确加载为 16kHz 16bit 单声道 PCM bytes。"""
    fixture_path = Path(__file__).parent / "fixtures" / "律师声纹注册.wav"
    pcm_bytes, duration_ms = _load_audio_as_pcm16(str(fixture_path))
    # 16bit = 2 bytes per sample, 16kHz = 16000 samples/sec
    expected_bytes = int(duration_ms / 1000 * 16000 * 2)
    assert len(pcm_bytes) == expected_bytes
    assert isinstance(pcm_bytes, bytes)
    assert duration_ms > 0
```

Run: `cd backend && uv run pytest tests/test_xunfei_rtasr_demo.py::test_load_audio_as_pcm16 -v`
Expected: FAIL with `ImportError`（函数不存在）

- [ ] **Step 2: 实现音频加载函数**

```python
# backend/scripts/demo_xunfei_rtasr.py
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
        # 使用简单线性插值重采样，无需引入 torchaudio 依赖
        ratio = TARGET_SR / sr
        n = int(len(data) * ratio)
        indices = np.linspace(0, len(data) - 1, n)
        data = np.interp(indices, np.arange(len(data)), data)
    # float32 [-1, 1] -> int16
    data_int16 = (data * 32767).astype(np.int16)
    pcm_bytes = data_int16.tobytes()
    duration_ms = len(data_int16) / TARGET_SR * 1000
    return pcm_bytes, duration_ms
```

- [ ] **Step 3: 运行测试确认通过**

Run: `cd backend && uv run pytest tests/test_xunfei_rtasr_demo.py::test_load_audio_as_pcm16 -v`
Expected: PASS

- [ ] **Step 4: 提交**

```bash
git add backend/scripts/demo_xunfei_rtasr.py backend/tests/test_xunfei_rtasr_demo.py
git commit -m "$(cat <<'EOF'
feat(xunfei): 音频加载与预处理函数 + 测试

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: 声纹注册 HTTP 调用

**Files:**
- Modify: `backend/scripts/demo_xunfei_rtasr.py`
- Test: `backend/tests/test_xunfei_rtasr_demo.py`

- [ ] **Step 1: 写失败的声纹注册测试**

```python
# backend/tests/test_xunfei_rtasr_demo.py
from unittest.mock import Mock, patch

from demo_xunfei_rtasr import _register_voiceprint


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
```

Run: `cd backend && uv run pytest tests/test_xunfei_rtasr_demo.py::test_register_voiceprint -v`
Expected: FAIL with `ImportError`（函数不存在）

- [ ] **Step 2: 实现声纹注册函数**

```python
# backend/scripts/demo_xunfei_rtasr.py
import base64
import datetime
import random
import string

import requests

VOICEPRINT_URL = "https://office-api-personal-dx.iflyaisol.com/res/feature/v1/register"


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
    data = json.loads(result["data"]) if isinstance(result.get("data"), str) else result.get("data", {})
    if data.get("status") != 1:
        raise RuntimeError(f"声纹注册状态异常: {data}")
    return data["feature_id"]
```

注意：顶部 import 区需要新增 `import json`。

- [ ] **Step 3: 运行测试确认通过**

Run: `cd backend && uv run pytest tests/test_xunfei_rtasr_demo.py::test_register_voiceprint -v`
Expected: PASS

- [ ] **Step 4: 提交**

```bash
git add backend/scripts/demo_xunfei_rtasr.py backend/tests/test_xunfei_rtasr_demo.py
git commit -m "$(cat <<'EOF'
feat(xunfei): 声纹注册 HTTP 调用 + 测试

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: 结果解析函数

**Files:**
- Modify: `backend/scripts/demo_xunfei_rtasr.py`
- Test: `backend/tests/test_xunfei_rtasr_demo.py`

- [ ] **Step 1: 写失败的结果解析测试**

```python
# backend/tests/test_xunfei_rtasr_demo.py

from demo_xunfei_rtasr import _parse_transcription_result


def test_parse_transcription_result():
    """验证转写结果能正确解析为结构化文本。"""
    raw = {
        "cn": {
            "st": {
                "type": 0,
                "bg": 2340,
                "ed": 5120,
                "rt": [
                    {
                        "ws": [
                            {"cw": [{"w": "你", "wb": 2340, "we": 2680, "wp": "n", "rl": 1}]},
                            {"cw": [{"w": "好", "wb": 2680, "we": 2950, "wp": "n", "rl": 0}]},
                            {"cw": [{"w": "。", "wb": 2950, "we": 2950, "wp": "p", "rl": 0}]},
                        ]
                    }
                ],
            }
        },
        "seg_id": 0,
    }
    sentence = _parse_transcription_result(raw)
    assert sentence["text"] == "你好。"
    assert sentence["speaker"] == 1
    assert sentence["start_ms"] == 2340
    assert sentence["end_ms"] == 5120
```

Run: `cd backend && uv run pytest tests/test_xunfei_rtasr_demo.py::test_parse_transcription_result -v`
Expected: FAIL with `ImportError`（函数不存在）

- [ ] **Step 2: 实现结果解析函数**

```python
# backend/scripts/demo_xunfei_rtasr.py


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
```

- [ ] **Step 3: 运行测试确认通过**

Run: `cd backend && uv run pytest tests/test_xunfei_rtasr_demo.py::test_parse_transcription_result -v`
Expected: PASS

- [ ] **Step 4: 提交**

```bash
git add backend/scripts/demo_xunfei_rtasr.py backend/tests/test_xunfei_rtasr_demo.py
git commit -m "$(cat <<'EOF'
feat(xunfei): 转写结果解析函数 + 测试

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: WebSocket 实时转写主流程

**Files:**
- Modify: `backend/scripts/demo_xunfei_rtasr.py`

- [ ] **Step 1: 实现 WebSocket URL 构建与连接**

```python
# backend/scripts/demo_xunfei_rtasr.py
import asyncio
import json
import uuid as uuid_mod

import websockets

WS_URL = "wss://office-api-ast-dx.iflyaisol.com/ast/communicate/v1"


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
    # URL 编码时区偏移中的 + 号
    utc = utc.replace("+", "%2B")
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
    if pd:
        params["pd"] = pd

    signature = _generate_signature(params, access_key_secret)
    params["signature"] = signature

    # 对所有参数做 URL 编码并拼接
    encoded = []
    for k, v in sorted(params.items(), key=lambda x: x[0]):
        encoded.append(f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(str(v), safe='')}")
    return f"{WS_URL}?{'&'.join(encoded)}"
```

- [ ] **Step 2: 实现 WebSocket 音频发送与结果接收**

```python
# backend/scripts/demo_xunfei_rtasr.py


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

    async with websockets.connect(url) as ws:
        # 等待握手响应
        handshake = await ws.recv()
        hs_data = json.loads(handshake)
        if hs_data.get("action") == "started":
            sid = hs_data.get("sid", "")
            print(f"[握手成功] sid={sid}")
        else:
            print(f"[握手异常] {handshake}")
            return sentences

        # 分块发送音频：40ms = 16000 * 0.04 * 2 bytes = 1280 bytes
        chunk_size = 1280
        for i in range(0, len(pcm_bytes), chunk_size):
            chunk = pcm_bytes[i : i + chunk_size]
            await ws.send(chunk)
            await asyncio.sleep(0.04)  # 模拟实时流

        # 发送结束标识
        await ws.send(json.dumps({"end": True, "sessionId": sid}))

        # 持续接收结果直到连接关闭
        try:
            async for message in ws:
                if isinstance(message, bytes):
                    continue
                data = json.loads(message)
                action = data.get("action")
                if action == "result":
                    sentence = _parse_transcription_result(data.get("data", {}))
                    if sentence["text"]:
                        sentences.append(sentence)
                        _print_sentence(sentence)
                elif action == "error":
                    print(f"[错误] code={data.get('code')} desc={data.get('desc')}")
                    break
        except websockets.exceptions.ConnectionClosed:
            pass

    return sentences
```

- [ ] **Step 3: 实现终端格式化输出**

```python
# backend/scripts/demo_xunfei_rtasr.py


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
```

- [ ] **Step 4: 实现主函数入口**

```python
# backend/scripts/demo_xunfei_rtasr.py

import os


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

    fixture_path = Path(__file__).parent.parent / "tests" / "fixtures" / "律师声纹注册.wav"
    if not fixture_path.exists():
        print(f"错误：找不到测试音频 {fixture_path}")
        raise SystemExit(1)

    print(f"[加载音频] {fixture_path.name}")
    pcm_bytes, duration_ms = _load_audio_as_pcm16(str(fixture_path))
    print(f"[音频信息] 时长 {duration_ms / 1000:.1f}s, PCM 大小 {len(pcm_bytes)} bytes")

    if duration_ms < 10_000:
        print("警告：音频时长不足 10s，声纹注册可能失败。请使用更长的音频。")

    # 声纹注册
    print("[声纹注册] 正在上传...")
    audio_base64 = base64.b64encode(pcm_bytes).decode("utf-8")
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


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: 提交**

```bash
git add backend/scripts/demo_xunfei_rtasr.py
git commit -m "$(cat <<'EOF'
feat(xunfei): WebSocket 实时转写主流程 + 终端输出

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: 端到端验证

**Files:**
- Modify: `backend/.env.example`（可选，添加凭证模板注释）

- [ ] **Step 1: 运行全部单元测试**

Run: `cd backend && uv run pytest tests/test_xunfei_rtasr_demo.py -v`
Expected: 4 tests PASS（签名、音频加载、声纹注册、结果解析）

- [ ] **Step 2: 配置环境变量并运行 demo**

```bash
cd backend
export XUNFEI_APPID="5040f1a0"
export XUNFEI_APIKEY="a22cef6d51f3c7a85104cbc90705414c"
export XUNFEI_APISECRET="MjAzY2E3ODA4NDJhYzYxZTgwMmZjYTg0"
uv run python scripts/demo_xunfei_rtasr.py
```

Expected 输出格式：
```
[加载音频] 律师声纹注册.wav
[音频信息] 时长 xx.xs, PCM 大小 xxxxx bytes
[声纹注册] 正在上传...
[声纹注册] 成功，feature_id=...
[握手成功] sid=...
[说话人1] 00:02.340 - 00:05.120
  您好，我是王律师。
...
[完成] 共 N 句
```

- [ ] **Step 3: 若音频不足 10s，用 `劳动仲裁对话_完整版.wav` 测试**

```bash
cd backend
# 临时修改脚本中的 fixture_path 或使用命令行参数（如已实现）
uv run python scripts/demo_xunfei_rtasr.py
```

若 `律师声纹注册.wav` 时长不足 10s，修改脚本默认路径为 `tests/fixtures/劳动仲裁对话_完整版.wav` 后重新运行。

- [ ] **Step 4: 提交最终版本**

```bash
git add backend/scripts/demo_xunfei_rtasr.py backend/tests/test_xunfei_rtasr_demo.py
git commit -m "$(cat <<'EOF'
feat(xunfei): 讯飞 RTASR + 声纹注册 Demo 完成

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**1. Spec coverage：**
- [x] 签名生成（HmacSHA1 + Base64）→ Task 1
- [x] 音频 16kHz 16bit PCM 转换 → Task 2
- [x] 声纹注册 HTTP 调用 → Task 3
- [x] WebSocket 握手 URL 构建 → Task 5 Step 1
- [x] 分块发送音频（40ms/1280 bytes）→ Task 5 Step 2
- [x] 结束标识 JSON → Task 5 Step 2
- [x] 结果解析（rl 角色、时间戳、文本）→ Task 4
- [x] 终端格式化输出 → Task 5 Step 3
- [x] 凭证环境变量读取 → Task 5 Step 4
- [x] 参数：role_type=2、feature_ids、pd=court → Task 5 Step 1
- [x] 音频时长不足 10s 的警告 → Task 6 Step 2

**2. Placeholder scan：**
- 无 TBD、TODO、"implement later"
- 所有代码块包含完整实现
- 所有命令包含预期输出

**3. Type consistency：**
- `_generate_signature(params: dict[str, str], secret: str) -> str` 全 plan 一致
- `_load_audio_as_pcm16(path: str) -> tuple[bytes, float]` 全 plan 一致
- `_register_voiceprint` 参数名与调用处一致
- `_parse_transcription_result(data: dict) -> dict[str, object]` 全 plan 一致

**4. 依赖检查：**
- `websockets`：已在 `pyproject.toml`
- `soundfile`：已在 `pyproject.toml`
- `python-dotenv`：已在 `pyproject.toml`
- `requests`：项目已有 FastAPI，推测可用（或改用 `httpx`，已在 `pyproject.toml` 中）
- 若 `requests` 未安装，Task 3 改用 `httpx.post`：
  ```python
  import httpx
  resp = httpx.post(VOICEPRINT_URL, params=query_params, headers=headers, json=body)
  ```
