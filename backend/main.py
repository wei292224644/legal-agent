import asyncio
import contextlib
import copy
import json
import logging
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

# uvicorn 默认只给 uvicorn.* 系列 logger 加 handler,不给应用 logger。
# 不调 basicConfig 的话,main.py 与 src/* 里的 logger.info 全静默,
# 排查问题时会误以为代码没跑到。force=True 覆盖任何已有 root handler。
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    force=True,
)

logger = logging.getLogger(__name__)

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


async def _safe_send_json(ws: WebSocket, payload: dict) -> None:
    try:
        await ws.send_json(payload)
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception as exc:
        logger.warning("WS send failed: %s", exc)


async def _safe_ws_close(ws: WebSocket, code: int = 1000, reason: str = "") -> None:
    with contextlib.suppress(AttributeError):
        await ws.close(code=code, reason=reason)


async def _generate_summary_and_save(session_id: str, ctx: ContextStore) -> None:
    summary = await generate_summary(ctx)
    await session_manager.set_summary(session_id, summary)


async def _handle_text_message(
    ws: WebSocket,
    msg: dict,
    orch: Orchestrator,
    session_id: str,
    ctx: ContextStore,
) -> bool:
    """处理客户端文本消息。返回 True 表示会话应该关闭。"""
    msg_type = msg.get("type")

    if msg_type == "ping":
        await _safe_send_json(ws, {"type": "pong"})
        return False

    if msg_type == "confirm":
        request_id = msg.get("request_id")
        if request_id:
            ok = await orch.confirm_analysis(request_id)
            await _safe_send_json(ws, {"type": "confirm_ack", "request_id": request_id, "ok": ok})
        return False

    if msg_type == "dismiss":
        request_id = msg.get("request_id")
        if request_id:
            await orch.dismiss_pending(request_id)
        return False

    if msg_type == "close":
        asyncio.create_task(_generate_summary_and_save(session_id, ctx))
        await session_manager.close_session(session_id)
        return True

    return False


@app.websocket("/ws/{session_id}")
async def legal_session(ws: WebSocket, session_id: str):
    await ws.accept()
    print(f"[WS] accepted sid={session_id}")

    # --- Session 获取 / 创建 / 恢复 ---
    state = await session_manager.get_state(session_id) or await session_manager.restore_session(session_id)
    if state is None:
        enrollment = await asyncio.to_thread(_session_enrollment)
        session_id = await session_manager.create_session(enrollment, session_id=session_id)
        state = await session_manager.get_state(session_id)
        print(f"[WS] new session created sid={session_id}")
    else:
        print(f"[WS] session restored sid={session_id} status={state.status}")

    # 排他连接：已有 WebSocket 时拒绝新连接
    if not await session_manager.attach_ws(session_id, ws):
        print(f"[WS] attach REJECTED sid={session_id} (1008)")
        await _safe_ws_close(ws, code=1008, reason="Session already connected")
        return
    print(f"[WS] attached sid={session_id}")

    # --- 恢复或新建 Agent 状态 ---
    if state.context_store and state.orchestrator:
        ctx = ContextStore.from_dict(state.context_store)
        orch = Orchestrator.from_dict(
            state.orchestrator, ctx=ctx, session_id=session_id, user_id="lawyer-default"
        )
    else:
        ctx = ContextStore()
        orch = Orchestrator(ctx, session_id=session_id, user_id="lawyer-default")

    bus = UtteranceBus(maxsize=10)
    orch.attach_bus(bus)

    async def on_suggestion(text, meta):
        try:
            if meta.get("kind") == "pending":
                await ws.send_json({
                    "type": "suggestion.pending",
                    "text": None,
                    "meta": {
                        "utt_id": meta["utt_id"],
                        "request_id": meta["request_id"],
                        "preview": meta.get("preview", {}),
                    },
                })
            else:
                await ws.send_json({
                    "type": "suggestion.ready",
                    "text": text,
                    "meta": {
                        "utt_id": meta["utt_id"],
                        **({"request_id": meta["request_id"]} if "request_id" in meta else {}),
                    },
                })
        except (WebSocketDisconnect, RuntimeError):
            # WS 已断开,不应崩溃也不必告警(常规连接关闭)
            pass
        except Exception as exc:
            logger.warning("Suggestion callback failed: %s", exc)

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
        # 包一层 try 把异常显式 log 出来。否则 stt_task 异常被 finally 里的
        # contextlib.suppress(Exception) 吞掉,排查时完全看不到。
        try:
            async for utt in stream_stt(audio_iter(), enrollment=enrollment):
                logger.info("STT produced utt: %s", utt.text[:50])
                await _safe_send_json(
                    ws,
                    {
                        "type": "transcript",
                        "id": utt.id,
                        "text": utt.text,
                        "t_start": utt.t_start,
                        "t_end": utt.t_end,
                        "speaker": utt.speaker,
                        "closed_by": utt.closed_by,
                        "is_final": True,
                    },
                )
                ok = await bus.put(utt)
                if not ok:
                    logger.warning("Utterance bus full, dropping utt %s", utt.id)
        except Exception:
            logger.exception("consume_stt died")
            raise

    stt_task = asyncio.create_task(consume_stt())
    print(f"[WS] entering receive loop sid={session_id}")

    # --- 主循环 ---
    try:
        while True:
            data = await ws.receive()

            if data["type"] == "websocket.disconnect":
                print(f"[WS] disconnect received sid={session_id} code={data.get('code')}")
                break

            if "bytes" in data:
                audio = np.frombuffer(data["bytes"], dtype=np.int16).astype(np.float32) / 32768.0
                if len(audio) > 0:
                    logger.info(
                        "WS recv bytes: len=%d, max=%.4f, min=%.4f", len(audio), float(audio.max()), float(audio.min())
                    )
                else:
                    logger.info("WS recv bytes: len=0 (empty chunk)")
                await audio_q.put((audio, time.monotonic() - t0))

            elif "text" in data:
                try:
                    msg = json.loads(data["text"])
                except json.JSONDecodeError:
                    await _safe_send_json(ws, {"type": "error", "message": "Invalid JSON"})
                    continue
                should_close = await _handle_text_message(ws, msg, orch, session_id, ctx)
                if should_close:
                    break

    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception as exc:
        logger.warning("WS main loop unexpected error: %s", exc, exc_info=True)
    finally:
        await audio_q.put(None)
        # 保存 Agent 状态 → SessionManager → 持久化
        # 无论 update_agent_state 是否成功，都必须 detach_ws，否则 _ws_map 泄漏
        state = await session_manager.get_state(session_id)
        if state is not None and state.status != "closed":
            with contextlib.suppress(Exception):
                await session_manager.update_agent_state(session_id, ctx, orch)
            with contextlib.suppress(Exception):
                await session_manager.detach_ws(session_id)
        with contextlib.suppress(Exception):
            await orch.shutdown()
        with contextlib.suppress(Exception):
            await stt_task
