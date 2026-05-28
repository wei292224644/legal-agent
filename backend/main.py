import asyncio
import json
import sys
import time
from pathlib import Path

import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

sys.path.insert(0, str(Path(__file__).parent / "src"))
from stt.funasr_stream import stream_stt  # noqa: E402

app = FastAPI()


@app.websocket("/ws/{session_id}")
async def legal_session(ws: WebSocket, session_id: str):
    await ws.accept()

    audio_q: asyncio.Queue[tuple[np.ndarray, float] | None] = asyncio.Queue()
    t0 = time.monotonic()

    async def audio_iter():
        while True:
            item = await audio_q.get()
            if item is None:
                return
            yield item

    async def consume_stt():
        async for utt in stream_stt(audio_iter()):
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
