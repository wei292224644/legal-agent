"""ContextStore — 对话上下文与画像的内存存储。

线程安全：generation 和 utterances 用 asyncio.Lock 保护；
profile 更新通过 asyncio.Queue 异步消费，避免阻塞主路径。
"""

import asyncio
import contextlib
from dataclasses import dataclass

from models.utterance import Utterance


@dataclass
class ProfileEntry:
    """画像条目：从对话中提取的法律事实。"""

    key: str
    value: str
    timestamp: float  # 用 utt.t_start（相对音频秒数），非 datetime
    source_utt_id: str
    confidence: float = 1.0
    category: str | None = None
    subject: str = ""  # 事实归属主体：本人 / 对方 / 第三方


class ContextStore:
    """上下文存储器。管理 utterance 历史、generation 计数和画像条目。"""

    def __init__(self):
        self._utterances: list[Utterance] = []
        self._profile: list[ProfileEntry] = []
        self._profile_queue: asyncio.Queue = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None
        self._generation = 0
        self._lock = asyncio.Lock()
        self._shutdown = False

    async def append_utterance(self, utt: Utterance) -> int:
        """追加发言，原子递增 generation，返回新的 generation 编号。"""
        async with self._lock:
            self._utterances.append(utt)
            self._generation += 1
            return self._generation

    def get_full_history(self) -> list[Utterance]:
        """获取完整对话历史（浅拷贝）。"""
        return list(self._utterances)

    def get_generation(self) -> int:
        """返回当前 generation 编号。"""
        return self._generation

    def get_recent_window(self, n: int = 8) -> list[Utterance]:
        """获取最近 n 轮对话。n <= 0 时返回空列表。"""
        if n <= 0:
            return []
        return self._utterances[-n:]

    async def start_profile_worker(self) -> None:
        """启动 profile worker 异步任务。幂等：已启动则跳过。"""
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._profile_worker())

    async def enqueue_profile_update(self, utt_id: str, entries: list[ProfileEntry]) -> None:
        """将画像更新放入队列，由 worker 异步消费。"""
        await self._profile_queue.put((utt_id, entries))

    def get_profile(self) -> list[ProfileEntry]:
        """获取全部画像条目（浅拷贝），按 timestamp 升序排列。"""
        return sorted(self._profile, key=lambda e: e.timestamp)

    def get_profile_keys(self) -> list[str]:
        """获取已提取的 key 列表，按 timestamp 降序去重，保留每个 key 的最新出现。"""
        sorted_profile = sorted(self._profile, key=lambda e: e.timestamp, reverse=True)
        return list(dict.fromkeys(e.key for e in sorted_profile))

    def get_profile_summary(self) -> dict[str, dict[str, str]]:
        """返回已知事实摘要，按 subject 分组，每个 (subject, key) 取最新值。

        形如 {"当事人": {"职业": "..."}, "对方": {"职业": "..."}}；
        未标注主体的条目归在 "" 分组下。同一 key 在不同 subject 下并存，不互相覆盖。
        """
        summary: dict[str, dict[str, str]] = {}
        for entry in self._profile:
            summary.setdefault(entry.subject, {})[entry.key] = entry.value
        return summary

    async def stop_profile_worker(self) -> None:
        """优雅关闭 profile worker：等待队列消费完毕再取消任务。"""
        self._shutdown = True
        if self._worker_task:
            try:
                await asyncio.wait_for(self._profile_queue.join(), timeout=2.0)
            except TimeoutError:
                pass
            self._worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker_task
            self._worker_task = None

    async def _profile_worker(self) -> None:
        """后台 worker：从队列消费画像更新并写入 self._profile。"""
        while not self._shutdown:
            try:
                utt_id, entries = await asyncio.wait_for(self._profile_queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            try:
                for entry in entries:
                    self._profile.append(entry)
            except Exception:
                # 单条解析失败不影响队列，继续消费下一条
                pass
            self._profile_queue.task_done()
