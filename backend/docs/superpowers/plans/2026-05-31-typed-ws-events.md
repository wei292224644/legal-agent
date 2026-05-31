# 实时事件契约化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 WebSocket 通信从「callback + dict + 字符串 type」的胶水代码升级为 Pydantic discriminated union 事件契约，顺带把持久化从 callback 抽到 Orchestrator，修复直接洞察被静默丢弃与 `onAnalysis` 死代码 bug。

**Architecture:** 后端定义 `OutboundEvent` Union，Orchestrator 通过单 emitter 推送 typed event；持久化由 Orchestrator 内部完成，main.py 只负责 `model_dump()` → WebSocket。前端定义镜像 TS discriminated union，reducer 用 exhaustive switch 处理 `RECV_EVENT` action。

**Tech Stack:** Pydantic v2 + FastAPI + asyncio（后端）；React 19 + TypeScript + Vitest + useReducer（前端）。

**Spec:** [`backend/docs/superpowers/specs/2026-05-31-typed-ws-events-design.md`](../specs/2026-05-31-typed-ws-events-design.md)

---

## 决策修正（相对 spec）

- `SuggestionRepository.upsert_pending` 已存在，无需新增。沿用现有方法。
- `dismissed` / `expired` 终态会**持久化**（spec 立场）；这与 `main.py:191/199` 旧注释「中间状态不存 DB」相左，按 spec 走（终态入库便于审计；history 端点已过滤这两类，前端无副作用）；任务里会把旧注释一并改掉。
- 前端 `Insight` 类型简化为 `{ id; uttId; text; createdAt }`，删除从未真正流通过的 `category / title / citation / riskLevel`；`InsightCard.tsx` 改为简单文本卡。这是 spec `InsightReady` schema 的必然结果。

---

## 文件结构

**后端新增：**
- `backend/src/agent/events.py` — OutboundEvent Pydantic union
- `backend/tests/agent/test_events_schema.py` — 事件 round-trip
- `backend/tests/agent/test_orchestrator_emitter.py` — Orchestrator 事件路径覆盖

**后端修改：**
- `backend/src/agent/orchestrator.py` — emitter / repo writer 注入；持久化迁入
- `backend/main.py` — 单 `send_event`；TranscriptDelta / Pong / ConfirmAck / ErrorEvent 改 typed；删 3 个 callback；旧注释清理

**前端新增：**
- `frontend/src/types/events.ts` — ServerEvent TS union
- `frontend/src/__tests__/sessionReducer.test.ts` — reducer 覆盖每个事件

**前端修改：**
- `frontend/src/types/index.ts` — 简化 `Insight`
- `frontend/src/components/insights/InsightCard.tsx` — 适配新 Insight
- `frontend/src/context/session-context.ts` — 加 `RECV_EVENT` action
- `frontend/src/context/SessionContext.tsx` — reducer 处理 RECV_EVENT
- `frontend/src/hooks/useWebSocket.ts` — 收敛为单 `onEvent`
- `frontend/src/pages/LiveSession.tsx` — 删 5 个 callback → 单 dispatch

---

## Task 1：定义后端事件 schema

**Files:**
- Create: `backend/src/agent/events.py`
- Test: `backend/tests/agent/test_events_schema.py`

- [ ] **Step 1: 写失败测试**

`backend/tests/agent/test_events_schema.py`：

```python
"""WS 出站事件 schema 的 round-trip 与 discriminator 验证。

为什么这样测：每个事件都要能被 model_dump() 序列化后再 model_validate()
还原，且联合类型按 `type` 字段正确分派——这两件事一旦失守，前后端协议立刻
错位。"""
import json
import pytest
from pydantic import TypeAdapter, ValidationError

from agent.events import (
    OutboundEvent,
    TranscriptDelta, InsightReady, AnalysisProposed, AnalysisReady,
    AnalysisDismissed, ProfileUpdated, ProfileEntryPayload,
    ConfirmAck, ErrorEvent, Pong,
)

ADAPTER: TypeAdapter[OutboundEvent] = TypeAdapter(OutboundEvent)


@pytest.mark.parametrize("evt", [
    TranscriptDelta(utt_id="u1", speaker="lawyer", text="hi",
                    t_start=0.0, t_end=1.0, closed_by=None),
    InsightReady(id="ins_1", utt_id="u1", text="结论"),
    AnalysisProposed(request_id="req_1", utt_id="u1",
                     topic="X 是否构成 Y", rationale="因为 Z"),
    AnalysisReady(request_id="req_1", utt_id="u1", text="深度结论"),
    AnalysisDismissed(request_id="req_1", reason="expired"),
    ProfileUpdated(entries=[ProfileEntryPayload(key="姓名", value="张三", subject="client")]),
    ConfirmAck(request_id="req_1", ok=True),
    ErrorEvent(message="oops"),
    Pong(),
])
def test_event_roundtrip_preserves_payload(evt):
    """事件 dump 后能被 union adapter 复原成同型同值。
    这是协议契约最低保证——破了说明 type literal 或字段定义出问题。"""
    raw = json.dumps(evt.model_dump())
    restored = ADAPTER.validate_json(raw)
    assert type(restored) is type(evt)
    assert restored.model_dump() == evt.model_dump()


def test_union_rejects_unknown_type():
    """未知 type 必须 ValidationError，防止 main.py 拿 dict 当 event 用。"""
    with pytest.raises(ValidationError):
        ADAPTER.validate_python({"type": "made_up_event"})


def test_analysis_dismissed_reason_is_constrained():
    """reason 是闭集——拼写错误会被立刻发现，不会变成"未知 dismiss 原因"。"""
    with pytest.raises(ValidationError):
        AnalysisDismissed(request_id="req_1", reason="bogus")  # type: ignore[arg-type]
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
cd backend && uv run pytest tests/agent/test_events_schema.py -v
```

Expected: `ModuleNotFoundError: No module named 'agent.events'`

- [ ] **Step 3: 实现 events.py**

`backend/src/agent/events.py`：

```python
"""WS 出站事件契约。Orchestrator 通过此契约对外说话；main.py 只负责
dump 到 WebSocket，不做任何业务判断。"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class TranscriptDelta(BaseModel):
    type: Literal["transcript"] = "transcript"
    utt_id: str
    speaker: str
    text: str
    t_start: float
    t_end: float
    closed_by: str | None = None
    is_final: bool = True


class InsightReady(BaseModel):
    type: Literal["insight.ready"] = "insight.ready"
    id: str
    utt_id: str
    text: str


class AnalysisProposed(BaseModel):
    type: Literal["analysis.proposed"] = "analysis.proposed"
    request_id: str
    utt_id: str
    topic: str
    rationale: str


class AnalysisReady(BaseModel):
    type: Literal["analysis.ready"] = "analysis.ready"
    request_id: str
    utt_id: str
    text: str


class AnalysisDismissed(BaseModel):
    type: Literal["analysis.dismissed"] = "analysis.dismissed"
    request_id: str
    reason: Literal["dismissed", "expired", "abandoned"]


class ProfileEntryPayload(BaseModel):
    key: str
    value: str
    subject: str


class ProfileUpdated(BaseModel):
    type: Literal["profile.updated"] = "profile.updated"
    entries: list[ProfileEntryPayload]


class ConfirmAck(BaseModel):
    type: Literal["confirm_ack"] = "confirm_ack"
    request_id: str
    ok: bool


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str


class Pong(BaseModel):
    type: Literal["pong"] = "pong"


OutboundEvent = Annotated[
    TranscriptDelta | InsightReady | AnalysisProposed | AnalysisReady
    | AnalysisDismissed | ProfileUpdated | ConfirmAck | ErrorEvent | Pong,
    Field(discriminator="type"),
]
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
cd backend && uv run pytest tests/agent/test_events_schema.py -v
```

Expected: 全部 PASS（11 个 parametrize + 2 个独立 case = 13 个）。

