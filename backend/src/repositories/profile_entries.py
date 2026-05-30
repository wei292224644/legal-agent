"""ProfileEntry 仓储：批量写入与按 session 列出。"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent.context_store import ProfileEntry
from db.models import ProfileEntry as ProfileEntryRow


class ProfileEntryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def bulk_insert(self, session_id: uuid.UUID, entries: list[ProfileEntry]) -> None:
        for e in entries:
            self._s.add(ProfileEntryRow(
                id=uuid.uuid4(),
                session_id=session_id,
                source_utt_id=e.source_utt_id,
                key=e.key,
                value=e.value,
                timestamp=e.timestamp,
                confidence=e.confidence,
                category=e.category,
                subject=e.subject,
            ))
        await self._s.commit()

    async def list_by_session(self, session_id: uuid.UUID) -> list[ProfileEntry]:
        stmt = (
            select(ProfileEntryRow)
            .where(ProfileEntryRow.session_id == session_id)
            .order_by(ProfileEntryRow.timestamp)
        )
        rows = (await self._s.execute(stmt)).scalars().all()
        return [
            ProfileEntry(
                key=r.key, value=r.value, timestamp=r.timestamp,
                source_utt_id=r.source_utt_id or "", confidence=r.confidence,
                category=r.category, subject=r.subject,
            )
            for r in rows
        ]
