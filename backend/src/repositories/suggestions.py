"""Suggestion 仓储：用 (session_id, request_id) 作为业务幂等键 upsert。"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Suggestion


class SuggestionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def upsert_pending(
        self,
        session_id: uuid.UUID,
        *,
        utt_id: str,
        request_id: str,
        preview_topic: str | None,
        preview_rationale: str | None,
    ) -> None:
        row = await self._find(session_id, request_id)
        if row is None:
            self._s.add(Suggestion(
                id=uuid.uuid4(), session_id=session_id, utt_id=utt_id,
                request_id=request_id, kind="pending",
                preview_topic=preview_topic, preview_rationale=preview_rationale,
            ))
        else:
            row.kind = "pending"
            row.preview_topic = preview_topic
            row.preview_rationale = preview_rationale
            row.updated_at = datetime.now(timezone.utc)
        await self._s.commit()

    async def upsert_ready(
        self,
        session_id: uuid.UUID,
        *,
        request_id: str,
        text: str,
        utt_id: str | None = None,
    ) -> None:
        row = await self._find(session_id, request_id)
        if row is None:
            if utt_id is None:
                raise ValueError("upsert_ready without pending requires utt_id")
            self._s.add(Suggestion(
                id=uuid.uuid4(), session_id=session_id, utt_id=utt_id,
                request_id=request_id, kind="ready", text=text,
            ))
        else:
            row.kind = "ready"
            row.text = text
            row.updated_at = datetime.now(timezone.utc)
        await self._s.commit()

    async def _find(self, session_id: uuid.UUID, request_id: str) -> Suggestion | None:
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
                "kind": r.kind,
                "preview_topic": r.preview_topic,
                "preview_rationale": r.preview_rationale,
                "text": r.text,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
