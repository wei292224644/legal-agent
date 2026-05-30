"""Utterance 仓储：插入与按 session 列出。"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Utterance as UtteranceRow
from models.utterance import Utterance


class UtteranceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def append(self, session_id: uuid.UUID, utt: Utterance) -> int:
        """插入一条 utterance，返回分配的 seq；session_id+seq 唯一约束确保不重号。"""
        next_seq = (
            await self._s.execute(
                select(func.coalesce(func.max(UtteranceRow.seq), 0) + 1).where(
                    UtteranceRow.session_id == session_id
                )
            )
        ).scalar_one()
        row = UtteranceRow(
            id=utt.id,
            session_id=session_id,
            seq=next_seq,
            text=utt.text,
            t_start=utt.t_start,
            t_end=utt.t_end,
            speaker=utt.speaker,
            closed_by=utt.closed_by,
            content_hash=utt.content_hash,
        )
        self._s.add(row)
        await self._s.commit()
        return next_seq

    async def list_by_session(self, session_id: uuid.UUID) -> list[Utterance]:
        stmt = (
            select(UtteranceRow)
            .where(UtteranceRow.session_id == session_id)
            .order_by(UtteranceRow.seq)
        )
        rows = (await self._s.execute(stmt)).scalars().all()
        return [
            Utterance(
                id=r.id, text=r.text, t_start=r.t_start, t_end=r.t_end,
                speaker=r.speaker, closed_by=r.closed_by,
            )
            for r in rows
        ]