- [ ] **Step 5: 提交**

```bash
git add backend/src/agent/events.py backend/tests/agent/test_events_schema.py
git commit -m "feat(events): WS 出站事件 schema (Pydantic discriminated union)

每个事件 type literal 即协议码，model_dump 上线、validate 收线。
union 通过 discriminator='type' 按字段分派，未知 type 立刻 ValidationError。"
```

---

## Task 2：Orchestrator 注入 emitter 与 repo writer

**Files:**
- Modify: `backend/src/agent/orchestrator.py`
- Test: `backend/tests/agent/test_orchestrator_emitter.py`

> 本任务只搭骨架（新接口 + 旧 callback 暂存），不删旧逻辑。事件路径在 Task 3~6 逐个迁。

- [ ] **Step 1: 写失败测试**

`backend/tests/agent/test_orchestrator_emitter.py`：

```python
"""Orchestrator 事件路径：fake emitter + in-memory repo writer 验证。

设计目的：把 Orchestrator 从 sessionmaker 与 WebSocket 隔离开测。
- emitter 只收 list[OutboundEvent]
- repo writer 实现 SuggestionRepository 用到的几个方法，存 list[dict]
"""
from __future__ import annotations

import asyncio
import pytest
import pytest_asyncio
from dataclasses import dataclass, field

from agent.context_store import ContextStore
from agent.events import OutboundEvent


@dataclass
class FakeEmitter:
    received: list[OutboundEvent] = field(default_factory=list)

    async def __call__(self, evt: OutboundEvent) -> None:
        self.received.append(evt)


@dataclass
class FakeRepoWriter:
    """Orchestrator 通过它写 DB；这里只记账。"""
    calls: list[tuple[str, dict]] = field(default_factory=list)

    async def insert_direct(self, *, utt_id: str, text: str) -> None:
        self.calls.append(("insert_direct", {"utt_id": utt_id, "text": text}))

    async def upsert_pending(self, *, utt_id: str, request_id: str,
                              preview_topic: str | None,
                              preview_rationale: str | None) -> None:
        self.calls.append(("upsert_pending", {
            "utt_id": utt_id, "request_id": request_id,
            "preview_topic": preview_topic, "preview_rationale": preview_rationale,
        }))

    async def mark_running(self, request_id: str) -> None:
        self.calls.append(("mark_running", {"request_id": request_id}))

    async def upsert_ready(self, *, request_id: str, text: str, utt_id: str | None) -> None:
        self.calls.append(("upsert_ready", {
            "request_id": request_id, "text": text, "utt_id": utt_id,
        }))

    async def mark_dismissed(self, request_id: str) -> None:
        self.calls.append(("mark_dismissed", {"request_id": request_id}))

    async def mark_expired(self, request_id: str) -> None:
        self.calls.append(("mark_expired", {"request_id": request_id}))


@pytest_asyncio.fixture
async def orch(db_session):
    """用 db_session 派生 sessionmaker 给 ContextStore；Orchestrator
    用 fake emitter + repo writer（不走真实 DB,与 ctx 的 DB 隔离）。"""
    import uuid as _uuid
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from agent.orchestrator import Orchestrator

    sm = async_sessionmaker(db_session.bind, expire_on_commit=False)
    ctx = ContextStore(session_id=_uuid.uuid4(), sessionmaker=sm)

    # 关掉 PA/Gate/HA（这一任务只验 wiring，不验业务）
    class _NoopGate:
        async def is_relevant(self, _utt):
            return False

    class _NoopPA:
        async def extract(self, **_):
            return []

    class _NoopHA:
        async def arun(self, _utt):
            return None

    o = Orchestrator(
        ctx=ctx,
        gate=_NoopGate(),
        pa=_NoopPA(),
        ha=_NoopHA(),
        session_id="sess",
        user_id="u",
    )
    o.set_event_emitter(FakeEmitter())
    o.set_repo_writer(FakeRepoWriter())
    yield o


@pytest.mark.asyncio
async def test_emitter_swallows_errors(orch):
    """emitter 抛错不应中断 Orchestrator——这是稳定性保证。"""
    async def boom(_evt):
        raise RuntimeError("ws gone")

    orch.set_event_emitter(boom)
    # 直接调内部 emit；不应抛出
    from agent.events import Pong
    await orch._emit_event(Pong())


def test_setters_exist(orch):
    """set_event_emitter / set_repo_writer 是新公共接口。"""
    assert callable(getattr(orch, "set_event_emitter"))
    assert callable(getattr(orch, "set_repo_writer"))
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
cd backend && uv run pytest tests/agent/test_orchestrator_emitter.py -v
```

Expected: `AttributeError: 'Orchestrator' object has no attribute 'set_event_emitter'`

- [ ] **Step 3: 修改 Orchestrator，加 setters + 私有 emit + repo writer protocol**

在 `backend/src/agent/orchestrator.py` 顶部 import 区加：

```python
from collections.abc import Awaitable, Callable
from typing import Protocol

from agent.events import OutboundEvent
```

文件中段加 protocol（放在 `PROFILE_WINDOW_SIZE = 6` 之后）：

```python
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
```

`Orchestrator.__init__` 末尾加：

```python
        self._emitter: Callable[[OutboundEvent], Awaitable[None]] | None = None
        self._repo: _RepoWriter | None = None
```

加两个 setter（在 `set_profile_callback` 旁边）：

```python
    def set_event_emitter(
        self, emit: Callable[[OutboundEvent], Awaitable[None]]
    ) -> None:
        self._emitter = emit

    def set_repo_writer(self, repo: _RepoWriter) -> None:
        self._repo = repo
```

加私有 emit（替换文件最末尾的 `async def _emit`，但**先保留旧 _emit 不删**——Task 3~6 才会迁移调用方）：

```python
    async def _emit_event(self, evt: OutboundEvent) -> None:
        if self._emitter is None:
            return
        try:
            await self._emitter(evt)
        except Exception:
            logger.warning("emit_event failed for %s", evt.type, exc_info=True)
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
cd backend && uv run pytest tests/agent/test_orchestrator_emitter.py -v
```

Expected: 2 个测试 PASS。

- [ ] **Step 5: 跑现有 orchestrator 相关测试，确认未破坏**

```bash
cd backend && uv run pytest -k "orchestrator or context_store" -v
```

Expected: 全部 PASS（新增的 setter 不影响旧代码）。

- [ ] **Step 6: 提交**

```bash
git add backend/src/agent/orchestrator.py backend/tests/agent/test_orchestrator_emitter.py
git commit -m "feat(orch): 加 set_event_emitter / set_repo_writer 骨架

新 _emit_event 兜底捕获异常,emitter 失败不污染其他事件路径。
本提交不动旧 callback,后续 task 逐个事件类型迁移。"
```

---

## Task 3：迁移 ProfileUpdated 事件路径

**Files:**
- Modify: `backend/src/agent/orchestrator.py:145-160`
- Modify: `backend/tests/agent/test_orchestrator_emitter.py`

- [ ] **Step 1: 加测试**

在 `test_orchestrator_emitter.py` 加：

