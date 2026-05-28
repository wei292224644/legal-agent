"""Orchestrator — wires ContextStore, IntentRouter, ProfileAgent, HeavyAgent."""

import asyncio
import time
import uuid
from dataclasses import dataclass, field

from agent.context_store import ContextStore
from agent.heavy_agent import HeavyAgent
from agent.intent_router import IntentRouter
from agent.profile_agent import ProfileAgent
from models.utterance import Utterance


@dataclass
class PendingRequest:
    request_id: str
    utt: Utterance
    intent_type: str
    generation: int
    meta: dict = field(default_factory=dict)


class Orchestrator:
    def __init__(
        self,
        ctx: ContextStore,
        ir: IntentRouter | None = None,
        pa: ProfileAgent | None = None,
        ha: HeavyAgent | None = None,
    ):
        self._ctx = ctx
        self._ir = ir or IntentRouter()
        self._pa = pa or ProfileAgent()
        self._ha = ha or HeavyAgent(ctx)
        self._suggestion_callback = None
        self._pending: dict[str, PendingRequest] = {}
        asyncio.create_task(self._ctx.start_profile_worker())

    def set_suggestion_callback(self, callback) -> None:
        self._suggestion_callback = callback

    async def handle_utterance(self, utt: Utterance) -> int:
        generation = await self._ctx.append_utterance(utt)

        ir_task = asyncio.create_task(
            self._ir.classify(text=utt.text, speaker=utt.speaker)
        )
        pa_task = asyncio.create_task(
            self._pa.extract(
                text=utt.text,
                speaker=utt.speaker,
                existing_keys=self._ctx.get_profile_keys(),
                utt_id=utt.id,
            )
        )

        pa_entries = await pa_task
        if pa_entries:
            await self._ctx.enqueue_profile_update(utt.id, pa_entries)

        ir_result = await ir_task

        if ir_result.severity == "ignore":
            return generation

        if not self._suggestion_callback:
            return generation

        meta = {
            "severity": ir_result.severity,
            "intent_type": ir_result.intent_type,
            "law_domain": ir_result.law_domain,
            "entities": ir_result.entities,
            "utt_id": utt.id,
        }

        if ir_result.severity == "simple":
            result = await self._ha.analyze_quick(
                utt, ir_result.intent_type, generation
            )
            if result is not None:
                meta["kind"] = "ready"
                await self._emit_suggestion(result, meta)
        else:
            request_id = f"req_{uuid.uuid4().hex[:8]}"
            self._pending[request_id] = PendingRequest(
                request_id=request_id,
                utt=utt,
                intent_type=ir_result.intent_type,
                generation=generation,
                meta=meta,
            )
            meta["kind"] = "pending"
            meta["request_id"] = request_id
            await self._emit_suggestion(None, meta)

        return generation

    async def confirm_analysis(self, request_id: str) -> bool:
        pending = self._pending.pop(request_id, None)
        if pending is None:
            return False

        result = await self._ha.analyze(
            pending.utt, pending.intent_type, pending.generation
        )
        if result is not None:
            pending.meta["kind"] = "ready"
            pending.meta["request_id"] = request_id
            await self._emit_suggestion(result, pending.meta)
        return True

    def dismiss_pending(self, request_id: str) -> None:
        self._pending.pop(request_id, None)

    async def shutdown(self) -> None:
        """清理资源：取消 profile worker，清空 pending。"""
        await self._ctx.stop_profile_worker()
        self._pending.clear()

    async def _emit_suggestion(self, text: str | None, meta: dict) -> None:
        cb_result = self._suggestion_callback(text, meta)
        if asyncio.iscoroutine(cb_result):
            await cb_result
