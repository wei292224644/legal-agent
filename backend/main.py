import asyncio
import contextlib
import io
import json
import logging
import sys
import time
import uuid
from pathlib import Path

import numpy as np
import soundfile as sf
from fastapi import FastAPI, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import async_sessionmaker

sys.path.insert(0, str(Path(__file__).parent / "src"))
from agent.bus import UtteranceBus  # noqa: E402
from agent.context_store import ContextStore  # noqa: E402
from agent.events import (  # noqa: E402
    ConfirmAck,
    ErrorEvent,
    OutboundEvent,
    Pong,
    TranscriptDelta,
)
from agent.orchestrator import Orchestrator  # noqa: E402
from agent.relevance_gate import load_relevance_model  # noqa: E402
from db.engine import create_engine_from_env, get_sessionmaker  # noqa: E402
from diarization.enrollment import Enrollment, enroll_speaker  # noqa: E402
from repositories.suggestions import SuggestionRepository  # noqa: E402
from session.manager import SessionManager  # noqa: E402
from session.summary import generate_summary  # noqa: E402
from stt.funasr_stream import stream_stt  # noqa: E402

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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

session_manager: SessionManager | None = None
_maker: async_sessionmaker | None = None


async def _load_session_enrollment(sid: uuid.UUID) -> Enrollment | None:
    """从 SessionManager 加载 session 绑定的 enrollment。"""
    if session_manager is None:
        return None
    return await session_manager.get_enrollment(sid)


@app.post("/api/sessions")
async def create_session():
    """创建新会话并返回 session_id。前端拿到 id 后通过 WS 连接。"""
    session_id = await session_manager.create_session()
    return {"session_id": session_id}


@app.get("/api/sessions/{session_id}/history")
async def get_history(session_id: str):
    """返回 session 的完整历史（utterances + suggestions + profile），供前端刷新回放。"""
    from repositories.profile_entries import ProfileEntryRepository
    from repositories.sessions import SessionRepository
    from repositories.suggestions import SuggestionRepository
    from repositories.utterances import UtteranceRepository

    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的 session_id 格式") from None

    async with _maker() as s:
        row = await SessionRepository(s).get(sid)
        if row is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        utts = await UtteranceRepository(s).list_by_session(sid)
        sugs = await SuggestionRepository(s).list_by_session(sid)
        profile_entries = await ProfileEntryRepository(s).list_by_session(sid)

    return {
        "session_id": str(sid),
        "status": row.status,
        "utterances": [
            {
                "id": u.id, "text": u.text, "t_start": u.t_start,
                "t_end": u.t_end, "speaker": u.speaker, "closed_by": u.closed_by,
            } for u in utts
        ],
        "suggestions": sugs,
        "profile_entries": [
            {
                "key": e.key,
                "value": e.value,
                "subject": e.subject,
                "category": e.category or "fact",
                "timestamp": e.timestamp,
                "source_utt_id": e.source_utt_id or "",
            }
            for e in profile_entries
        ],
    }


@app.post("/api/sessions/{session_id}/enrollment")
async def upload_enrollment(session_id: str, audio: UploadFile):
    """上传律师声纹音频并绑定到 session。"""
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的 session_id 格式") from None

    from repositories.sessions import SessionRepository

    async with _maker() as s:
        row = await SessionRepository(s).get(sid)
        if row is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        if row.status == "closed":
            raise HTTPException(status_code=400, detail="会话已结束")

    contents = await audio.read()
    try:
        with io.BytesIO(contents) as bio:
            pcm, sr = sf.read(bio, dtype="float32", always_2d=False)
    except Exception:
        raise HTTPException(status_code=400, detail="音频文件无法解析") from None

    if pcm.ndim == 2:
        pcm = pcm.mean(axis=1)

    if len(pcm) / sr < 1.0:
        raise HTTPException(status_code=400, detail="音频过短")

    try:
        enrollment = await asyncio.to_thread(enroll_speaker, pcm, sr)
    except Exception:
        logger.exception("enroll_speaker failed")
        raise HTTPException(status_code=500, detail="声纹处理失败") from None

    await session_manager.set_enrollment(sid, enrollment)
    await audio.close()
    return {"ok": True}


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    """获取 session 基本信息。"""
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的 session_id 格式") from None

    from repositories.sessions import SessionRepository

    async with _maker() as s:
        row = await SessionRepository(s).get(sid)
        if row is None:
            raise HTTPException(status_code=404, detail="会话不存在")

    return {
        "session_id": str(row.id),
        "status": row.status,
        "has_enrollment": row.lawyer_embedding is not None,
    }


