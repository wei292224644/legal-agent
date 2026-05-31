"""Orchestrator — 纯机械管道:零语义判断,只对 RelevanceGate 与 child run 状态反应。

控制流:
1. 每条 utterance → append context(单写者), 并行触发 gate + PA(仅 client 句)
2. PA 结果异步入画像写口(单写者)
3. gate=true → spawn child run(并发); gate=false → 仅记录,不响应
4. child run 完成:
   - 未 paused → 直推 ready(stale generation 时丢弃)
   - paused(踩了 gated deep_analysis)→ emit pending,等律师 confirm
5. confirm → continue_run 续跑同一 run;dismiss/超时 → abandon
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from agent.events import (
    OutboundEvent, ProfileUpdated, ProfileEntryPayload, InsightReady,
    AnalysisProposed,
)

from agno.run.base import RunStatus

from agent.context_store import ContextStore
from agent.heavy_agent import HeavyAgent
from agent.profile_agent import ProfileAgent
from agent.relevance_gate import RelevanceGate
from config import RUN_TIMEOUT
from models.utterance import Utterance

logger = logging.getLogger(__name__)

PROFILE_WINDOW_SIZE = 6


class _RepoWriter(Protocol):
    """Orchestrator 写 DB 用的最小接口。main.py 注入一个绑定 sessionmaker
    + session_id 的实现；测试注入 FakeRepoWriter。"""
    async def insert_direct(self, *, utt_id: str, text: str) -> None: ...
    async def upsert_pending(self, *, utt_id: str, request_id: str,
                              preview_topic: str | None,
                              preview_rationale: str | None) -> None: ...
    async def mark_running(self, request_id: str) -> None: ...
    async def upsert_ready(self, *, request_id: str, text: str,
                            utt_id: str | None) -> None: ...
    async def mark_dismissed(self, request_id: str) -> None: ...
    async def mark_expired(self, request_id: str) -> None: ...


@dataclass
class PendingRequest:
    """挂起的 child run。

    `run_output` 是 Agno RunOutput 引用,confirm/reject 时直接调它的
    `.requirements[i].confirm()/.reject()`(纯内存操作,Agno db 状态由
    `agent.acontinue_run(...)` 自己 upsert)。**不序列化**——RunOutput 含
    模型/工具/消息等大量运行期对象,跨进程恢复也无 Agno API 支持。
    """

    request_id: str
    run_id: str
    utt_id: str
    generation: int
    preview: dict
    # wall-clock 秒。TTL 比较用 time.time() 统一基线,跨进程也有意义。
    created_at: float = field(default_factory=time.time)
    # 仅内存。不序列化。
    run_output: Any = None


class Orchestrator:
    def __init__(
        self,
        ctx: ContextStore,
        gate: RelevanceGate | None = None,
        pa: ProfileAgent | None = None,
        ha: HeavyAgent | None = None,
        session_id: str = "default",
        user_id: str = "default",
    ):
        self._ctx = ctx
        self._gate = gate or RelevanceGate()
        self._pa = pa or ProfileAgent()
        self._ha = ha or HeavyAgent(ctx, session_id=session_id, user_id=user_id)
        self._suggestion_callback = None
        self._expiry_callback = None
        self._pending: dict[str, PendingRequest] = {}
        self._inflight: set[asyncio.Task] = set()  # 在飞 child task,防 GC + 收集异常
        self._bus = None
        self._bus_task = None
        self._ttl_task = None
        self._profile_callback = None
        self._emitter: Callable[[OutboundEvent], Awaitable[None]] | None = None
        self._repo: _RepoWriter | None = None

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def attach_bus(self, bus) -> None:
        self._bus = bus

    def set_suggestion_callback(self, callback) -> None:
        self._suggestion_callback = callback

    def set_expiry_callback(self, callback) -> None:
        self._expiry_callback = callback

    def set_profile_callback(self, callback) -> None:
        self._profile_callback = callback

    def set_event_emitter(
        self, emit: Callable[[OutboundEvent], Awaitable[None]]
    ) -> None:
        self._emitter = emit

    def set_repo_writer(self, repo: _RepoWriter) -> None:
        self._repo = repo

    async def start(self) -> None:
        await self._ctx.start_profile_worker()
        if self._bus is not None and self._bus_task is None:
            self._bus_task = asyncio.create_task(self._consume_bus())
        if self._ttl_task is None:
            self._ttl_task = asyncio.create_task(self._sweep_pending_ttl())

    async def shutdown(self) -> None:
        await self._ctx.stop_profile_worker()
        for task in (self._bus_task, self._ttl_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        # 等所有在飞 child task 结束(它们已经走 logger,不会抛到这里)
        if self._inflight:
            await asyncio.gather(*self._inflight, return_exceptions=True)
        self._inflight.clear()
        self._pending.clear()

    # ------------------------------------------------------------------
    # main path
    # ------------------------------------------------------------------

    async def handle_utterance(self, utt: Utterance) -> int:
        # speaker 归一:None 是 bug 信号,uncertain 是合法的"非律师"标签
        if utt.speaker is None:
            logger.warning("utterance %s speaker=None,声纹链路可能未接通(已降级为 client)", utt.id)
        if utt.speaker not in ("lawyer", "client"):
            utt.speaker = "client"

        generation = await self._ctx.append_utterance(utt)

        # gate 与 PA 并行,gate 不阻塞 PA(画像兜底)
        gate_task = asyncio.create_task(self._safe_gate(utt))
        pa_task = None
        if utt.speaker != "lawyer":
            pa_task = asyncio.create_task(
                self._pa.extract(
                    text=utt.text,
                    speaker=utt.speaker,
                    history=self._ctx.get_recent_window(n=PROFILE_WINDOW_SIZE),
                    existing_profile=self._ctx.get_profile_summary(),
                    utt_id=utt.id,
                )
            )

        if pa_task is not None:
            try:
                entries = await pa_task
                if entries:
                    for entry in entries:
                        entry.timestamp = utt.t_start
                    await self._ctx.enqueue_profile_update(utt.id, entries)
                    if self._profile_callback is not None:
                        try:
                            result = self._profile_callback(entries)
                            if asyncio.iscoroutine(result):
                                await result
                        except Exception:
                            logger.warning("profile callback failed", exc_info=True)
                    await self._emit_event(ProfileUpdated(
                        entries=[
                            ProfileEntryPayload(
                                key=e.key, value=e.value, subject=e.subject,
                            ) for e in entries
                        ],
                    ))
            except Exception as e:
                logger.warning("ProfileAgent.extract failed for utt %s: %s", utt.id, e)

        should_spawn = await gate_task
        if should_spawn:
            self._spawn_inflight(self._run_child(utt, generation), label=f"child:{utt.id}")

        return generation

    def _spawn_inflight(self, coro, *, label: str) -> None:
        """统一的 fire-and-forget 入口:保存引用防 GC + 异常入 log。"""
        task = asyncio.create_task(coro, name=label)
        self._inflight.add(task)

        def _done(t: asyncio.Task) -> None:
            self._inflight.discard(t)
            if t.cancelled():
                return
            exc = t.exception()
            if exc is not None:
                logger.exception("inflight task %s crashed", label, exc_info=exc)

        task.add_done_callback(_done)

    async def _safe_gate(self, utt: Utterance) -> bool:
        try:
            return await self._gate.is_relevant(utt)
        except Exception as e:
            # gate 抖动按 False 处理(画像兜底捞回事实),但必须留下抖动证据
            logger.warning("RelevanceGate failed for utt %s: %s", utt.id, e)
            return False

    async def _run_child(self, utt: Utterance, generation: int) -> None:
        task = asyncio.create_task(self._ha.arun(utt))
        try:
            run = await asyncio.wait_for(task, timeout=RUN_TIMEOUT)
        except TimeoutError:
            logger.warning("child run timeout (>%ss) for utt %s", RUN_TIMEOUT, utt.id)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            return
        except Exception:
            logger.exception("child run failed for utt %s", utt.id)
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            return

        # 两个分支都要查 generation:paused 也可能因新 utterance 而 stale,
        # 此时弹 pending 卡片只会污染新对话。
        if self._ctx.get_generation() != generation:
            return

        if not run.is_paused:
            text = (getattr(run, "content", None) or "").strip()
            if not text:
                return
            insight_id = f"ins_{uuid.uuid4().hex[:8]}"
            if self._repo is not None:
                try:
                    await self._repo.insert_direct(utt_id=utt.id, text=text)
                except Exception:
                    logger.warning("insert_direct failed utt=%s", utt.id, exc_info=True)
            await self._emit_event(InsightReady(
                id=insight_id, utt_id=utt.id, text=text,
            ))
            return

        # paused: 取首个 requirement 的预览给律师
        req = run.active_requirements[0] if run.active_requirements else None
        tool_args = (
            dict(req.tool_execution.tool_args or {})
            if req is not None and req.tool_execution is not None
            else {}
        )
        topic = str(tool_args.get("topic", ""))
        rationale = str(tool_args.get("rationale", ""))

        request_id = f"req_{uuid.uuid4().hex[:8]}"
        self._pending[request_id] = PendingRequest(
            request_id=request_id,
            run_id=run.run_id,
            utt_id=utt.id,
            generation=generation,
            preview={"topic": topic, "rationale": rationale},
            run_output=run,
        )
        if self._repo is not None:
            try:
                await self._repo.upsert_pending(
                    utt_id=utt.id, request_id=request_id,
                    preview_topic=topic, preview_rationale=rationale,
                )
            except Exception:
                logger.warning("upsert_pending failed req=%s", request_id, exc_info=True)
        await self._emit_event(AnalysisProposed(
            request_id=request_id, utt_id=utt.id, topic=topic, rationale=rationale,
        ))

    # ------------------------------------------------------------------
    # confirm / dismiss / cleanup
    # ------------------------------------------------------------------

    async def confirm_analysis(self, request_id: str) -> bool:
        pending = self._pending.pop(request_id, None)
        if pending is None:
            return False
        if pending.run_output is None:
            # 从 db 恢复出来的 pending 没有 RunOutput 引用 → 无法 confirm,
            # 直接 abandon。前端应当避免对恢复后的 pending 发 confirm。
            await self._abandon_run(pending)
            return False

        # 不再校验 generation:卡片已经展示给用户,paused run 的上下文在 pause 时
        # 就冻结了,之后新 utterance 不会污染续跑结果。再校验只会让"用户读卡片
        # 期间又说话"这一常见路径无差别失败。
        # 在内存里 confirm 所有 active_requirement,再调 acontinue_run。
        # Agno 文档约定:requirements 直接从 run_output.requirements 传入。
        for req in pending.run_output.active_requirements or []:
            try:
                req.confirm()
            except Exception:
                logger.warning("requirement.confirm() failed", exc_info=True)

        try:
            run = await asyncio.wait_for(
                self._ha.acontinue_run(
                    run_id=pending.run_id,
                    requirements=pending.run_output.requirements,
                ),
                timeout=RUN_TIMEOUT,
            )
        except Exception:
            logger.exception("continue_run failed for run_id=%s", pending.run_id)
            await self._abandon_run(pending)
            return False

        text = getattr(run, "content", None)
        await self._emit({"kind": "ready", "utt_id": pending.utt_id, "request_id": request_id}, text=text)
        return True

    async def dismiss_pending(self, request_id: str) -> None:
        pending = self._pending.pop(request_id, None)
        if pending is None:
            return
        await self._abandon_run(pending)

    async def _abandon_run(self, pending: PendingRequest) -> None:
        """放弃挂起 run:reject 内存中的 requirements + 把 Agno db 的 run 状态标 CANCELLED。

        注意:Agno SqliteDb/PostgresDb 没有 get_run/delete_run 这类 API。
        真实可用 API 是 update_approval_run_status(run_id, RunStatus.*) 与
        delete_approval(approval_id)。这里只动 run_status,approvals 行让
        Agno 内部 GC,避免我们替它管 approval_id 生命周期。
        """
        # 1) 内存中 reject(若有 run_output)
        if pending.run_output is not None:
            for req in pending.run_output.active_requirements or []:
                try:
                    req.reject("abandoned")
                except Exception:
                    pass
        # 2) db 中把 run 标 CANCELLED,避免 paused 状态永久滞留
        db = self._ha._db
        try:
            if hasattr(db, "update_approval_run_status"):
                db.update_approval_run_status(run_id=pending.run_id, run_status=RunStatus.cancelled)
        except Exception:
            logger.warning(
                "update_approval_run_status failed for run_id=%s", pending.run_id, exc_info=True
            )

    async def _sweep_pending_ttl(self) -> None:
        """后台扫描:挂起 run 超过 PENDING_TTL 自动 abandon。
        每轮循环重读 config.PENDING_TTL,让 monkeypatch 在测试里生效。"""
        while True:
            try:
                import config as _cfg  # noqa: PLC0415
                ttl = _cfg.PENDING_TTL
                await asyncio.sleep(max(0.05, min(ttl / 4, 30)))
            except asyncio.CancelledError:
                break
            now = time.time()
            stale = [rid for rid, p in self._pending.items() if now - p.created_at > ttl]
            if stale and self._expiry_callback is not None:
                try:
                    result = self._expiry_callback(stale)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:
                    logger.warning("expiry callback failed", exc_info=True)
            for rid in stale:
                pending = self._pending.pop(rid, None)
                if pending:
                    await self._abandon_run(pending)

    # ------------------------------------------------------------------
    # plumbing
    # ------------------------------------------------------------------

    async def _consume_bus(self) -> None:
        while True:
            try:
                utt = await self._bus.get()
                await self.handle_utterance(utt)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("handle_utterance failed")

    async def _emit(self, meta: dict, text: str | None) -> None:
        if self._suggestion_callback is None:
            return
        result = self._suggestion_callback(text, meta)
        if asyncio.iscoroutine(result):
            await result

    async def _emit_event(self, evt: OutboundEvent) -> None:
        if self._emitter is None:
            return
        try:
            await self._emitter(evt)
        except Exception:
            logger.warning("emit_event failed for %s", evt.type, exc_info=True)

