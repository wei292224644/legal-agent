# 实时事件契约化：Typed Envelope + 职责分层

## 背景与问题

当前 WebSocket 通信路径是「callback + dict + 字符串 type」的胶水代码，已暴露多个 bug：

1. **直接洞察被静默丢弃**：HeavyAgent 非 gated 路径产出的 `kind=ready` 事件（无 `request_id`）经 `on_suggestion` 发出 `suggestion.ready`（meta 无 request_id），前端 `LiveSession.tsx:223-232` 走 `if (rid)` 分支，无 rid 就什么都不做。
2. **`onAnalysis` 是孤儿**：前端 `useWebSocket.ts:125-128` 监听 `type: 'analysis'` 往 `insights[]` 写，但后端从未发送该 type。`addInsight` 永远不会被调用。
3. **schema 没契约**：后端 `_emit(text, meta: dict)`，前端按「type + meta.request_id 是否存在」组合解码业务语义。任何字段重命名都不会被任一端发现。
4. **持久化和推送同住一个 callback**：`main.py:266-314` `on_suggestion` 既写 `SuggestionRepository` 又 `ws.send_json`，任一抛错污染另一个；测试无法单独验证。
5. **后端 `kind` 和前端 `type` 是两套词汇**：靠 callback 翻译（`kind=ready` + `request_id is None` → 直接洞察；`kind=ready` + `request_id` → 深度分析结果），位组合解码。
6. **错误处理标准不一**：`profile_update` 用 `_safe_send_json`，`suggestion` 用裸 `ws.send_json`。

根因不是任一条 if/else，而是「业务事件、WS 传输、持久化」三个职责糊在了 callback 层。

## 目标

- **后端发出的每个 WS 消息都是 typed 领域事件**（Pydantic discriminated union），编译期/运行期都拒绝散字段。
- **持久化与 WS 推送解耦**：DB 写入由 Orchestrator 内部完成，callback 只负责把事件 dump 到 WS。
- **前端 reducer 用 discriminated union**，`switch (evt.type)` 漏 case 时 TS 编译报错。
- **后端业务事件 vs WS 消息一一对应**，删除中间翻译层。
- **修复上述 5 个具体 bug**（直接洞察可见、insight.ready 单独通道、profile_update 标准化错误处理）。

## 非目标

- 不引入 EventBus 框架。仍是单 callback 注入，但参数类型化。
- 不重构 Orchestrator 的并发模型 / TTL 扫描 / pending 卡片生命周期。
- 不动 STT、ProfileAgent、HeavyAgent 内部逻辑。
- 不重写 SQL schema 或 Repository 接口。
- 不引入 codegen（pydantic2ts 等），TS 类型手写镜像后端。

## 事件契约（新增 `backend/src/agent/events.py`）

> 文件位置选 `agent/` 而不是 `models/`，因为它是 Orchestrator 的对外协议，与 Utterance/ProfileEntry 这种内部领域模型职责不同。

```python
"""WS 出站事件契约。Orchestrator 通过此契约对外说话；main.py 只负责
dump 到 WebSocket，不做任何业务判断。"""

from typing import Annotated, Literal
from pydantic import BaseModel, Field

class TranscriptDelta(BaseModel):
    """STT 出句。来自 stt 任务而非 Orchestrator。"""
    type: Literal["transcript"] = "transcript"
    utt_id: str
    speaker: str  # "lawyer" | "client" | "uncertain"
    text: str
    t_start: float
    t_end: float
    closed_by: str | None = None
    is_final: bool = True

class InsightReady(BaseModel):
    """HeavyAgent 非 gated 路径直出的实时洞察。"""
    type: Literal["insight.ready"] = "insight.ready"
    id: str           # server 生成的 insight id，前端用作 React key
    utt_id: str
    text: str

class AnalysisProposed(BaseModel):
    """HeavyAgent 调用 gated deep_analysis 工具，等律师确认。"""
    type: Literal["analysis.proposed"] = "analysis.proposed"
    request_id: str
    utt_id: str
    topic: str
    rationale: str

class AnalysisReady(BaseModel):
    """律师 confirm 后续跑完成。"""
    type: Literal["analysis.ready"] = "analysis.ready"
    request_id: str
    utt_id: str
    text: str

class AnalysisDismissed(BaseModel):
    """律师 dismiss 或 TTL 过期。前端用此事件把卡片淡出。"""
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
    """text 协议入站消息的应答，保留现有语义。"""
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

**关键约束：**
- `type` 是 string literal，**作为前后端唯一约定的协议码**。命名采用 `domain.action` 风格（`insight.ready`、`analysis.proposed`），便于扩展。
- 所有事件都是 Pydantic `BaseModel`：`model_dump()` 即可上 WS。
- `OutboundEvent` 是 discriminated union，未来加新事件只需新增 class 并加入 union。

## Orchestrator 改造

### 接口变化

**删除：**
- `set_suggestion_callback(callback)` —— 替换为 `set_event_emitter(emit)`
- `set_profile_callback(callback)` —— 合并到统一 emitter
- `set_expiry_callback(callback)` —— 合并到统一 emitter（发 `AnalysisDismissed(reason="expired")`）
- 内部 `_emit(meta: dict, text: str | None)` —— 替换为 `_emit_event(evt: OutboundEvent)`

**新增：**
```python
def set_event_emitter(self, emit: Callable[[OutboundEvent], Awaitable[None]]) -> None:
    self._emit_event = emit
