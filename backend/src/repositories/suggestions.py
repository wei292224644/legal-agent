"""Suggestion 仓储：直接洞察（direct）与深度分析（gated）的统一持久化。

gated 生命周期: pending → running → ready / expired / dismissed
direct 生命周期: 直接 ready，无 request_id,无确认流程
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Suggestion


class SuggestionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    # ── gated: pending ────────────────────────────────────────────

    async def upsert_pending(
        self,
        session_id: uuid.UUID,
        *,
        utt_id: str,
        request_id: str,
        preview_topic: str | None,
        preview_rationale: str | None,
    ) -> None:
        row = await self._find_gated(session_id, request_id)
        if row is None:
            self._s.add(Suggestion(
                id=uuid.uuid4(), session_id=session_id, utt_id=utt_id,
                request_id=request_id, source="gated", status="pending",
                preview_topic=preview_topic, preview_rationale=preview_rationale,
            ))
        else:
            row.status = "pending"
            row.preview_topic = preview_topic
            row.preview_rationale = preview_rationale
        await self._s.commit()

    # ── gated: 状态切换 ────────────────────────────────────────────

    async def mark_running(self, session_id: uuid.UUID, request_id: str) -> None:
        """用户点击确认后标记为执行中。"""
        row = await self._find_gated(session_id, request_id)
        if row is None:
            return
        row.status = "running"
        row.confirmed_at = datetime.now(UTC)
        await self._s.commit()

    async def upsert_ready(
        self,
        session_id: uuid.UUID,
        *,
        request_id: str,
        text: str,
        utt_id: str | None = None,
    ) -> None:
        """gated 分析结果就绪。没有 pending 行时兜底新建（进程重启后 pending 丢失）。"""
        row = await self._find_gated(session_id, request_id)
        if row is None:
            if utt_id is None:
                raise ValueError("upsert_ready without pending requires utt_id")
            self._s.add(Suggestion(
                id=uuid.uuid4(), session_id=session_id, utt_id=utt_id,
                request_id=request_id, source="gated", status="ready", text=text,
            ))
        else:
            row.status = "ready"
            row.text = text
        await self._s.commit()

    async def mark_dismissed(self, session_id: uuid.UUID, request_id: str) -> None:
        row = await self._find_gated(session_id, request_id)
        if row is None:
            return
        row.status = "dismissed"
        await self._s.commit()

    async def mark_expired(self, session_id: uuid.UUID, request_id: str) -> None:
        row = await self._find_gated(session_id, request_id)
        if row is None:
            return
        row.status = "expired"
        await self._s.commit()

    # ── direct: 实时洞察（无 request_id,无确认流程）────────────────

    async def insert_direct(
        self, session_id: uuid.UUID, *, utt_id: str, text: str,
    ) -> None:
        self._s.add(Suggestion(
            id=uuid.uuid4(), session_id=session_id, utt_id=utt_id,
            request_id=None, source="direct", status="ready", text=text,
        ))
        await self._s.commit()

    # ── 查询 ─────────────────────────────────────────────────────

    async def _find_gated(self, session_id: uuid.UUID, request_id: str) -> Suggestion | None:
        stmt = select(Suggestion).where(
            Suggestion.session_id == session_id,
            Suggestion.request_id == request_id,
        )
        return (await self._s.execute(stmt)).scalar_one_or_none()

    async def list_by_session(self, session_id: uuid.UUID) -> list[dict]:
        stmt = (
            select(Suggestion)
            .where(Suggestion.session_id == session_id)
            .order_by(Suggestion.created_at)
        )
        rows = (await self._s.execute(stmt)).scalars().all()
        return [
            {
                "id": str(r.id),
                "utt_id": r.utt_id,
                "request_id": r.request_id,
                "source": r.source,
                "status": r.status,
                "preview_topic": r.preview_topic,
                "preview_rationale": r.preview_rationale,
                "text": r.text,
                "error": r.error,
                "confirmed_at": r.confirmed_at.isoformat() if r.confirmed_at else None,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