```python
from unittest.mock import AsyncMock

from agent.events import ProfileUpdated
from models.profile import ProfileEntry  # 路径以现有项目为准
from models.utterance import Utterance


@pytest.mark.asyncio
async def test_handle_utterance_emits_profile_updated(orch):
    """客户句子 → PA 返回 entries → emit ProfileUpdated。
    业务意图：画像数据每次更新都要让前端实时看到，不能只入 DB。"""
    fake_emitter = FakeEmitter()
    orch.set_event_emitter(fake_emitter)

    # 把 _pa.extract 替换为返回 2 条 entry
    entries = [
        ProfileEntry(key="姓名", value="张三", subject="client", timestamp=0.0),
        ProfileEntry(key="年龄", value="30", subject="client", timestamp=0.0),
    ]
    orch._pa.extract = AsyncMock(return_value=entries)

    utt = Utterance(id="u1", text="我叫张三今年三十", speaker="client",
                    t_start=0.0, t_end=1.0)
    await orch.handle_utterance(utt)

    profile_evts = [e for e in fake_emitter.received if isinstance(e, ProfileUpdated)]
    assert len(profile_evts) == 1
    assert {(p.key, p.value, p.subject) for p in profile_evts[0].entries} == {
        ("姓名", "张三", "client"), ("年龄", "30", "client"),
    }


@pytest.mark.asyncio
async def test_handle_utterance_lawyer_skips_profile_event(orch):
    """律师句子不跑 PA,自然不应 emit ProfileUpdated。"""
    fake_emitter = FakeEmitter()
    orch.set_event_emitter(fake_emitter)

    utt = Utterance(id="u1", text="您好", speaker="lawyer",
                    t_start=0.0, t_end=1.0)
    await orch.handle_utterance(utt)

    profile_evts = [e for e in fake_emitter.received if isinstance(e, ProfileUpdated)]
    assert profile_evts == []
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
cd backend && uv run pytest tests/agent/test_orchestrator_emitter.py::test_handle_utterance_emits_profile_updated -v
```

Expected: FAIL（旧代码走 `self._profile_callback`，没人接 → received 为空）。

- [ ] **Step 3: 改 handle_utterance**

`backend/src/agent/orchestrator.py`，把现有 profile callback 调用块（约 145-160 行）替换为：

```python
        if pa_task is not None:
            try:
                entries = await pa_task
                if entries:
                    for entry in entries:
                        entry.timestamp = utt.t_start
                    await self._ctx.enqueue_profile_update(utt.id, entries)
                    await self._emit_event(ProfileUpdated(
                        entries=[
                            ProfileEntryPayload(
                                key=e.key, value=e.value, subject=e.subject,
                            ) for e in entries
                        ],
                    ))
            except Exception as e:
                logger.warning("ProfileAgent.extract failed for utt %s: %s", utt.id, e)
```

import 区加：

```python
from agent.events import ProfileUpdated, ProfileEntryPayload
```

**注意**：保留 `set_profile_callback` 方法定义（暂时无用）——避免破坏 main.py 旧 wiring，Task 8 统一删除。

- [ ] **Step 4: 运行测试，确认通过**

```bash
cd backend && uv run pytest tests/agent/test_orchestrator_emitter.py -v
```

Expected: 全部 PASS（共 4 个 test）。

- [ ] **Step 5: 提交**

```bash
git add backend/src/agent/orchestrator.py backend/tests/agent/test_orchestrator_emitter.py
git commit -m "refactor(orch): handle_utterance 改 emit ProfileUpdated"
```

---

## Task 4：迁移 InsightReady 事件路径（含持久化）

**Files:**
- Modify: `backend/src/agent/orchestrator.py:191-220`（`_run_child` 非 paused 分支）
- Modify: `backend/tests/agent/test_orchestrator_emitter.py`

- [ ] **Step 1: 加测试**

```python
from agent.events import InsightReady


@pytest.mark.asyncio
async def test_run_child_emits_insight_ready_and_persists(orch):
    """非 gated 路径:HeavyAgent 直出文本 → InsightReady 事件 + repo.insert_direct。
    业务意图:大多数 utterance 走这条路径,事件丢失等于"实时洞察"一直空白。"""
    fake_emitter = FakeEmitter()
    fake_repo = FakeRepoWriter()
    orch.set_event_emitter(fake_emitter)
    orch.set_repo_writer(fake_repo)

    # 构造一个非 paused 的 fake RunOutput
    class _FakeRun:
        is_paused = False
        content = "这是直接洞察"

    orch._ha.arun = AsyncMock(return_value=_FakeRun())

    utt = Utterance(id="u1", text="某客户陈述", speaker="client",
                    t_start=0.0, t_end=1.0)
    generation = await orch._ctx.append_utterance(utt)
    await orch._run_child(utt, generation)

    insight_evts = [e for e in fake_emitter.received if isinstance(e, InsightReady)]
    assert len(insight_evts) == 1
    evt = insight_evts[0]
    assert evt.utt_id == "u1"
    assert evt.text == "这是直接洞察"
    assert evt.id.startswith("ins_")

    # 同一 id 必须落到 DB
    direct_calls = [c for c in fake_repo.calls if c[0] == "insert_direct"]
    assert len(direct_calls) == 1
    assert direct_calls[0][1] == {"utt_id": "u1", "text": "这是直接洞察"}


@pytest.mark.asyncio
async def test_run_child_skips_empty_insight(orch):
    """空 content 不应入 DB 也不应发事件——避免占位卡片污染 UI。"""
    fake_emitter = FakeEmitter()
    fake_repo = FakeRepoWriter()
    orch.set_event_emitter(fake_emitter)
    orch.set_repo_writer(fake_repo)

    class _FakeRun:
        is_paused = False
        content = "   "  # 全空白

    orch._ha.arun = AsyncMock(return_value=_FakeRun())
    utt = Utterance(id="u1", text="x", speaker="client", t_start=0.0, t_end=1.0)
    generation = await orch._ctx.append_utterance(utt)
    await orch._run_child(utt, generation)

    assert [e for e in fake_emitter.received if isinstance(e, InsightReady)] == []
    assert fake_repo.calls == []
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
cd backend && uv run pytest tests/agent/test_orchestrator_emitter.py::test_run_child_emits_insight_ready_and_persists -v
```

Expected: FAIL（旧 `_run_child` 走 `_emit({"kind": "ready", ...})` 调旧 callback，FakeEmitter 收不到）。

- [ ] **Step 3: 改 `_run_child` 非 paused 分支**

`backend/src/agent/orchestrator.py`，把：

```python
        if not run.is_paused:
            await self._emit({"kind": "ready", "utt_id": utt.id}, text=getattr(run, "content", None))
            return
```

替换为：

```python
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
```

import 区追加：

```python
from agent.events import InsightReady
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
cd backend && uv run pytest tests/agent/test_orchestrator_emitter.py -v
```

Expected: 全部 PASS（6 个 test）。

- [ ] **Step 5: 提交**

```bash
git add backend/src/agent/orchestrator.py backend/tests/agent/test_orchestrator_emitter.py
git commit -m "refactor(orch): 直接洞察走 InsightReady + insert_direct,根治前端丢弃 bug"
```

---

## Task 5：迁移 AnalysisProposed 事件路径（含持久化）

**Files:**
- Modify: `backend/src/agent/orchestrator.py:222-245`（`_run_child` paused 分支）
- Modify: `backend/tests/agent/test_orchestrator_emitter.py`

- [ ] **Step 1: 加测试**

```python
from agent.events import AnalysisProposed


@pytest.mark.asyncio
async def test_run_child_emits_analysis_proposed_and_persists(orch):
    """gated 路径:HeavyAgent paused 等确认 → AnalysisProposed + upsert_pending。"""
    fake_emitter = FakeEmitter()
    fake_repo = FakeRepoWriter()
    orch.set_event_emitter(fake_emitter)
    orch.set_repo_writer(fake_repo)

    class _FakeReq:
        class tool_execution:
            tool_args = {"topic": "本案是否构成违约", "rationale": "对方未履行交付义务"}
        def confirm(self): pass
        def reject(self, _): pass

    class _FakeRun:
        is_paused = True
        run_id = "agno_run_xyz"
        active_requirements = [_FakeReq()]
        requirements = active_requirements
        content = None

    orch._ha.arun = AsyncMock(return_value=_FakeRun())
    utt = Utterance(id="u1", text="x", speaker="client", t_start=0.0, t_end=1.0)
    generation = await orch._ctx.append_utterance(utt)
    await orch._run_child(utt, generation)

    proposed = [e for e in fake_emitter.received if isinstance(e, AnalysisProposed)]
    assert len(proposed) == 1
    evt = proposed[0]
    assert evt.utt_id == "u1"
    assert evt.topic == "本案是否构成违约"
    assert evt.rationale == "对方未履行交付义务"
    assert evt.request_id.startswith("req_")

    pending_calls = [c for c in fake_repo.calls if c[0] == "upsert_pending"]
    assert len(pending_calls) == 1
    assert pending_calls[0][1]["utt_id"] == "u1"
    assert pending_calls[0][1]["request_id"] == evt.request_id

    # PendingRequest 必须仍在内存以便后续 confirm
    assert evt.request_id in orch._pending
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
cd backend && uv run pytest tests/agent/test_orchestrator_emitter.py::test_run_child_emits_analysis_proposed_and_persists -v
```