```

### 持久化抽离

`_run_child` / `confirm_analysis` / `_sweep_pending_ttl` 现在自己写 DB，再发事件：

```python
async def _run_child(self, utt: Utterance, generation: int) -> None:
    # ...timeout 包裹同前...
    if self._ctx.get_generation() != generation:
        return

    if not run.is_paused:
        # 直接洞察分支
        text = getattr(run, "content", None) or ""
        if text.strip():
            insight_id = f"ins_{uuid.uuid4().hex[:8]}"
            await self._persist_insight(utt.id, insight_id, text)
            await self._emit_event(InsightReady(
                id=insight_id, utt_id=utt.id, text=text,
            ))
        return

    # paused 分支：proposed
    req = run.active_requirements[0] if run.active_requirements else None
    tool_args = dict(req.tool_execution.tool_args) if req and req.tool_execution else {}
    topic = tool_args.get("topic", "")
    rationale = tool_args.get("rationale", "")

    request_id = f"req_{uuid.uuid4().hex[:8]}"
    self._pending[request_id] = PendingRequest(
        request_id=request_id, run_id=run.run_id, utt_id=utt.id,
        generation=generation, preview={"topic": topic, "rationale": rationale},
        run_output=run,
    )
    await self._persist_analysis_proposed(utt.id, request_id, topic, rationale)
    await self._emit_event(AnalysisProposed(
        request_id=request_id, utt_id=utt.id, topic=topic, rationale=rationale,
    ))
```

`_persist_insight` / `_persist_analysis_proposed` 是 Orchestrator 私有方法，封装对 `SuggestionRepository` 的写入。注入方式：**构造期注入一个 `repo_factory: Callable[[], AsyncContextManager[SuggestionRepository]]`**，避免把 sessionmaker 直接拖进 Orchestrator。

### Profile 路径

`handle_utterance` 内 ProfileAgent 出 entries 后：
```python
await self._ctx.enqueue_profile_update(utt.id, entries)
await self._emit_event(ProfileUpdated(
    entries=[ProfileEntryPayload(key=e.key, value=e.value, subject=e.subject) for e in entries]
))
```

### Confirm/Dismiss 路径

```python
async def confirm_analysis(self, request_id: str) -> bool:
    # ...原 acontinue_run 逻辑...
    text = getattr(run, "content", None) or ""
    await self._persist_analysis_ready(request_id, text)
    await self._emit_event(AnalysisReady(
        request_id=request_id, utt_id=pending.utt_id, text=text,
    ))
    return True

async def dismiss_pending(self, request_id: str) -> None:
    # ...原 _abandon_run 逻辑...
    await self._emit_event(AnalysisDismissed(
        request_id=request_id, reason="dismissed",
    ))
```

TTL sweep 内的 `expiry_callback` 改为：
```python
for rid in stale:
    pending = self._pending.pop(rid, None)
    if pending:
        await self._abandon_run(pending)
        await self._emit_event(AnalysisDismissed(
            request_id=rid, reason="expired",
        ))
