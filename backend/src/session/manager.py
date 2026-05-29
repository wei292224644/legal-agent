"""SessionManager — 管理 Session 生命周期、排他连接、快照与 TTL。

核心职责：
- create_session / restore_session
- attach_ws（排他连接）/ detach_ws（触发快照）
- update_agent_state（将 Agent 状态写回 SessionState）
- 定期快照 + 断开快照
- TTL 清理过期 disconnected session
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid

from agent.context_store import ContextStore
from agent.orchestrator import Orchestrator
from diarization.enrollment import Enrollment
from session.models import SessionState
from session.persistence import PersistenceBackend
from session.serializer import SessionSerializer


class SessionManager:
    """Session 生命周期管理器。"""

    def __init__(
        self,
        backend: PersistenceBackend,
        *,
        snapshot_interval: float = 60.0,
        ttl: float = 600.0,
    ) -> None:
        self._backend = backend
        self._snapshot_interval = snapshot_interval
        self._ttl = ttl

        self._sessions: dict[str, SessionState] = {}
        self._ws_map: dict[str, object] = {}  # session_id → WebSocket（只存引用，不序列化）
        self._lock = asyncio.Lock()
        self._snapshot_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """启动定期快照任务。"""
        if self._snapshot_task is None:
            self._snapshot_task = asyncio.create_task(self._snapshot_loop())

    async def stop(self) -> None:
        """停止定期快照，并快照所有活跃 session。"""
        if self._snapshot_task is not None:
            self._snapshot_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._snapshot_task
            self._snapshot_task = None
        await self._snapshot_all()

    # ------------------------------------------------------------------
    # Session CRUD
    # ------------------------------------------------------------------

    async def create_session(
        self,
        enrollment: Enrollment,
        session_id: str | None = None,
    ) -> str:
        """创建新 session，返回 session_id。

        session_id 为空时自动生成 UUID；前端已持有 ID 时直接复用。
        """
        sid = session_id or str(uuid.uuid4())
        state = SessionState(
            session_id=sid,
            enrollment=SessionSerializer.enrollment_to_dict(enrollment),
        )
        async with self._lock:
            self._sessions[sid] = state
        return sid

    async def restore_session(self, session_id: str) -> SessionState | None:
        """从持久化恢复 session；不存在时返回 None。

        恢复后状态为 disconnected，等待 WebSocket attach。
        """
        data = self._backend.load(session_id)
        if data is None:
            return None
        state = SessionSerializer.from_dict(data)
        state.status = "disconnected"
        async with self._lock:
            self._sessions[session_id] = state
        return state

    async def get_state(self, session_id: str) -> SessionState | None:
        """获取 session 状态。"""
        async with self._lock:
            return self._sessions.get(session_id)

    async def close_session(self, session_id: str) -> SessionState | None:
        """关闭 session（律师主动结束或超时），触发最终快照。"""
        async with self._lock:
            state = self._sessions.get(session_id)
            if state is None:
                return None
            state.status = "closed"
            self._ws_map.pop(session_id, None)

        await self._snapshot(session_id)
        return state

    # ------------------------------------------------------------------
    # WebSocket 排他连接
    # ------------------------------------------------------------------

    async def attach_ws(self, session_id: str, ws: object) -> bool:
        """将 WebSocket 绑定到 session。排他连接：已有连接返回 False。"""
        async with self._lock:
            state = self._sessions.get(session_id)
            if state is None:
                return False
            if session_id in self._ws_map:
                return False
            self._ws_map[session_id] = ws
            state.status = "active"
            state.touch()
            return True

    async def detach_ws(self, session_id: str) -> None:
        """WebSocket 断开，标记 disconnected 并立即触发快照。"""
        async with self._lock:
            self._ws_map.pop(session_id, None)
            state = self._sessions.get(session_id)
            if state is not None:
                state.status = "disconnected"
                state.touch()

        await self._snapshot(session_id)

    # ------------------------------------------------------------------
    # Agent 状态同步
    # ------------------------------------------------------------------

    async def update_agent_state(
        self,
        session_id: str,
        ctx: ContextStore,
        orch: Orchestrator,
    ) -> None:
        """将 Agent 运行时状态写回 SessionState（内存中）。"""
        async with self._lock:
            state = self._sessions.get(session_id)
            if state is None:
                return
            state.context_store = ctx.to_dict()
            state.orchestrator = orch.to_dict()
            state.touch()

    # ------------------------------------------------------------------
    # 快照与清理
    # ------------------------------------------------------------------

    async def _snapshot(self, session_id: str) -> None:
        """将指定 session 快照到持久化后端。"""
        async with self._lock:
            state = self._sessions.get(session_id)
            if state is None:
                return
            data = SessionSerializer.to_dict(state)

        # 锁外执行 IO，避免阻塞其他 session
        self._backend.save(session_id, data)

    async def _snapshot_all(self) -> None:
        """快照所有内存中的 session。"""
        async with self._lock:
            states = list(self._sessions.items())

        for session_id, state in states:
            data = SessionSerializer.to_dict(state)
            self._backend.save(session_id, data)

    async def _snapshot_loop(self) -> None:
        """后台任务：定期快照所有 active session。"""
        while True:
            try:
                await asyncio.sleep(self._snapshot_interval)
            except asyncio.CancelledError:
                break

            async with self._lock:
                active_ids = [
                    sid
                    for sid, s in self._sessions.items()
                    if s.status == "active"
                ]

            for sid in active_ids:
                await self._snapshot(sid)

    async def cleanup_expired(self) -> None:
        """清理超过 TTL 的 disconnected session。"""
        now = time.monotonic()
        async with self._lock:
            expired = [
                sid
                for sid, s in self._sessions.items()
                if s.status == "disconnected" and (now - s.last_active_at) > self._ttl
            ]
            for sid in expired:
                self._sessions.pop(sid, None)
                self._ws_map.pop(sid, None)