Expected: FAIL（旧分支调 `_emit` + 旧 callback）。

- [ ] **Step 3: 改 `_run_child` paused 分支**

替换 paused 分支（约 222-245 行）为：

```python
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
```

import 区加：

```python
from agent.events import AnalysisProposed
```

- [ ] **Step 4: 测试通过**

```bash
cd backend && uv run pytest tests/agent/test_orchestrator_emitter.py -v
```

Expected: 7 个 PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/src/agent/orchestrator.py backend/tests/agent/test_orchestrator_emitter.py
git commit -m "refactor(orch): paused 分支走 AnalysisProposed + upsert_pending"
```

---

## Task 6：迁移 AnalysisReady 事件路径（含持久化）

**Files:**
- Modify: `backend/src/agent/orchestrator.py:251-287`（`confirm_analysis`）
- Modify: `backend/tests/agent/test_orchestrator_emitter.py`

- [ ] **Step 1: 加测试**

```python
from agent.events import AnalysisReady


@pytest.mark.asyncio
async def test_confirm_analysis_emits_ready_and_persists(orch):
    """confirm → continue_run 返回 → AnalysisReady + mark_running + upsert_ready。
    业务意图:律师等了卡片确认深析,结果必须实时回到 UI 同时落 DB 便于刷新恢复。"""
    fake_emitter = FakeEmitter()
    fake_repo = FakeRepoWriter()
    orch.set_event_emitter(fake_emitter)
    orch.set_repo_writer(fake_repo)

    # 手工塞一个 pending
    from agent.orchestrator import PendingRequest

    class _FakeReq:
        def confirm(self): pass
        def reject(self, _): pass

    class _FakeRun:
        is_paused = False
        content = "深度分析结论"
        run_id = "agno_run_1"
        active_requirements = [_FakeReq()]
        requirements = active_requirements

    orch._pending["req_abc"] = PendingRequest(
        request_id="req_abc", run_id="agno_run_1", utt_id="u1",
        generation=0, preview={"topic": "", "rationale": ""},
        run_output=_FakeRun(),
    )
    orch._ha.acontinue_run = AsyncMock(return_value=_FakeRun())

    ok = await orch.confirm_analysis("req_abc")
    assert ok is True

    ready = [e for e in fake_emitter.received if isinstance(e, AnalysisReady)]
    assert len(ready) == 1
    assert ready[0].request_id == "req_abc"
    assert ready[0].utt_id == "u1"
    assert ready[0].text == "深度分析结论"

    op_names = [c[0] for c in fake_repo.calls]
    assert "mark_running" in op_names
    assert "upsert_ready" in op_names
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
cd backend && uv run pytest tests/agent/test_orchestrator_emitter.py::test_confirm_analysis_emits_ready_and_persists -v
```

Expected: FAIL。

- [ ] **Step 3: 改 confirm_analysis**

把 `confirm_analysis` 末尾的 `_emit(...)` 调用块替换为：

```python
        # 先标 running(让 DB 反映"已点确认"状态),续跑完成后再 ready
        if self._repo is not None:
            try:
                await self._repo.mark_running(pending.request_id)
            except Exception:
                logger.warning("mark_running failed req=%s", pending.request_id, exc_info=True)

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
            await self._emit_event(AnalysisDismissed(
                request_id=pending.request_id, reason="abandoned",
            ))
            return False

        text = (getattr(run, "content", None) or "").strip()
        if self._repo is not None:
            try:
                await self._repo.upsert_ready(
                    request_id=pending.request_id, text=text, utt_id=pending.utt_id,
                )
            except Exception:
                logger.warning("upsert_ready failed req=%s", pending.request_id, exc_info=True)
        await self._emit_event(AnalysisReady(
            request_id=pending.request_id, utt_id=pending.utt_id, text=text,
        ))
        return True
```

import 区加：

```python
from agent.events import AnalysisReady, AnalysisDismissed
```

**注意**：原 confirm_analysis 内部还有 `acontinue_run` 的 try/except，请用上方代码完整替换从 `try:` 到 `return True` 的整段。`mark_running` 必须在 `acontinue_run` 之前调（旧 main.py 注释里说"running 不存 DB"是错的——dismiss 同样按 spec 持久化）。

- [ ] **Step 4: 测试通过**

```bash
cd backend && uv run pytest tests/agent/test_orchestrator_emitter.py -v
```

Expected: 8 个 PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/src/agent/orchestrator.py backend/tests/agent/test_orchestrator_emitter.py
git commit -m "refactor(orch): confirm 路径走 AnalysisReady + mark_running/upsert_ready"
```

---

## Task 7：迁移 AnalysisDismissed 事件路径（dismiss + expired + abandoned）

**Files:**
- Modify: `backend/src/agent/orchestrator.py:289-342`（`dismiss_pending`、`_sweep_pending_ttl`）
- Modify: `backend/tests/agent/test_orchestrator_emitter.py`

- [ ] **Step 1: 加测试**

```python
from agent.events import AnalysisDismissed


@pytest.mark.asyncio
async def test_dismiss_pending_emits_dismissed(orch):
    fake_emitter = FakeEmitter()
    fake_repo = FakeRepoWriter()
    orch.set_event_emitter(fake_emitter)
    orch.set_repo_writer(fake_repo)

    from agent.orchestrator import PendingRequest

    class _FakeReq:
        def reject(self, _): pass

    class _FakeRun:
        active_requirements = [_FakeReq()]

    orch._pending["req_x"] = PendingRequest(
        request_id="req_x", run_id="r", utt_id="u", generation=0,
        preview={}, run_output=_FakeRun(),
    )
    # 替换 _abandon_run 中对 self._ha._db 的访问
    orch._ha._db = type("D", (), {"update_approval_run_status": lambda **_: None})()

    await orch.dismiss_pending("req_x")

    dismissed = [e for e in fake_emitter.received if isinstance(e, AnalysisDismissed)]
    assert len(dismissed) == 1
    assert dismissed[0].request_id == "req_x"
    assert dismissed[0].reason == "dismissed"
    assert ("mark_dismissed", {"request_id": "req_x"}) in fake_repo.calls


@pytest.mark.asyncio
async def test_ttl_expiry_emits_expired(orch, monkeypatch):
    """TTL 过期 → AnalysisDismissed(reason='expired') + mark_expired。"""
    import config
    monkeypatch.setattr(config, "PENDING_TTL", 0.1)

    fake_emitter = FakeEmitter()
    fake_repo = FakeRepoWriter()
    orch.set_event_emitter(fake_emitter)
    orch.set_repo_writer(fake_repo)

    from agent.orchestrator import PendingRequest
    import time as _time

    class _FakeReq:
        def reject(self, _): pass
    class _FakeRun:
        active_requirements = [_FakeReq()]

    orch._pending["req_y"] = PendingRequest(
        request_id="req_y", run_id="r", utt_id="u", generation=0,
        preview={}, run_output=_FakeRun(),
        created_at=_time.time() - 10,  # 已过期
    )
    orch._ha._db = type("D", (), {"update_approval_run_status": lambda **_: None})()

    await orch.start()
    # 等一轮 sweep
    await asyncio.sleep(0.3)
    await orch.shutdown()

    expired = [e for e in fake_emitter.received
               if isinstance(e, AnalysisDismissed) and e.reason == "expired"]
    assert len(expired) >= 1
    assert any(c[0] == "mark_expired" for c in fake_repo.calls)
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
cd backend && uv run pytest tests/agent/test_orchestrator_emitter.py::test_dismiss_pending_emits_dismissed tests/agent/test_orchestrator_emitter.py::test_ttl_expiry_emits_expired -v
```

