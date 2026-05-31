"""SessionManager — 管理 Session 生命周期 + WS 排他 + TTL 清理。

持久化全交给 Repositories；本类只管 runtime（WS、status 镜像、内存 ctx/orch 引用）。
"""
from __future__ import annotations

import asyncio
import contextlib
import uuid

import numpy as np
from sqlalchemy.ext.asyncio import async_sessionmaker

from diarization.enrollment import Enrollment
from repositories.sessions import SessionRepository
from session.models import SessionRuntime


class SessionManager:
    """Session 生命周期管理器。"""

    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        *,
        ttl: float = 600.0,
        cleanup_interval: float = 60.0,
    ) -> None:
        self._maker = sessionmaker
        self._ttl = ttl
        self._cleanup_interval = cleanup_interval
        self._sessions: dict[uuid.UUID, SessionRuntime] = {}
        self._ws_map: dict[uuid.UUID, object] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """启动定期清理任务。"""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop(self) -> None:
        """停止定期清理。"""
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._cleanup_task
            self._cleanup_task = None

    # ------------------------------------------------------------------
    # Session CRUD
    # ------------------------------------------------------------------

    async def create_session(self) -> uuid.UUID:
        """创建新 session 并返回 session_id。不再接收 enrollment 参数。"""
        async with self._maker() as s:
            sid = await SessionRepository(s).create()
        async with self._lock:
            self._sessions[sid] = SessionRuntime(session_id=sid, status="active")
        return sid

    async def restore_session(self, session_id: uuid.UUID) -> SessionRuntime | None:
        """从 DB 恢复 session；不存在返回 None。"""
        async with self._maker() as s:
            row = await SessionRepository(s).get(session_id)
            if row is None:
                return None
        async with self._lock:
            runtime = self._sessions.get(session_id)
            if runtime is None:
                runtime = SessionRuntime(session_id=session_id, status="disconnected")
                self._sessions[session_id] = runtime
            else:
                runtime.status = "disconnected"
        return runtime

    async def get_runtime(self, session_id: uuid.UUID) -> SessionRuntime | None:
        """获取内存 runtime；不存在返回 None。"""
        async with self._lock:
            return self._sessions.get(session_id)

    # ------------------------------------------------------------------
    # WebSocket 排他连接
    # ------------------------------------------------------------------

    async def attach_ws(self, session_id: uuid.UUID, ws: object) -> object | None:
        """接管 WS 通道，返回旧 ws（若有）。同步更新 DB status 为 active。"""
        async with self._lock:
            old = self._ws_map.pop(session_id, None)
            self._ws_map[session_id] = ws
            runtime = self._sessions.get(session_id)
            if runtime is not None:
                runtime.status = "active"
        async with self._maker() as s:
            await SessionRepository(s).set_status(session_id, "active")
        return old

    async def detach_ws(self, session_id: uuid.UUID, ws: object | None = None) -> None:
        """WS 断开时标记 disconnected；ws 参数用于竞态保护。"""
        async with self._lock:
            if ws is not None and self._ws_map.get(session_id) is not ws:
                return
            self._ws_map.pop(session_id, None)
            runtime = self._sessions.get(session_id)
            if runtime is not None and runtime.status != "closed":
                runtime.status = "disconnected"
        async with self._maker() as s:
            row = await SessionRepository(s).get(session_id)
            if row is not None and row.status != "closed":
                await SessionRepository(s).set_status(session_id, "disconnected")

    async def close_session(self, session_id: uuid.UUID) -> None:
        """关闭会话（律师主动结束或超时）。"""
        async with self._lock:
            runtime = self._sessions.get(session_id)
            if runtime is not None:
                runtime.status = "closed"
            self._ws_map.pop(session_id, None)
        async with self._maker() as s:
            await SessionRepository(s).set_status(session_id, "closed")

    # ------------------------------------------------------------------
    # Summary / Runtime 绑定
    # ------------------------------------------------------------------

    async def set_summary(self, session_id: uuid.UUID, summary: str | None) -> None:
        """写入 AI 摘要到 DB。"""
        async with self._maker() as s:
            await SessionRepository(s).set_summary(session_id, summary)

    async def set_enrollment(
        self, session_id: uuid.UUID, enrollment: Enrollment
    ) -> None:
        """将 enrollment 写入 DB 并更新 runtime 缓存。"""
        embedding_list = enrollment.embedding.tolist()
        async with self._maker() as s:
            await SessionRepository(s).set_enrollment(session_id, embedding_list)
        async with self._lock:
            runtime = self._sessions.get(session_id)
            if runtime is not None:
                runtime.enrollment = enrollment

    async def get_enrollment(self, session_id: uuid.UUID) -> Enrollment | None:
        """获取 enrollment；先读热缓存，未命中再查 DB。"""
        async with self._lock:
            runtime = self._sessions.get(session_id)
            if runtime is not None and runtime.enrollment is not None:
                return runtime.enrollment

        async with self._maker() as s:
            row = await SessionRepository(s).get(session_id)
        if row is None or row.lawyer_embedding is None:
            return None

        enrollment = Enrollment(
            embedding=np.array(row.lawyer_embedding, dtype=np.float32)
        )
        async with self._lock:
            runtime = self._sessions.get(session_id)
            if runtime is not None:
                runtime.enrollment = enrollment
        return enrollment

    async def bind_runtime(self, session_id: uuid.UUID, *, ctx, orchestrator) -> None:
        """绑定 ContextStore / Orchestrator 实例到 runtime，WS 重连时复用。"""
        async with self._lock:
            runtime = self._sessions.get(session_id)
            if runtime is None:
                return
            runtime.ctx = ctx
            runtime.orchestrator = orchestrator

    # ------------------------------------------------------------------
    # 清理
    # ------------------------------------------------------------------

    async def _cleanup_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._cleanup_interval)
            except asyncio.CancelledError:
                break
            async with self._maker() as s:
                expired = await SessionRepository(s).list_expired_disconnected(self._ttl)
            async with self._lock:
                for sid in expired:
                    self._sessions.pop(sid, None)
                    self._ws_map.pop(sid, None)
