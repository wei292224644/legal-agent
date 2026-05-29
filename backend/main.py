import asyncio
import copy
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
from session.manager import SessionManager  # noqa: E402
from session.persistence import SQLiteBackend  # noqa: E402
from session.serializer import SessionSerializer  # noqa: E402
from session.summary import generate_summary  # noqa: E402
from stt.funasr_stream import stream_stt  # noqa: E402

ENROLLMENT_WAV = Path(__file__).parent / "tests" / "fixtures" / "律师声纹注册.wav"
SESSION_DB = Path(__file__).parent / "data" / "sessions.db"

app = FastAPI()

_lawyer_enrollment: Enrollment | None = None
session_manager: SessionManager | None = None


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


def _session_enrollment() -> Enrollment:
    """每个会话拿到独立的 enrollment 副本。

    matcher 的双声纹自举会写回 client_embedding;若所有会话共享全局单例,
    会话 A 的客户声纹种子会泄漏污染会话 B 的说话人判定。
    """
    return copy.deepcopy(_get_lawyer_enrollment())


@app.on_event("startup")
async def _startup() -> None:
    global session_manager
    SESSION_DB.parent.mkdir(parents=True, exist_ok=True)
    backend = SQLiteBackend(SESSION_DB)
    session_manager = SessionManager(backend, snapshot_interval=60.0, ttl=600.0)
    await session_manager.start()


@app.on_event("shutdown")
async def _shutdown() -> None:
    global session_manager
    if session_manager is not None:
        await session_manager.stop()
        session_manager = None


@app.websocket("/ws/{session_id}")
async def legal_session(ws: WebSocket, session_id: str):
    await ws.accept()

    # --- Session 获取 / 创建 / 恢复 ---
    state = await session_manager.get_state(session_id)
    if state is None:
        state = await session_manager.restore_session(session_id)
    if state is None:
        enrollment = await asyncio.to_thread(_session_enrollment)
        session_id = await session_manager.create_session(enrollment, session_id=session_id)
        state = await session_manager.get_state(session_id)

    # 排他连接：已有 WebSocket 时拒绝新连接
    attached = await session_manager.attach_ws(session_id, ws)
    if not attached:
        await ws.close(code=1008, reason="Session already connected")
        return

    # --- 恢复或新建 Agent 状态 ---
    if state.context_store and state.orchestrator:
        ctx = ContextStore.from_dict(state.context_store)
        orch = Orchestrator.from_dict(state.orchestrator, ctx=ctx)
    else:
        ctx = ContextStore()
        orch = Orchestrator(ctx)

    bus = UtteranceBus(maxsize=10)
    orch.attach_bus(bus)

    async def on_suggestion(text, meta):
        try:
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
        except Exception:
            # WS 已断开时不应崩溃
            pass

    orch.set_suggestion_callback(on_suggestion)
    await orch.start()

    # --- 音频管道 ---
    enrollment = SessionSerializer.enrollment_from_dict(state.enrollment)
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
            try:
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
            except Exception:
                pass
            ok = await bus.put(utt)
            if not ok:
                print(f"[WARN] Utterance bus full, dropping utt {utt.id}")

    stt_task = asyncio.create_task(consume_stt())

    # --- 主循环 ---
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
                elif msg_type == "close":
                    summary = await generate_summary(ctx)
                    state = await session_manager.get_state(session_id)
                    if state is not None:
                        state.summary = summary
                    await session_manager.close_session(session_id)
                    break

    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await audio_q.put(None)
        # 保存 Agent 状态 → SessionManager → 持久化
        state = await session_manager.get_state(session_id)
        if state is not None and state.status != "closed":
            await session_manager.update_agent_state(session_id, ctx, orch)
            await session_manager.detach_ws(session_id)
        try:
            await orch.shutdown()
        except Exception:
            pass
        try:
            await stt_task
        except Exception:
            pass