Expected: 2 个 FAIL。

- [ ] **Step 3: 改 dismiss_pending + _sweep_pending_ttl**

替换 `dismiss_pending` 整段为：

```python
    async def dismiss_pending(self, request_id: str) -> None:
        pending = self._pending.pop(request_id, None)
        if pending is None:
            return
        await self._abandon_run(pending)
        if self._repo is not None:
            try:
                await self._repo.mark_dismissed(request_id)
            except Exception:
                logger.warning("mark_dismissed failed req=%s", request_id, exc_info=True)
        await self._emit_event(AnalysisDismissed(
            request_id=request_id, reason="dismissed",
        ))
```

替换 `_sweep_pending_ttl` 末尾 stale 处理块（约 339-342 行）为：

```python
            for rid in stale:
                pending = self._pending.pop(rid, None)
                if pending is None:
                    continue
                await self._abandon_run(pending)
                if self._repo is not None:
                    try:
                        await self._repo.mark_expired(rid)
                    except Exception:
                        logger.warning("mark_expired failed req=%s", rid, exc_info=True)
                await self._emit_event(AnalysisDismissed(
                    request_id=rid, reason="expired",
                ))
```

**同时删除** `set_expiry_callback` 和 `expiry_callback` 调用（已无业务用途）；以及 `_expiry_callback` 字段初始化。

- [ ] **Step 4: 测试通过**

```bash
cd backend && uv run pytest tests/agent/test_orchestrator_emitter.py -v
```

Expected: 10 个 PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/src/agent/orchestrator.py backend/tests/agent/test_orchestrator_emitter.py
git commit -m "refactor(orch): dismiss/expired/abandoned 走 AnalysisDismissed + 终态入库

删 set_expiry_callback (已被事件取代)。"
```

---

## Task 8：清理 Orchestrator 旧 callback + 旧 `_emit`

**Files:**
- Modify: `backend/src/agent/orchestrator.py`

> 此时所有事件路径已迁移完毕,旧 `_suggestion_callback / _profile_callback / _emit / set_suggestion_callback / set_profile_callback` 已无引用方。

- [ ] **Step 1: 跑现有测试基线**

```bash
cd backend && uv run pytest tests/agent/ -v
```

记录 PASS 数（应当 ≥10）。

- [ ] **Step 2: 删旧代码**

从 `backend/src/agent/orchestrator.py` 删除：

- `__init__` 中 `self._suggestion_callback = None`、`self._profile_callback = None`、`self._expiry_callback = None`
- `set_suggestion_callback`、`set_profile_callback`（已在 Task 7 删 `set_expiry_callback`）
- 末尾 `_emit` 方法

- [ ] **Step 3: 再跑测试**

```bash
cd backend && uv run pytest tests/agent/ -v
```

Expected: 与 Step 1 相同的 PASS 数（删除的是死代码）。

- [ ] **Step 4: 提交**

```bash
git add backend/src/agent/orchestrator.py
git commit -m "chore(orch): 删除已无引用的旧 callback 与 _emit"
```

---

## Task 9：main.py 改 emitter 接线 + typed inbound 应答

**Files:**
- Modify: `backend/main.py`（多段：consume_stt、_handle_text_message、WS handler）

> 本任务是把 Orchestrator 已就绪的 emitter / repo_writer 接到 WebSocket 上。

- [ ] **Step 1: 加 send_event 辅助 + RepoWriter 适配器**

`main.py` 顶部 import 区加：

```python
from agent.events import (
    OutboundEvent, TranscriptDelta, ConfirmAck, ErrorEvent, Pong,
)
from repositories.suggestions import SuggestionRepository
```

在 `_safe_send_json` 旁边加（独立函数，复用 `_safe_send_json`）：

```python
async def _send_event(ws: WebSocket, evt: OutboundEvent) -> None:
    await _safe_send_json(ws, evt.model_dump())
```

在 `_handle_text_message` 上方加 RepoWriter 适配器：

```python
class _DbRepoWriter:
    """绑定 sessionmaker + session_id 的 SuggestionRepository facade,
    给 Orchestrator 注入。每次调用打开一个独立 session,与 ws 生命周期解耦。"""

    def __init__(self, sessionmaker, session_id: uuid.UUID) -> None:
        self._sm = sessionmaker
        self._sid = session_id

    async def insert_direct(self, *, utt_id: str, text: str) -> None:
        async with self._sm() as s:
            await SuggestionRepository(s).insert_direct(
                self._sid, utt_id=utt_id, text=text,
            )

    async def upsert_pending(self, *, utt_id: str, request_id: str,
                              preview_topic, preview_rationale) -> None:
        async with self._sm() as s:
            await SuggestionRepository(s).upsert_pending(
                self._sid, utt_id=utt_id, request_id=request_id,
                preview_topic=preview_topic, preview_rationale=preview_rationale,
            )

    async def mark_running(self, request_id: str) -> None:
        async with self._sm() as s:
            await SuggestionRepository(s).mark_running(self._sid, request_id)

    async def upsert_ready(self, *, request_id: str, text: str,
                            utt_id: str | None) -> None:
        async with self._sm() as s:
            await SuggestionRepository(s).upsert_ready(
                self._sid, request_id=request_id, text=text, utt_id=utt_id,
            )

    async def mark_dismissed(self, request_id: str) -> None:
        async with self._sm() as s:
            await SuggestionRepository(s).mark_dismissed(self._sid, request_id)

    async def mark_expired(self, request_id: str) -> None:
        async with self._sm() as s:
            await SuggestionRepository(s).mark_expired(self._sid, request_id)
```

- [ ] **Step 2: 改 `_handle_text_message`**

把现有 `_handle_text_message` 内部三个 `_safe_send_json(ws, {...})` 调用改成：

```python
    if msg_type == "ping":
        await _send_event(ws, Pong())
        return False

    if msg_type == "confirm":
        request_id = msg.get("request_id")
        if request_id:
            ok = await orch.confirm_analysis(request_id)
            await _send_event(ws, ConfirmAck(request_id=request_id, ok=ok))
        return False

    if msg_type == "dismiss":
        request_id = msg.get("request_id")
        if request_id:
            await orch.dismiss_pending(request_id)
        return False
```

同时把"Invalid JSON" 错误改 typed：

```python
                    await _send_event(ws, ErrorEvent(message="Invalid JSON"))
```

删掉旧注释 `# running 不存 DB（中间状态）...` 与 `# dismissed 不存 DB（中间状态）...`（已不准确）。

- [ ] **Step 3: 改 consume_stt**

替换 `consume_stt` 内的 transcript 推送为：

```python
                    await _send_event(ws, TranscriptDelta(
                        utt_id=utt.id,
                        speaker=utt.speaker or "uncertain",
                        text=utt.text,
                        t_start=utt.t_start,
                        t_end=utt.t_end,
                        closed_by=utt.closed_by,
                    ))
```

- [ ] **Step 4: WS handler 主体替换 callback wiring**

把 `legal_session` 里 `on_suggestion / on_profile_update` 两块整段（约 266-331 行）和它们的 `set_*_callback` 调用，**全部删掉**。在 `await orch.start()` **之前** 加：

```python
        orch.set_event_emitter(lambda evt: _send_event(ws, evt))
        orch.set_repo_writer(_DbRepoWriter(_maker, sid_uuid))
```