@app.on_event("startup")
async def _startup() -> None:
    # 预加载 BERT 模型。硬依赖：失败即阻止服务启动。
    load_relevance_model()

    global session_manager, _maker
    import db.models  # noqa: E402, F401
    from db.base import Base  # noqa: E402

    engine = create_engine_from_env()
    # 确保表存在——测试套件跑完后可能已 drop_all
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    _maker = get_sessionmaker(engine)
    session_manager = SessionManager(_maker, ttl=600.0)
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


async def _send_event(ws: WebSocket, evt: OutboundEvent) -> None:
    await _safe_send_json(ws, evt.model_dump())


async def _safe_ws_close(ws: WebSocket, code: int = 1000, reason: str = "") -> None:
    with contextlib.suppress(AttributeError, RuntimeError):
        await ws.close(code=code, reason=reason)


async def _generate_summary_and_save(session_id: uuid.UUID, ctx: ContextStore) -> None:
    summary = await generate_summary(ctx)
    await session_manager.set_summary(session_id, summary)


class _DbRepoWriter:
    """绑定 sessionmaker + session_id 的 SuggestionRepository facade,
    给 Orchestrator 注入。每次调用打开一个独立 session,与 ws 生命周期解耦。"""

    def __init__(self, sessionmaker: async_sessionmaker, session_id: uuid.UUID) -> None:
        self._sm = sessionmaker
        self._sid = session_id

    async def insert_direct(self, *, utt_id: str, text: str) -> None:
        async with self._sm() as s:
            await SuggestionRepository(s).insert_direct(
                self._sid, utt_id=utt_id, text=text,
            )

    async def upsert_pending(self, *, utt_id: str, request_id: str,
                              preview_topic: str | None, preview_rationale: str | None) -> None:
        async with self._sm() as s:
            await SuggestionRepository(s).upsert_pending(
                self._sid, utt_id=utt_id, request_id=request_id,
                preview_topic=preview_topic, preview_rationale=preview_rationale,
            )

    async def mark_running(self, request_id: str) -> None:
        async with self._sm() as s:
            await SuggestionRepository(s).mark_running(self._sid, request_id)

    async def upsert_ready(self, *, request_id: str, text: str,
                            utt_id: str | None) -> None:
        async with self._sm() as s:
            await SuggestionRepository(s).upsert_ready(
                self._sid, request_id=request_id, text=text, utt_id=utt_id,
            )

    async def mark_dismissed(self, request_id: str) -> None:
        async with self._sm() as s:
            await SuggestionRepository(s).mark_dismissed(self._sid, request_id)

    async def mark_expired(self, request_id: str) -> None:
        async with self._sm() as s:
            await SuggestionRepository(s).mark_expired(self._sid, request_id)


async def _handle_text_message(
    ws: WebSocket,
    msg: dict,
    orch: Orchestrator,
    session_id: uuid.UUID,
    ctx: ContextStore,
    audio_q: asyncio.Queue[tuple[np.ndarray, float] | None] | None,
) -> bool:
    """处理客户端文本消息。返回 True 表示会话应该关闭。"""
    msg_type = msg.get("type")

    if msg_type == "ping":
        await _send_event(ws, Pong())
        return False

    if msg_type == "confirm":
        request_id = msg.get("request_id")
        if request_id:
            ok = await orch.confirm_analysis(request_id)
            await _send_event(ws, ConfirmAck(request_id=request_id, ok=ok))
        return False

    if msg_type == "dismiss":
        request_id = msg.get("request_id")
        if request_id:
            await orch.dismiss_pending(request_id)
        return False

    if msg_type == "audio_end":
        if audio_q is not None:
            with contextlib.suppress(Exception):
                await audio_q.put(None)
        return False

    if msg_type == "close":
        asyncio.create_task(_generate_summary_and_save(session_id, ctx))
        await session_manager.close_session(session_id)
        return True

    return False


