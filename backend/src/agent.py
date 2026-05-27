import asyncio
from collections import deque
from dataclasses import dataclass
from typing import Awaitable, Callable

from audio_pipeline import TranscriptResult


@dataclass
class IntentResult:
    intent_id: str
    question: str
    context: str


@dataclass
class AnalysisResult:
    category: str
    title: str
    content: str
    citation: str | None = None
    level: str | None = None


AnalyzeFn = Callable[
    [dict[str, list[dict]], list[TranscriptResult]],
    Awaitable[tuple[str, list[IntentResult | AnalysisResult]]],
]
ExecuteFn = Callable[[IntentResult, list[TranscriptResult]], Awaitable[list[AnalysisResult]]]


class LegalAgent:
    def __init__(
        self,
        on_intent: Callable[[IntentResult], Awaitable[None]],
        on_analysis: Callable[[AnalysisResult], Awaitable[None]],
        analyze_fn: AnalyzeFn,
        execute_fn: ExecuteFn,
    ):
        self._on_intent = on_intent
        self._on_analysis = on_analysis
        self._analyze_fn = analyze_fn
        self._execute_fn = execute_fn

        self._context_window: deque[TranscriptResult] = deque(maxlen=50)
        self._user_profile: dict[str, list[dict]] = {}
        self._facts_summary: str = ""

        self._pending_intents: dict[str, tuple[IntentResult, list[TranscriptResult]]] = {}
        self._executor_tasks: dict[str, asyncio.Task] = {}

    # ── Public ─────────────────────────────────────────────────────────────────

    async def observe(self, text: str, speaker: str) -> None:
        self._context_window.append(TranscriptResult(text=text, speaker=speaker))
        if speaker != "客户":
            return
        # fire-and-forget: never cancel, never wait
        asyncio.create_task(self._run_observer())

    async def confirm_intent(self, intent_id: str) -> None:
        stored = self._pending_intents.pop(intent_id, None)
        if stored is None:
            return
        intent, context = stored
        task = asyncio.create_task(self._run_executor(intent, context))
        self._executor_tasks[intent_id] = task

    def dismiss_intent(self, intent_id: str) -> None:
        self._pending_intents.pop(intent_id, None)

    # ── Internal ───────────────────────────────────────────────────────────────

    async def _run_observer(self) -> None:
        # Snapshot current state (other observers modify profile concurrently)
        profile = dict(self._user_profile)
        context = list(self._context_window)

        facts_summary, results = await self._analyze_fn(profile, context)
        if facts_summary:
            self._facts_summary = facts_summary

        for result in results:
            if isinstance(result, IntentResult):
                self._pending_intents[result.intent_id] = (result, context)
                await self._on_intent(result)
            else:
                await self._on_analysis(result)

    async def _run_executor(self, intent: IntentResult, context: list[TranscriptResult]) -> None:
        results = await self._execute_fn(intent, context)
        for result in results:
            await self._on_analysis(result)
        self._executor_tasks.pop(intent.intent_id, None)
