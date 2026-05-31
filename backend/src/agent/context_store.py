"""ContextStore — 对话上下文与画像的内存视图 + DB 写穿。

设计：
- 读路径：内存 list（避免每条 utterance 来时走 DB）。
- 写路径：内存 + DB 同步写，每次开短事务。
- 启动/恢复：调用 hydrate() 从 DB 加载历史。

DB 是真值源；内存是 cache。刷新 / 重启后通过 hydrate 重建。
"""
import asyncio
import contextlib
import logging
import uuid as _uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import async_sessionmaker

from models.utterance import Utterance

logger = logging.getLogger(__name__)


@dataclass
class ProfileEntry:
    """画像条目：从对话中提取的法律事实。"""

    key: str
    value: str
    timestamp: float         # 用 utt.t_start（相对音频秒数），非 datetime
    source_utt_id: str
    confidence: float = 1.0
    category: str | None = None
    subject: str = ""        # 事实归属主体：本人 / 对方 / 第三方


class ContextStore:
    """上下文存储器。管理 utterance 历史、generation 计数和画像条目。"""

    def __init__(
        self,
        *,
        session_id: _uuid.UUID,
        sessionmaker: async_sessionmaker,
    ) -> None:
        self._session_id = session_id
        self._maker = sessionmaker
        self._utterances: list[Utterance] = []
        self._profile: list[ProfileEntry] = []
        self._recent_suggestions: list[str] = []
        self._profile_queue: asyncio.Queue = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None
        self._generation = 0
        self._lock = asyncio.Lock()
        self._shutdown = False

    # 仅供 prompt 上下文使用，防止 child 重复同一话题快答；超过窗口即丢，无需持久化。
    _RECENT_SUGGESTIONS_CAP = 6

    async def hydrate(self) -> None:
        """从 DB 加载 utterances + profile——恢复内存 cache 视图。"""
        from repositories.profile_entries import ProfileEntryRepository
        from repositories.utterances import UtteranceRepository

        async with self._maker() as s:
            utts = await UtteranceRepository(s).list_by_session(self._session_id)
            profile = await ProfileEntryRepository(s).list_by_session(self._session_id)
        async with self._lock:
            self._utterances = utts
            self._profile = profile
            self._generation = len(utts)

    async def append_utterance(self, utt: Utterance) -> int:
        """追加发言到 DB + 内存，原子递增 generation。"""
        from repositories.utterances import UtteranceRepository

        async with self._maker() as s:
            await UtteranceRepository(s).append(self._session_id, utt)
        async with self._lock:
            self._utterances.append(utt)
            self._generation += 1
            return self._generation

    def get_full_history(self) -> list[Utterance]:
        """完整对话历史（浅拷贝）。"""
        return list(self._utterances)

    def get_generation(self) -> int:
        """当前 generation 编号。"""
        return self._generation

    def get_recent_window(self, n: int = 8) -> list[Utterance]:
        """最近 n 轮对话。n <= 0 返回空。"""
        if n <= 0:
            return []
        return self._utterances[-n:]

    async def start_profile_worker(self) -> None:
        """启动 profile worker。幂等。"""
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._profile_worker())

    async def enqueue_profile_update(self, utt_id: str, entries: list[ProfileEntry]) -> None:
        """入队画像更新，由 worker 异步消费。"""
        await self._profile_queue.put((utt_id, entries))

    def get_profile(self) -> list[ProfileEntry]:
        """全部画像条目，按 timestamp 升序。"""
        return sorted(self._profile, key=lambda e: e.timestamp)

    def get_profile_keys(self) -> list[str]:
        """已提取 key 列表，按 timestamp 降序去重。"""
        sorted_p = sorted(self._profile, key=lambda e: e.timestamp, reverse=True)
        return list(dict.fromkeys(e.key for e in sorted_p))

    def record_suggestion(self, text: str) -> None:
        """记录一条已发出的快答文本，仅保留最近 N 条用于后续 prompt 去重提示。"""
        text = (text or "").strip()
        if not text:
            return
        self._recent_suggestions.append(text)
        if len(self._recent_suggestions) > self._RECENT_SUGGESTIONS_CAP:
            del self._recent_suggestions[: len(self._recent_suggestions) - self._RECENT_SUGGESTIONS_CAP]

    def get_recent_suggestions(self, n: int = 3) -> list[str]:
        """最近 n 条已发快答，按时间升序（最早在前）。n<=0 返回空。"""
        if n <= 0:
            return []
        return list(self._recent_suggestions[-n:])

    def get_profile_summary(self) -> dict[str, dict[str, str]]:
        """已知事实摘要，按 subject 分组，(subject, key) 取最新值。"""
        summary: dict[str, dict[str, str]] = {}
        for entry in self._profile:
            summary.setdefault(entry.subject, {})[entry.key] = entry.value
        return summary

    async def stop_profile_worker(self) -> None:
        """优雅关闭 profile worker。"""
        self._shutdown = True
        if self._worker_task:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._profile_queue.join(), timeout=2.0)
            self._worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker_task
            self._worker_task = None

    async def _profile_worker(self) -> None:
        """后台消费画像队列，写入 DB + 内存。"""
        while not self._shutdown:
            try:
                utt_id, entries = await asyncio.wait_for(
                    self._profile_queue.get(), timeout=1.0
                )
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            try:
                from repositories.profile_entries import ProfileEntryRepository

                async with self._maker() as s:
                    await ProfileEntryRepository(s).bulk_insert(
                        self._session_id, entries
                    )
                self._profile.extend(entries)
            except Exception as exc:
                logger.warning("Profile worker dropped entry: %s", exc, exc_info=True)
            self._profile_queue.task_done()