- [ ] **Step 5: 全量测试**

```bash
cd backend && uv run pytest -v
```

Expected: 全部 PASS。任何 callback 引用残留会在导入时报 AttributeError，必须清干净。

- [ ] **Step 6: 启动手测（关键 sanity check）**

```bash
cd backend && uv run uvicorn main:app --reload
```

另开终端：

```bash
cd backend && uv run python -c "
import asyncio, json, websockets, httpx
async def main():
    async with httpx.AsyncClient() as c:
        r = await c.post('http://localhost:8000/api/sessions')
        sid = r.json()['session_id']
    async with websockets.connect(f'ws://localhost:8000/ws/{sid}') as ws:
        await ws.send(json.dumps({'type': 'ping'}))
        print(await ws.recv())
asyncio.run(main())
"
```

Expected: 打印 `{"type": "pong"}`。证明 typed event 走通了 send path。

- [ ] **Step 7: 提交**

```bash
git add backend/main.py
git commit -m "feat(ws): main.py 改单 send_event + DbRepoWriter,删 3 个 callback"
```

---

## Task 10：前端 ServerEvent 类型 + 简化 Insight

**Files:**
- Create: `frontend/src/types/events.ts`
- Modify: `frontend/src/types/index.ts:1-15`（Insight + InsightCategory）
- Modify: `frontend/src/components/insights/InsightCard.tsx`（整体重写）

- [ ] **Step 1: 创建 events.ts**

`frontend/src/types/events.ts`：

```ts
// 后端 backend/src/agent/events.py 的镜像。
// 改后端 schema 时必须同步本文件——CI 无法强制,靠 PR review 把关。

export type TranscriptDelta = {
  type: 'transcript'
  utt_id: string
  speaker: string  // 'lawyer' | 'client' | 'uncertain' (后端是宽 string)
  text: string
  t_start: number
  t_end: number
  closed_by: string | null
  is_final: boolean
}

export type InsightReady = {
  type: 'insight.ready'
  id: string
  utt_id: string
  text: string
}

export type AnalysisProposed = {
  type: 'analysis.proposed'
  request_id: string
  utt_id: string
  topic: string
  rationale: string
}

export type AnalysisReady = {
  type: 'analysis.ready'
  request_id: string
  utt_id: string
  text: string
}

export type AnalysisDismissed = {
  type: 'analysis.dismissed'
  request_id: string
  reason: 'dismissed' | 'expired' | 'abandoned'
}

export type ProfileEntryPayload = {
  key: string
  value: string
  subject: string
}

export type ProfileUpdated = {
  type: 'profile.updated'
  entries: ProfileEntryPayload[]
}

export type ConfirmAck = { type: 'confirm_ack'; request_id: string; ok: boolean }
export type ErrorEvent = { type: 'error'; message: string }
export type Pong = { type: 'pong' }

export type ServerEvent =
  | TranscriptDelta
  | InsightReady
  | AnalysisProposed
  | AnalysisReady
  | AnalysisDismissed
  | ProfileUpdated
  | ConfirmAck
  | ErrorEvent
  | Pong
```

- [ ] **Step 2: 简化 Insight 类型**

修改 `frontend/src/types/index.ts` 顶部：

```ts
// 把现有的 InsightCategory + Insight 块（约 1-15 行）替换为：
export type Insight = {
  id: string
  uttId: string
  text: string
  createdAt: string
}
```

- [ ] **Step 3: 重写 InsightCard**

`frontend/src/components/insights/InsightCard.tsx` 完整替换为：

```tsx
import { Sparkles } from 'lucide-react'
import type { Insight } from '@/types'

export type InsightCardProps = { insight: Insight }

export default function InsightCard({ insight }: InsightCardProps) {
  return (
    <div className="py-4 border-t border-border-color first:border-t-0">
      <div className="flex items-center gap-2 mb-2">
        <Sparkles className="w-3 h-3 text-accent" />
        <span className="text-xs font-medium text-accent">实时洞察</span>
      </div>
      <p className="text-sm text-ink-secondary leading-relaxed whitespace-pre-wrap">
        {insight.text}
      </p>
    </div>
  )
}
```

- [ ] **Step 4: 跑前端类型检查**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: PASS。任何残留对 `insight.category / title / citation / riskLevel` 的引用会在这里被发现。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/types/events.ts frontend/src/types/index.ts frontend/src/components/insights/InsightCard.tsx
git commit -m "feat(types): ServerEvent 镜像 + Insight 简化为 {id,uttId,text}"
```

---

## Task 11：reducer 加 RECV_EVENT action

**Files:**
- Modify: `frontend/src/context/session-context.ts`
- Modify: `frontend/src/context/SessionContext.tsx`
- Create: `frontend/src/__tests__/sessionReducer.test.ts`

- [ ] **Step 1: 把 reducer 抽到独立文件以便测试**

注意：当前 reducer 内联在 `SessionContext.tsx` 里，测试不便。先把 reducer 抽出。

新增 `frontend/src/context/sessionReducer.ts`：

```ts
import type { ServerEvent } from '@/types/events'
import type {
  SessionAction, SessionState,
} from './session-context'
import { entriesToProfile } from '@/types'
import type {
  ConnectionStatus, Insight, Profile, ProfileEntryItem,
  RecordingStatus, Suggestion, TranscriptLine,
} from '@/types'

function recvEvent(state: SessionState, evt: ServerEvent): SessionState {
  switch (evt.type) {
    case 'transcript': {
      const line: TranscriptLine = {
        id: evt.utt_id,
        speaker: (evt.speaker as TranscriptLine['speaker']) ?? 'uncertain',
        text: evt.text,
        timestamp: evt.t_start,
      }
      return { ...state, transcripts: [...state.transcripts, line] }
    }
    case 'insight.ready': {
      const insight: Insight = {
        id: evt.id,
        uttId: evt.utt_id,
        text: evt.text,
        createdAt: new Date().toISOString(),
      }
      return { ...state, insights: [insight, ...state.insights] }
    }
    case 'analysis.proposed': {
      const exists = state.suggestions.some((s) => s.requestId === evt.request_id)
      if (exists) return state
      const sug: Suggestion = {
        id: evt.request_id,
        requestId: evt.request_id,
        status: 'pending',
        topic: evt.topic,
        rationale: evt.rationale,
        text: null,
        createdAt: new Date().toISOString(),
      }
      return { ...state, suggestions: [sug, ...state.suggestions] }
    }
    case 'analysis.ready':
      return {
        ...state,
        suggestions: state.suggestions.map((s) =>
          s.requestId === evt.request_id
            ? { ...s, status: 'ready', text: evt.text }
            : s
        ),
      }
    case 'analysis.dismissed':
      return {
        ...state,
        suggestions: state.suggestions.filter((s) => s.requestId !== evt.request_id),
      }
    case 'profile.updated': {
      const merged: ProfileEntryItem[] = [
        ...(state.profile?.entries ?? []),
        ...evt.entries,
      ]
      return { ...state, profile: entriesToProfile(merged) }
    }
    case 'confirm_ack':
      // ok=false 时把 suggestion 移除(后端拒绝了 confirm)
      return evt.ok
        ? state
        : {
            ...state,
            suggestions: state.suggestions.filter((s) => s.requestId !== evt.request_id),
          }
    case 'error':
    case 'pong':
      return state
    default: {
      // exhaustive 检查:加新事件而未在此分派,TS 报错
      const _exhaustive: never = evt
      void _exhaustive
      return state
    }
  }
}

