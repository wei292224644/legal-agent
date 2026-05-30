"""Session 仓储：封装 sessions 表的 CRUD。

设计：每个方法一次原子操作 + commit；调用方不需要管事务边界。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Session


class SessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create(self, *, session_id: uuid.UUID | None = None) -> uuid.UUID:
        sid = session_id or uuid.uuid4()
        self._s.add(Session(id=sid, status="active"))
        await self._s.commit()
        return sid

    async def get(self, session_id: uuid.UUID) -> Session | None:
        return await self._s.get(Session, session_id)

    async def set_status(self, session_id: uuid.UUID, status: str) -> None:
        row = await self._s.get(Session, session_id)
        if row is None:
            return
        row.status = status
        row.last_active_at = datetime.now(timezone.utc)
        if status == "closed":
            row.closed_at = datetime.now(timezone.utc)
        await self._s.commit()

    async def set_summary(self, session_id: uuid.UUID, summary: str | None) -> None:
        row = await self._s.get(Session, session_id)
        if row is None:
            return
        row.summary = summary
        await self._s.commit()

    async def touch(self, session_id: uuid.UUID) -> None:
        row = await self._s.get(Session, session_id)
        if row is None:
            return
        row.last_active_at = datetime.now(timezone.utc)
        await self._s.commit()

    async def list_expired_disconnected(self, ttl_seconds: float) -> list[uuid.UUID]:
        """返回 disconnected 且超过 TTL 的 session_id；供清理任务使用。"""
        from sqlalchemy import and_

        cutoff = datetime.now(timezone.utc).timestamp() - ttl_seconds
        stmt = select(Session.id).where(
            and_(
                Session.status == "disconnected",
                Session.last_active_at < datetime.fromtimestamp(cutoff, tz=timezone.utc),
            )
        )
        return list((await self._s.execute(stmt)).scalars().all())
