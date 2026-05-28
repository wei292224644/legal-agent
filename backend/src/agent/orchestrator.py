"""Orchestrator — wires ContextStore, IntentRouter, ProfileAgent, HeavyAgent."""
import asyncio

from agent.context_store import ContextStore, Utterance
from agent.heavy_agent import HeavyAgent
from agent.intent_router import IntentRouter
from agent.profile_agent import ProfileAgent


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
        # Start profile worker so PA extracts are actually consumed
        asyncio.create_task(self._ctx.start_profile_worker())

    def set_suggestion_callback(self, callback) -> None:
        """callback(text: str, meta: dict) -> None | Coroutine"""
        self._suggestion_callback = callback

    async def handle_utterance(self, utt: Utterance) -> int:
        """Handle a new utterance: store it, run IR + PA in parallel, route."""
        generation = await self._ctx.append_utterance(utt)

        # Launch IR and PA in parallel (D1: IR + PA parallel)
        ir_task = asyncio.create_task(self._ir.classify(utt.text))
        pa_task = asyncio.create_task(
            self._pa.extract(
                text=utt.text,
                speaker=utt.speaker,
                existing_keys=self._ctx.get_profile_keys(),
                utt_id=utt.id,
            )
        )

        # PA path: enqueue results (fire-and-forget from caller perspective)
        pa_entries = await pa_task
        if pa_entries:
            await self._ctx.enqueue_profile_update(utt.id, pa_entries)

        # IR path: route decision
        ir_result = await ir_task
        if ir_result.intent in ("simple", "complex") and self._suggestion_callback:
            # Trigger HeavyAgent and emit suggestion
            result = await self._ha.analyze(utt, ir_result.intent, generation)
            if result is not None:
                cb_result = self._suggestion_callback(
                    result, {"intent": ir_result.intent, "utt_id": utt.id}
                )
                if asyncio.iscoroutine(cb_result):
                    asyncio.create_task(cb_result)

        return generation
