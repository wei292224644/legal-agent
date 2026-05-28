import asyncio
import json
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

sys.path.insert(0, str(Path(__file__).parent / "src"))
from diarization.enrollment import Enrollment, enroll_speaker  # noqa: E402
from stt.funasr_stream import stream_stt  # noqa: E402

ENROLLMENT_WAV = Path(__file__).parent / "tests" / "fixtures" / "律师声纹注册.wav"

app = FastAPI()

_lawyer_enrollment: Enrollment | None = None


def _get_lawyer_enrollment() -> Enrollment:
    """模块级单例:律师 enrollment 全进程加载一次。

    Sprint 3 会把这换成 WS 协议里前端上传 / 用户绑定的 enrollment。
    """
    global _lawyer_enrollment
    if _lawyer_enrollment is None:
        audio, sr = sf.read(str(ENROLLMENT_WAV), dtype="float32", always_2d=False)
        if audio.ndim == 2:
            audio = audio.mean(axis=1)
        _lawyer_enrollment = enroll_speaker(audio, sr)
    return _lawyer_enrollment


@app.websocket("/ws/{session_id}")
async def legal_session(ws: WebSocket, session_id: str):
    await ws.accept()

    enrollment = _get_lawyer_enrollment()
    audio_q: asyncio.Queue[tuple[np.ndarray, float] | None] = asyncio.Queue()
    t0 = time.monotonic()

    async def audio_iter():
        while True:
            item = await audio_q.get()
            if item is None:
                return
            yield item

    async def consume_stt():
        async for utt in stream_stt(audio_iter(), enrollment=enrollment):
            await ws.send_json({
                "type": "transcript",
                "id": utt.id,
                "text": utt.text,
                "t_start": utt.t_start,
                "t_end": utt.t_end,
                "speaker": utt.speaker,
                "closed_by": utt.closed_by,
                "is_final": True,
            })

    stt_task = asyncio.create_task(consume_stt())

    try:
        while True:
            data = await ws.receive()

            if data["type"] == "websocket.disconnect":
                break

            if "bytes" in data:
                audio = np.frombuffer(data["bytes"], dtype=np.int16).astype(np.float32) / 32768.0
                await audio_q.put((audio, time.monotonic() - t0))

            elif "text" in data:
                msg = json.loads(data["text"])
                msg_type = msg.get("type")
                if msg_type == "ping":
                    await ws.send_json({"type": "pong"})
                # intent confirm/dismiss 待 Sprint 3 Orchestrator 接入

    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await audio_q.put(None)
        try:
            await stt_task
        except Exception:
            pass