export function sessionReducer(state: SessionState, action: SessionAction): SessionState {
  switch (action.type) {
    case 'RECV_EVENT':
      return recvEvent(state, action.payload)
    case 'SET_SESSION_ID':
      return { ...state, sessionId: action.payload }
    case 'SET_PROFILE':
      return { ...state, profile: action.payload }
    case 'ADD_INSIGHT':
      return { ...state, insights: [action.payload, ...state.insights] }
    case 'ADD_SUGGESTION': {
      const exists = state.suggestions.some((s) => s.requestId === action.payload.requestId)
      if (exists) return state
      return { ...state, suggestions: [action.payload, ...state.suggestions] }
    }
    case 'UPDATE_SUGGESTION':
      return {
        ...state,
        suggestions: state.suggestions.map((s) =>
          s.requestId === action.payload.requestId
            ? { ...s, ...action.payload.updates }
            : s
        ),
      }
    case 'DISMISS_SUGGESTION':
      return {
        ...state,
        suggestions: state.suggestions.filter((s) => s.requestId !== action.payload),
      }
    case 'ADD_TRANSCRIPT':
      return { ...state, transcripts: [...state.transcripts, action.payload] }
    case 'SET_CONNECTION_STATUS':
      return { ...state, connectionStatus: action.payload }
    case 'SET_RECORDING_STATUS':
      return { ...state, recordingStatus: action.payload }
    case 'TOGGLE_TRANSCRIPT_PANEL':
      return { ...state, isTranscriptPanelOpen: !state.isTranscriptPanelOpen }
    case 'SET_ACTIVE_MOBILE_TAB':
      return { ...state, activeMobileTab: action.payload }
    case 'HYDRATE':
      return { ...state, ...action.payload }
    default:
      return state
  }
}

```

> Import 区按实际用到的类型清理（`ConnectionStatus / Profile / RecordingStatus` 等如果用不到就别 import）；TS unused-import 报错时删即可。

- [ ] **Step 2: 修改 session-context.ts，加 RECV_EVENT action 类型**

在 `SessionAction` union 头部加：

```ts
import type { ServerEvent } from '@/types/events'

export type SessionAction =
  | { type: 'RECV_EVENT'; payload: ServerEvent }
  | { type: 'SET_SESSION_ID'; payload: string }
  // ... 其余保留
```

`SessionContextValue` 加：

```ts
  recvEvent: (evt: ServerEvent) => void
```

- [ ] **Step 3: 修改 SessionContext.tsx**

把内联的 `sessionReducer` 删除，改为：

```tsx
import { sessionReducer } from './sessionReducer'
```

`SessionProvider` 内加：

```tsx
  const recvEvent = useCallback(
    (evt: ServerEvent) => dispatch({ type: 'RECV_EVENT', payload: evt }),
    []
  )
```

并在 provider value 里加 `recvEvent`。`import type { ServerEvent } from '@/types/events'`。

- [ ] **Step 4: 写 reducer 测试**

`frontend/src/__tests__/sessionReducer.test.ts`：

```ts
import { describe, it, expect } from 'vitest'
import { sessionReducer } from '@/context/sessionReducer'
import { initialState } from '@/context/session-context'
import type { ServerEvent } from '@/types/events'

const recv = (evt: ServerEvent) =>
  sessionReducer(initialState, { type: 'RECV_EVENT', payload: evt })

describe('sessionReducer.RECV_EVENT', () => {
  it('transcript → 追加到 transcripts', () => {
    const s = recv({
      type: 'transcript', utt_id: 'u1', speaker: 'lawyer',
      text: 'hi', t_start: 0, t_end: 1, closed_by: null, is_final: true,
    })
    expect(s.transcripts).toHaveLength(1)
    expect(s.transcripts[0]).toMatchObject({ id: 'u1', text: 'hi', speaker: 'lawyer' })
  })

  it('insight.ready → 加到 insights 头部', () => {
    const s = recv({ type: 'insight.ready', id: 'ins_1', utt_id: 'u1', text: '洞察' })
    expect(s.insights).toHaveLength(1)
    expect(s.insights[0]).toMatchObject({ id: 'ins_1', uttId: 'u1', text: '洞察' })
  })

  it('analysis.proposed → 新建 pending suggestion (幂等)', () => {
    const evt: ServerEvent = {
      type: 'analysis.proposed', request_id: 'req_1', utt_id: 'u1',
      topic: 'T', rationale: 'R',
    }
    const s1 = sessionReducer(initialState, { type: 'RECV_EVENT', payload: evt })
    const s2 = sessionReducer(s1, { type: 'RECV_EVENT', payload: evt })
    expect(s1.suggestions).toHaveLength(1)
    expect(s2.suggestions).toHaveLength(1)  // 幂等
    expect(s1.suggestions[0]).toMatchObject({ status: 'pending', topic: 'T' })
  })

  it('analysis.ready → 把同 request_id 的 suggestion 改 ready', () => {
    const s1 = recv({
      type: 'analysis.proposed', request_id: 'req_1', utt_id: 'u1',
      topic: 'T', rationale: 'R',
    })
    const s2 = sessionReducer(s1, {
      type: 'RECV_EVENT',
      payload: { type: 'analysis.ready', request_id: 'req_1', utt_id: 'u1', text: '深度' },
    })
    expect(s2.suggestions[0]).toMatchObject({ status: 'ready', text: '深度' })
  })

  it('analysis.dismissed → 移除 suggestion', () => {
    const s1 = recv({
      type: 'analysis.proposed', request_id: 'req_1', utt_id: 'u1',
      topic: 'T', rationale: 'R',
    })
    const s2 = sessionReducer(s1, {
      type: 'RECV_EVENT',
      payload: { type: 'analysis.dismissed', request_id: 'req_1', reason: 'dismissed' },
    })
    expect(s2.suggestions).toHaveLength(0)
  })

  it('profile.updated → merge entries 并生成 Profile', () => {
    const s = recv({
      type: 'profile.updated',
      entries: [{ key: '姓名', value: '张三', subject: 'client' }],
    })
    expect(s.profile).not.toBeNull()
    expect(s.profile!.entries).toHaveLength(1)
  })

  it('confirm_ack ok=false → 移除对应 suggestion', () => {
    const s1 = recv({
      type: 'analysis.proposed', request_id: 'req_1', utt_id: 'u1',
      topic: 'T', rationale: 'R',
    })
    const s2 = sessionReducer(s1, {
      type: 'RECV_EVENT',
      payload: { type: 'confirm_ack', request_id: 'req_1', ok: false },
    })
    expect(s2.suggestions).toHaveLength(0)
  })

  it('pong / error → 状态不变', () => {
    const s1 = recv({ type: 'pong' })
    const s2 = recv({ type: 'error', message: 'x' })
    expect(s1).toEqual(initialState)
    expect(s2).toEqual(initialState)
  })
})
```

- [ ] **Step 5: 跑测试**

```bash
cd frontend && pnpm test src/__tests__/sessionReducer.test.ts
```

Expected: 8 个 PASS。

- [ ] **Step 6: 跑 tsc**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: PASS。

- [ ] **Step 7: 提交**

```bash
git add frontend/src/context frontend/src/__tests__/sessionReducer.test.ts
git commit -m "feat(state): RECV_EVENT action + reducer exhaustive switch"
```

---

## Task 12：useWebSocket 收敛为单 onEvent

**Files:**
- Modify: `frontend/src/hooks/useWebSocket.ts`

- [ ] **Step 1: 改 hook 签名**

完整替换 `useWebSocket.ts`：

```ts
import { useRef, useState, useCallback, useEffect } from 'react'
import type { ServerEvent } from '@/types/events'

