"""UtteranceBus — 事件总线，解耦 STT 与 Agent."""

from __future__ import annotations

import asyncio

from models.utterance import Utterance


class UtteranceBus:
    """有界异步队列，承载 Utterance 事件."""

    def __init__(self, maxsize: int = 10) -> None:
        self._q: asyncio.Queue[Utterance] = asyncio.Queue(maxsize=maxsize)

    async def put(self, utt: Utterance) -> bool:
        """投递 utterance. 成功返回 True，队列满返回 False（不阻塞、不丢弃旧数据）."""
        try:
            self._q.put_nowait(utt)
            return True
        except asyncio.QueueFull:
            return False

    async def get(self) -> Utterance:
        """阻塞等待并返回下一个 utterance."""
        return await self._q.get()