```

### 错误处理

`_emit_event` 内部包 try/except 兜底，所有异常 `logger.warning` 记录但不重抛——Orchestrator 不知道 WebSocket 存在，所以也不该 catch `WebSocketDisconnect`。WS 层面的断开由 main.py 的 `send_event` 通过 `_safe_send_json` 吞掉，Orchestrator 这里只是兜底防止"发事件失败"污染其他事件路径。

```python
async def _emit_event(self, evt: OutboundEvent) -> None:
    if self._emitter is None:
        return
    try:
        await self._emitter(evt)
    except Exception:
        logger.warning("emit_event failed for %s", evt.type, exc_info=True)
```

## main.py 改造

WS handler 内部：

```python
async def send_event(evt: OutboundEvent) -> None:
    await _safe_send_json(ws, evt.model_dump())

orch.set_event_emitter(send_event)

# 删除 on_suggestion、on_profile_update、on_expiry 三个 callback
# 删除 SuggestionRepository 在 callback 里的调用（已迁入 Orchestrator）
```

入站消息（`_handle_text_message`）保持 `ping/confirm/dismiss/end` 现有语义，应答仍用 typed event：

```python
await _safe_send_json(ws, Pong().model_dump())
await _safe_send_json(ws, ConfirmAck(request_id=rid, ok=ok).model_dump())
```

`consume_stt` 内的 transcript 推送改用 `TranscriptDelta`：
```python
await send_event(TranscriptDelta(
    utt_id=utt.id, speaker=utt.speaker or "uncertain",
    text=utt.text, t_start=utt.t_start, t_end=utt.t_end,
    closed_by=utt.closed_by,
))
```

## 前端类型镜像（新增 `frontend/src/types/events.ts`）

```ts
export type TranscriptDelta = {
  type: 'transcript'
  utt_id: string
  speaker: 'lawyer' | 'client' | 'uncertain'
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

export type ProfileUpdated = {
  type: 'profile.updated'
  entries: Array<{ key: string; value: string; subject: string }>
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

**约定**：当后端 `events.py` 增删字段，必须同步本文件——CI 无法强制，靠 PR 标题约定 `[ws-protocol]` 前缀提醒 reviewer。

## useWebSocket 简化

删 `Callbacks` 接口，只暴露单个 `onEvent: (evt: ServerEvent) => void`：

```ts
export function useWebSocket(sessionId: string, onEvent: (e: ServerEvent) => void) {
  // ...
  ws.onmessage = (e) => {
    let evt: ServerEvent
    try { evt = JSON.parse(e.data) as ServerEvent } catch { return }
    onEventRef.current(evt)
  }
  // ...
}
```

调用方在 `LiveSession.tsx` 用 `useReducer` + exhaustive switch：

```ts
function reducer(state: SessionState, evt: ServerEvent): SessionState {
  switch (evt.type) {
    case 'transcript':
      return { ...state, transcripts: [...state.transcripts, toTranscript(evt)] }
    case 'insight.ready':
      return { ...state, insights: [...state.insights, toInsight(evt)] }
    case 'analysis.proposed':
      return { ...state, suggestions: [...state.suggestions, toPendingSuggestion(evt)] }
    case 'analysis.ready':
      return updateSuggestion(state, evt.request_id, { status: 'ready', text: evt.text })
    case 'analysis.dismissed':
      return removeSuggestion(state, evt.request_id)
    case 'profile.updated':
      return { ...state, profile: mergeProfile(state.profile, evt.entries) }
    case 'confirm_ack':
      return evt.ok ? state : removeSuggestion(state, evt.request_id)
    case 'error':
      // 已有 wsError state 路径处理
      return state
    case 'pong':
      return state
    default: {
      const _exhaustive: never = evt
      return state
    }
  }
}
```

**注意**：现在的 `LiveSession.tsx` 用 `SessionContext` 而非局部 reducer。改造保留 `SessionContext`，但 context 内部由 reducer 驱动，对外暴露的 `addTranscript/addInsight/...` 都改成 dispatch action。具体形状由 implementation plan 决定。

## 数据流图

```
                    ┌──────────────┐
   audio bytes ───▶ │  consume_stt │ ──TranscriptDelta──▶┐
                    └──────────────┘                      │
                                                          │
                    ┌──────────────┐                      │
   text msgs ────▶  │ _handle_text │ ──Pong/ConfirmAck──▶ │
                    └──────┬───────┘                      │
                           │                              │
                           ▼                              │   ┌────────────┐
                    ┌──────────────┐                      ├──▶│ send_event │──▶ WS
                    │ Orchestrator │                      │   └────────────┘
                    │              │                      │
                    │  handle_utt  │──ProfileUpdated──────┤
                    │  _run_child  │──InsightReady ───────┤
                    │              │──AnalysisProposed────┤
                    │  confirm     │──AnalysisReady ──────┤
                    │  dismiss/TTL │──AnalysisDismissed───┘
                    └──────┬───────┘
                           │
                           ▼
                    ┌──────────────┐
                    │SuggestionRepo│  （持久化，先于发事件）
                    └──────────────┘
```

## 兼容性 / 数据库

**无 schema 变化。** 复用现有 `suggestions` 表：
- `InsightReady` 落 `SuggestionRepository.insert_direct(...)` 现有路径
- `AnalysisProposed` 落 `SuggestionRepository.insert_pending(...)` （需新增，等价于 upsert，status=pending）
- `AnalysisReady` 落 `upsert_ready(...)` 现有路径

History 端点 `GET /api/sessions/{sid}/history` 现有返回的 `suggestions` 列表保持不变；前端 hydrate 时根据 `status` 字段映射到 `insights[]` 或 `suggestions[]` 即可。

## 测试策略

**后端单元**：
- `tests/test_orchestrator_events.py`：注入一个收集 `list[OutboundEvent]` 的 fake emitter，断言对应 utterance/confirm/dismiss 路径产出正确事件序列。
- `tests/test_events_schema.py`：每个事件类 round-trip（`model_dump` → JSON → `model_validate`）保证字段稳定。

**后端集成**：
- `tests/e2e_full_pipeline.py` 已有，按新事件 type 校验。

**前端单元**：
- `frontend/src/__tests__/sessionReducer.test.ts`：每种 `ServerEvent` 喂给 reducer，断言 state 变更。
- `useWebSocket.test.ts` 适配新签名（单 `onEvent` 而非多 callback）。

## 验证标准

1. 直接洞察可见：触发一条不调用 deep_analysis 的对话 → 前端 InsightStream 出现一张 InsightCard。
2. 深度分析仍可用：触发 deep_analysis → 出现 pending SuggestionCard → confirm → 卡片更新为 ready。
3. dismiss / TTL 过期：前端卡片消失（通过 AnalysisDismissed 事件）。
4. 画像实时更新：客户句子触发 ProfileAgent 后，画像面板字段实时变化。
5. 刷新页面后 history 恢复：insights/suggestions/profile 三类数据都恢复，无重复。
6. 后端单元测试覆盖率：Orchestrator 5 条事件路径各 1 个 test。
7. 前端 reducer exhaustive 检查：删除任一 `case` TS 编译报错。

## 改动范围估计

| 文件 | 操作 | 量级 |
|------|------|------|
| `backend/src/agent/events.py` | 新增 | ~80 行 |
| `backend/src/agent/orchestrator.py` | 改 callback → emitter；持久化迁入 | ~100 行 |
| `backend/src/repositories/suggestions.py` | 新增 `insert_pending` | ~15 行 |
| `backend/main.py` | 删 3 个 callback，加 1 个 send_event；transcript/pong/ack 用 typed | ~50 行 |
| `backend/tests/agent/test_orchestrator.py` 等现有测试 | 适配 set_event_emitter 新签名 | ~50 行 |
| `backend/tests/test_orchestrator_events.py` | 新增 | ~150 行 |
| `backend/tests/test_events_schema.py` | 新增 | ~60 行 |
| `frontend/src/types/events.ts` | 新增 | ~60 行 |
| `frontend/src/hooks/useWebSocket.ts` | 收敛 Callbacks → 单 onEvent | ~30 行 |
| `frontend/src/pages/LiveSession.tsx` + `SessionContext.tsx` | reducer 化 | ~100 行 |
| `frontend/src/__tests__/sessionReducer.test.ts` | 新增 | ~120 行 |

## 已知开放问题

- **HeavyAgent 是否真会输出非 gated 直接文本？** Spec 假设它会，且其 RunOutput 的 `content` 字段非空。需在 implementation 第一步实测一次，否则 InsightReady 永远不会触发，Bug A 仍未根治。如确认 HeavyAgent 必走 gated，则 InsightReady 事件保留接口但暂时不会产出，前端无影响。
- **AnalysisDismissed 是否需要在 history 端点返回？** 当前 history 已过滤掉 status=dismissed/expired，前端 hydrate 时这些卡片不会出现。无需特别处理。
