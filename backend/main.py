import asyncio
import json
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

sys.path.insert(0, str(Path(__file__).parent / "src"))
from agent.bus import UtteranceBus  # noqa: E402
from agent.context_store import ContextStore  # noqa: E402
from agent.orchestrator import Orchestrator  # noqa: E402
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

    # 首次加载会跑 cam++ 推理,放线程池避免阻塞 event loop(后续 session 是缓存命中,几乎 0 成本)
    enrollment = await asyncio.to_thread(_get_lawyer_enrollment)
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
            ok = await bus.put(utt)
            if not ok:
                # 有界队列满时丢弃，避免内存无限堆积
                print(f"[WARN] Utterance bus full, dropping utt {utt.id}")

    ctx = ContextStore()
    orch = Orchestrator(ctx)
    bus = UtteranceBus(maxsize=10)
    orch.attach_bus(bus)

    async def on_suggestion(text, meta):
        if meta.get("kind") == "pending":
            await ws.send_json({
                "type": "suggestion.pending",
                "text": None,
                "meta": {
                    "severity": meta["severity"],
                    "intent_type": meta["intent_type"],
                    "law_domain": meta["law_domain"],
                    "entities": meta["entities"],
                    "utt_id": meta["utt_id"],
                    "request_id": meta["request_id"],
                },
            })
        else:
            await ws.send_json({
                "type": "suggestion.ready",
                "text": text,
                "meta": {
                    "severity": meta["severity"],
                    "intent_type": meta["intent_type"],
                    "law_domain": meta["law_domain"],
                    "entities": meta["entities"],
                    "utt_id": meta["utt_id"],
                },
            })

    orch.set_suggestion_callback(on_suggestion)
    await orch.start()

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
                try:
                    msg = json.loads(data["text"])
                except json.JSONDecodeError:
                    await ws.send_json({"type": "error", "message": "Invalid JSON"})
                    continue
                msg_type = msg.get("type")
                if msg_type == "ping":
                    await ws.send_json({"type": "pong"})
                elif msg_type == "confirm":
                    request_id = msg.get("request_id")
                    if request_id:
                        ok = await orch.confirm_analysis(request_id)
                        await ws.send_json({"type": "confirm_ack", "request_id": request_id, "ok": ok})
                elif msg_type == "dismiss":
                    request_id = msg.get("request_id")
                    if request_id:
                        orch.dismiss_pending(request_id)

    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await audio_q.put(None)
        try:
            await orch.shutdown()
        except Exception:
            pass
        try:
            await stt_task
        except Exception:
            pass
