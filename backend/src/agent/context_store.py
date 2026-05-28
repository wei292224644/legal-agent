from dataclasses import dataclass
from datetime import datetime
import asyncio

from models.utterance import Utterance


@dataclass
class ProfileEntry:
    key: str
    value: str
    timestamp: datetime
    source_utt_id: str
    confidence: float = 1.0


class ContextStore:
    def __init__(self):
        self._utterances: list[Utterance] = []
        self._profile: list[ProfileEntry] = []
        self._profile_queue: asyncio.Queue = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None
        self._generation = 0
        self._lock = asyncio.Lock()
        self._shutdown = False

    async def append_utterance(self, utt: Utterance) -> int:
        async with self._lock:
            self._utterances.append(utt)
            self._generation += 1
            return self._generation

    def get_full_history(self) -> list[Utterance]:
        return list(self._utterances)

    def get_recent_window(self, n: int = 8) -> list[Utterance]:
        return self._utterances[-n:]

    async def start_profile_worker(self) -> None:
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._profile_worker())

    async def enqueue_profile_update(self, utt_id: str, entries: list[ProfileEntry]) -> None:
        await self._profile_queue.put((utt_id, entries))

    def get_profile(self) -> list[ProfileEntry]:
        return list(self._profile)

    def get_profile_keys(self) -> list[str]:
        return list(dict.fromkeys(e.key for e in self._profile))

    async def stop_profile_worker(self) -> None:
        self._shutdown = True
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None

    async def _profile_worker(self) -> None:
        while not self._shutdown:
            try:
                utt_id, entries = await asyncio.wait_for(self._profile_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            for entry in entries:
                self._profile.append(entry)
            self._profile_queue.task_done()