@app.websocket("/ws/{session_id}")
async def legal_session(ws: WebSocket, session_id: str):
    await ws.accept()
    logger.info("[WS] accepted sid=%s", session_id)

    # --- Session 验证 ---
    try:
        sid_uuid = uuid.UUID(session_id)
    except ValueError:
        logger.warning("[WS] invalid session_id sid=%s (4002)", session_id)
        await _safe_ws_close(ws, code=4002, reason="会话不存在")
        return

    runtime = await session_manager.get_runtime(sid_uuid) or await session_manager.restore_session(sid_uuid)
    if runtime is None:
        logger.warning("[WS] session not found sid=%s (4002)", session_id)
        await _safe_ws_close(ws, code=4002, reason="会话不存在")
        return
    if runtime.status == "closed":
        logger.warning("[WS] session closed sid=%s (4001)", session_id)
        await _safe_ws_close(ws, code=4001, reason="会话已结束")
        return
    logger.info("[WS] session loaded sid=%s status=%s", session_id, runtime.status)

    # 后来者接管：关掉旧 WS（若存在），本连接接管
    old_ws = await session_manager.attach_ws(sid_uuid, ws)
    if old_ws is not None:
        logger.info("[WS] replacing old ws sid=%s", session_id)
        await _safe_ws_close(old_ws, code=4000, reason="已被新连接接管")
    logger.info("[WS] attached sid=%s", session_id)

    # attach 成功后所有路径都必须保证 detach_ws 被调用。
    # 传入 ws 防止竞态：若新连接已替换 _ws_map 引用，旧 finally 不应误删新连接。
    ctx: ContextStore | None = None
    orch: Orchestrator | None = None
    audio_q: asyncio.Queue[tuple[np.ndarray, float] | None] | None = None
    stt_task: asyncio.Task | None = None
    try:
        # --- 恢复或新建 Agent 状态 ---
        if runtime.ctx is not None and runtime.orchestrator is not None:
            ctx = runtime.ctx
            orch = runtime.orchestrator
        else:
            ctx = ContextStore(session_id=sid_uuid, sessionmaker=_maker)
            orch = Orchestrator(ctx, session_id=session_id, user_id="lawyer-default")
            await session_manager.bind_runtime(sid_uuid, ctx=ctx, orchestrator=orch)

        bus = UtteranceBus(maxsize=10)
        orch.attach_bus(bus)

        orch.set_event_emitter(lambda evt: _send_event(ws, evt))
        orch.set_repo_writer(_DbRepoWriter(_maker, sid_uuid))
        await orch.start()

        # --- 音频管道 ---
        enrollment = await _load_session_enrollment(sid_uuid)
        if enrollment is None:
            logger.warning("[WS] no enrollment for sid=%s (4003)", session_id)
            await _safe_ws_close(ws, code=4003, reason="请先录制声纹")
            return
        audio_q = asyncio.Queue()
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
                    await _send_event(ws, TranscriptDelta(
                        utt_id=utt.id,
                        speaker=utt.speaker or "uncertain",
                        text=utt.text,
                        t_start=utt.t_start,
                        t_end=utt.t_end,
                        closed_by=utt.closed_by,
                    ))
                    ok = await bus.put(utt)
                    if not ok:
                        logger.warning("Utterance bus full, dropping utt %s", utt.id)
            except Exception:
                logger.exception("consume_stt died")
                raise

        stt_task = asyncio.create_task(consume_stt())
        logger.info("[WS] entering receive loop sid=%s", session_id)

        # --- 主循环 ---
        while True:
            data = await ws.receive()

            if data["type"] == "websocket.disconnect":
                logger.info("[WS] disconnect received sid=%s code=%s", session_id, data.get("code"))
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
                    await _send_event(ws, ErrorEvent(message="Invalid JSON"))
                    continue
                should_close = await _handle_text_message(ws, msg, orch, sid_uuid, ctx, audio_q)
                if should_close:
                    break

    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception:
        logger.exception("WS handler error sid=%s", session_id)
    finally:
        # 按"启动反序"清理,且每段独立 guard —— setup 异常时只清理已建立的部分。
        # suppress 范围收窄:只忽略预期异常,编程错误(Na​​meError/SyntaxError 等)仍暴露。
        _cleanup_exc = (RuntimeError, asyncio.CancelledError, OSError, AttributeError)
        if audio_q is not None:
            with contextlib.suppress(*_cleanup_exc):
                await audio_q.put(None)
        if stt_task is not None:
            with contextlib.suppress(*_cleanup_exc):
                await stt_task
        if orch is not None:
            with contextlib.suppress(*_cleanup_exc):
                await orch.shutdown()
        if ctx is not None and orch is not None:
            cur = await session_manager.get_runtime(sid_uuid)
            if cur is not None and cur.status != "closed":
                with contextlib.suppress(*_cleanup_exc):
                    await session_manager.bind_runtime(sid_uuid, ctx=ctx, orchestrator=orch)
        # detach_ws 必须执行，传入 ws 防止竞态。
        with contextlib.suppress(*_cleanup_exc):
            await session_manager.detach_ws(sid_uuid, ws)