export function useWebSocket(
  sessionId: string,
  onEvent: (evt: ServerEvent) => void,
) {
  const [isConnected, setIsConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const pingRef = useRef<ReturnType<typeof setInterval>>(null)
  const reconnectRef = useRef<ReturnType<typeof setTimeout>>(null)
  const onEventRef = useRef(onEvent)
  const connectRef = useRef<() => void>(() => {})
  const reconnectAttemptsRef = useRef(0)
  const maxReconnectAttempts = 3

  const wsUrl = `ws://localhost:8000/ws/${sessionId}`

  const cleanup = useCallback(() => {
    if (reconnectRef.current) clearTimeout(reconnectRef.current)
    if (pingRef.current) clearInterval(pingRef.current)
    const ws = wsRef.current
    if (ws) {
      ws.onopen = null
      ws.onmessage = null
      ws.onclose = null
      ws.onerror = null
      ws.close()
    }
    wsRef.current = null
  }, [])

  const connect = useCallback(() => {
    if (!sessionId) return
    cleanup()
    const ws = new WebSocket(wsUrl)

    ws.onopen = () => {
      setIsConnected(true)
      setError(null)
      reconnectAttemptsRef.current = 0
      pingRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'ping' }))
        } else if (pingRef.current) {
          clearInterval(pingRef.current)
        }
      }, 15_000)
    }

    ws.onclose = (e: CloseEvent) => {
      setIsConnected(false)
      if (e.code >= 4000 && e.code < 5000) {
        setError(e.reason || `连接已关闭 (code=${e.code})`)
        return
      }
      if (reconnectAttemptsRef.current < maxReconnectAttempts) {
        reconnectAttemptsRef.current += 1
        reconnectRef.current = setTimeout(() => connectRef.current(), 2000)
      } else {
        setError(`连接重试 ${maxReconnectAttempts} 次后放弃 (code=${e.code})`)
      }
    }

    ws.onmessage = (e: MessageEvent) => {
      try {
        const evt = JSON.parse(e.data) as ServerEvent
        onEventRef.current(evt)
      } catch {
        // 无效 JSON 直接丢弃,后端理论上不会发
      }
    }

    wsRef.current = ws
  }, [wsUrl, cleanup, sessionId])

  useEffect(() => {
    onEventRef.current = onEvent
    connectRef.current = connect
  })

  useEffect(() => {
    connect()
    return cleanup
  }, [connect, cleanup])

  const sendAudioChunk = useCallback((chunk: Uint8Array) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(chunk.buffer as ArrayBuffer)
    }
  }, [])

  const confirmIntent = useCallback((requestId: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'confirm', request_id: requestId }))
    }
  }, [])

  const dismissIntent = useCallback((requestId: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'dismiss', request_id: requestId }))
    }
  }, [])

  const notifyAudioEnd = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'audio_end' }))
    }
  }, [])

  const reconnect = useCallback(() => {
    reconnectAttemptsRef.current = 0
    setError(null)
    connect()
  }, [connect])

  return {
    isConnected, error,
    sendAudioChunk, confirmIntent, dismissIntent, notifyAudioEnd, reconnect,
  }
}
```

> 旧 `Callbacks` / `SuggestionData` / `TranscriptData` / `AnalysisData` 类型导出全部删除。

- [ ] **Step 2: 跑 tsc**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: **会失败** —— `LiveSession.tsx` 还用着旧 Callbacks 接口。这是预期的，下个 Task 修。

- [ ] **Step 3: 暂不 commit**（与 Task 13 一起 commit，避免中间状态破 build）

---

## Task 13：LiveSession.tsx 改单 dispatch + 验证

**Files:**
- Modify: `frontend/src/pages/LiveSession.tsx`

- [ ] **Step 1: 替换 LiveSession 内的 callbacks 接线**

`LiveSession.tsx` 改动点：

1. 删除 `onTranscript / onAnalysis / onSuggestion` 三个 `useCallback` 块（约 182-235 行）。
2. `useSession()` 解构里加 `recvEvent`，删 `addInsight / addSuggestion / updateSuggestion / dismissSuggestion / addTranscript / setProfile`（保留 `state / setProfile / setConnectionStatus / setSessionId / hydrate / toggleTranscriptPanel`；hydrate 路径仍要 setProfile，所以保留）。
3. 把 useWebSocket 调用改成：

```tsx
  const {
    isConnected, error: wsError,
    sendAudioChunk, confirmIntent, dismissIntent, notifyAudioEnd, reconnect,
  } = useWebSocket(
    hydrated ? (sessionId ?? '') : '',
    recvEvent,  // 单一 dispatch
  )
```

4. `handleConfirm` 简化为：

```tsx
  const handleConfirm = useCallback(
    (requestId: string) => {
      confirmIntent(requestId)
      // ready 状态等服务端 analysis.ready 事件回来,这里不再本地预改
    },
    [confirmIntent]
  )

  const handleDismiss = useCallback(
    (requestId: string) => {
      dismissIntent(requestId)
      // 卡片消失等 analysis.dismissed 事件
    },
    [dismissIntent]
  )
```

> spec 第 4 个问题已确认接受这点 RTT 延迟。本地预改会导致 reducer 状态与服务端不一致的窗口。

5. 删除 `SuggestionData` import（已不存在）。

- [ ] **Step 2: 跑 tsc**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: PASS。

- [ ] **Step 3: 跑前端测试**

```bash
cd frontend && pnpm test
```

Expected: 全部 PASS（含 Task 11 加的 reducer test）。

- [ ] **Step 4: 提交 Task 12+13 合并**

```bash
git add frontend/src/hooks/useWebSocket.ts frontend/src/pages/LiveSession.tsx
git commit -m "refactor(ws): 前端单 onEvent dispatch RECV_EVENT,删多 callback 接线"
```

---

## Task 14：手工验证 + 收尾

- [ ] **Step 1: 后端启动**

```bash
cd backend && uv run uvicorn main:app --reload
```

- [ ] **Step 2: 前端启动**

```bash
cd frontend && pnpm dev
```

- [ ] **Step 3: 验证矩阵（浏览器手测，每条都要看到）**

| 场景 | 操作 | 期望 |
|------|------|------|
| 转写 | 录一段对话 | 转写面板逐句出现 |
| 直接洞察 | 客户描述一个简单问题 | InsightCard 出现，文本来自 HeavyAgent |
| 深度分析提议 | 客户描述复杂场景触发 deep_analysis | SuggestionCard 出现 pending |
| 深度分析确认 | 点 confirm | 卡片变 ready，正文出现 |
| dismiss | 点 dismiss | 卡片消失（服务端事件回来后） |
| 画像更新 | 客户提到姓名 / 案由 | 画像面板字段实时更新 |
| 刷新恢复 | F5 | 转写 / suggestion / profile 三类都恢复 |

- [ ] **Step 4: 跑全套测试最终复核**

```bash
cd backend && uv run pytest
cd frontend && pnpm test && pnpm tsc --noEmit
```

Expected: 全部 PASS。

- [ ] **Step 5: 删 spec 中的「已知开放问题」记录到的 HeavyAgent 直出确认**

如果手测中确实看到 InsightCard 出现，说明 HeavyAgent 会走非 gated 路径。在 spec 末尾的"已知开放问题"段移除"是否真会输出直接文本"那条（用 commit message 记录"验证通过"）。

如果手测中**没看到** InsightCard：说明 HeavyAgent 强制走 gated，需要另开 issue 调整 prompt（属于本 plan 范围外）。

- [ ] **Step 6: 收尾 commit**

```bash
git add backend/docs/superpowers/specs/2026-05-31-typed-ws-events-design.md
git commit -m "docs: 关闭 typed-ws-events spec 的开放问题(手测验证 HeavyAgent 直出路径)"
```

---

## 验证标准（来自 spec）

- [ ] 直接洞察可见：客户简单描述 → InsightCard 出现
- [ ] 深度分析仍可用：触发 deep_analysis → pending → confirm → ready
- [ ] dismiss / TTL 过期：卡片消失（事件驱动而非本地）
- [ ] 画像实时更新
- [ ] 刷新恢复：三类数据无重复
- [ ] 后端测试 `tests/agent/test_orchestrator_emitter.py` 覆盖 5 条事件路径
- [ ] 前端 reducer 删任一 case TS 报错（exhaustive 检查）
