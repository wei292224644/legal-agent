# 实时洞察排序与类型区分 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 后端实时事件带上 `created_at` 时间戳，前端历史加载按 `source` 分拣 direct/gated，InsightStream 合并排序统一列表。

**Architecture:** 最小改动方案。后端只改事件模型和生成点；前端同步类型、Reducer 透传时间戳、历史加载时分拣、InsightStream 内部合并排序。

**Tech Stack:** Python (FastAPI/Pydantic/SQLAlchemy) + TypeScript (React/Vite)

---

## 文件结构

| 文件 | 动作 | 职责 |
|------|------|------|
| `backend/src/agent/events.py` | 修改 | `InsightReady` / `AnalysisProposed` 添加 `created_at: str` |
| `backend/src/agent/orchestrator.py` | 修改 | 生成事件时填入 `datetime.now(UTC).isoformat()` |
| `frontend/src/types/events.ts` | 修改 | 镜像后端事件类型，添加 `created_at` |
| `frontend/src/context/sessionReducer.ts` | 修改 | `RECV_EVENT` 处理 `insight.ready` / `analysis.proposed` 时写入 `evt.created_at` |
| `frontend/src/types/index.ts` | 修改 | `Suggestion` 类型添加可选 `source?: 'direct' \| 'gated'` |
| `frontend/src/pages/LiveSession.tsx` | 修改 | 历史回填时按 `source` 分拣到 `addInsight()` / `addSuggestion()` |
| `frontend/src/components/insights/InsightStream.tsx` | 修改 | 内部合并 `insights` + `suggestions`，按 `createdAt` 降序排序 |
| `frontend/src/__tests__/sessionReducer.test.ts` | 修改 | 更新测试用例，验证 `createdAt` 被正确写入 |

---

### Task 1: 后端事件模型添加 created_at

**Files:**
- Modify: `backend/src/agent/events.py:21-34`

- [ ] **Step 1: 修改 InsightReady**

在 `text: str` 下方添加 `created_at: str`：

```python
class InsightReady(BaseModel):
    type: Literal["insight.ready"] = "insight.ready"
    id: str
    utt_id: str
    text: str
    created_at: str
```

- [ ] **Step 2: 修改 AnalysisProposed**

在 `rationale: str` 下方添加 `created_at: str`：

```python
class AnalysisProposed(BaseModel):
    type: Literal["analysis.proposed"] = "analysis.proposed"
    request_id: str
    utt_id: str
    topic: str
    rationale: str
    created_at: str
```

- [ ] **Step 3: Commit**

```bash
git add backend/src/agent/events.py
git commit -m "feat(events): InsightReady / AnalysisProposed 添加 created_at

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: Orchestrator 生成事件时填入时间戳

**Files:**
- Modify: `backend/src/agent/orchestrator.py:269-271, 301-303`

- [ ] **Step 1: 确认已有 datetime 导入**

检查 `orchestrator.py` 文件顶部是否已有 `from datetime import datetime, UTC` 或类似导入。如果没有，在现有 import 块中添加：

```python
from datetime import UTC, datetime
```

- [ ] **Step 2: 修改 InsightReady 生成点**

找到 `_run_child` 方法中未 paused 分支的 `InsightReady` 构造（约第 269 行），改为：

```python
await self._emit_event(InsightReady(
    id=insight_id, utt_id=utt.id, text=text,
    created_at=datetime.now(UTC).isoformat(),
))
```

- [ ] **Step 3: 修改 AnalysisProposed 生成点**

找到同一方法中 paused 分支的 `AnalysisProposed` 构造（约第 301 行），改为：

```python
await self._emit_event(AnalysisProposed(
    request_id=request_id, utt_id=utt.id, topic=topic, rationale=rationale,
    created_at=datetime.now(UTC).isoformat(),
))
```

- [ ] **Step 4: Commit**

```bash
git add backend/src/agent/orchestrator.py
git commit -m "feat(orchestrator): 生成 InsightReady / AnalysisProposed 时填充 created_at

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: 后端回归测试

**Files:**
- Test: `backend/tests/`

- [ ] **Step 1: 运行现有测试**

```bash
cd backend && uv run pytest -x
```

Expected: 全部通过（事件模型改动是加字段，不影响现有逻辑）。

- [ ] **Step 2: 如失败则修复**

如果有序列化/反序列化测试硬编码了旧字段列表，更新期望字段包含 `created_at`。

---

### Task 4: 前端事件类型同步

**Files:**
- Modify: `frontend/src/types/events.ts:15-28`

- [ ] **Step 1: 修改 InsightReady**

```typescript
export type InsightReady = {
  type: 'insight.ready'
  id: string
  utt_id: string
  text: string
  created_at: string
}
```

- [ ] **Step 2: 修改 AnalysisProposed**

```typescript
export type AnalysisProposed = {
  type: 'analysis.proposed'
  request_id: string
  utt_id: string
  topic: string
  rationale: string
  created_at: string
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/types/events.ts
git commit -m "feat(types): InsightReady / AnalysisProposed 同步后端 created_at

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 5: Reducer 使用后端时间戳

**Files:**
- Modify: `frontend/src/context/sessionReducer.ts:19-40`

- [ ] **Step 1: 修改 insight.ready 处理**

```typescript
case 'insight.ready': {
  const insight: Insight = {
    id: evt.id,
    uttId: evt.utt_id,
    text: evt.text,
    createdAt: evt.created_at,
  }
  return { ...state, insights: [insight, ...state.insights] }
}
```

- [ ] **Step 2: 修改 analysis.proposed 处理**

```typescript
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
    createdAt: evt.created_at,
  }
  return { ...state, suggestions: [sug, ...state.suggestions] }
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/context/sessionReducer.ts
git commit -m "feat(reducer): RECV_EVENT 使用后端传入的 created_at

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 6: Suggestion 类型添加 source

**Files:**
- Modify: `frontend/src/types/index.ts:10-19`

- [ ] **Step 1: 修改 Suggestion 类型**

在 `createdAt: string` 上方添加：

```typescript
export type Suggestion = {
  id: string;
  requestId: string;
  status: SuggestionStatus;
  topic: string;
  rationale: string;
  text: string | null;
  progress?: number;
  source?: 'direct' | 'gated';   // 新增：用于历史数据识别
  createdAt: string;
};
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/types/index.ts
git commit -m "feat(types): Suggestion 添加可选 source 字段

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 7: 历史加载按 source 分拣

**Files:**
- Modify: `frontend/src/pages/LiveSession.tsx:155-167`

- [ ] **Step 1: 重构历史 suggestions 回填逻辑**

将现有的 `newSuggestions.forEach((s) => addSuggestion(s))` 替换为按 `source` 分拣：

```typescript
const existingSuggestionIds = new Set(latest.suggestions.map((s) => s.id))
const newHistoryItems = h.suggestions
  .filter((s) => s.status !== 'expired' && s.status !== 'dismissed' && !existingSuggestionIds.has(s.id))

newHistoryItems.forEach((s) => {
  if (s.source === 'direct') {
    addInsight({
      id: s.id,
      uttId: s.utt_id,
      text: s.text ?? '',
      createdAt: s.created_at,
    })
  } else {
    addSuggestion({
      id: s.id,
      requestId: s.request_id ?? `req-${s.id}`,
      status: s.status as 'pending' | 'running' | 'ready',
      topic: s.preview_topic ?? '',
      rationale: s.preview_rationale ?? '',
      text: s.text ?? null,
      source: s.source as 'direct' | 'gated',
      createdAt: s.created_at,
    })
  }
})
```

注意：删除原有的 `newSuggestions` 变量和 `newSuggestions.forEach(...)` 行。

- [ ] **Step 2: Commit**

```bash
git add frontend/src/pages/LiveSession.tsx
git commit -m "feat(history): 历史加载按 source 分拣 direct/gated

direct → insights 数组，gated → suggestions 数组

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 8: InsightStream 合并排序统一列表

**Files:**
- Modify: `frontend/src/components/insights/InsightStream.tsx`

- [ ] **Step 1: 替换渲染逻辑**

将整个组件替换为以下实现：

```tsx
import { Activity } from 'lucide-react'
import { ScrollArea } from '@/components/ui/scroll-area'
import InsightCard from './InsightCard'
import SuggestionCard from './SuggestionCard'
import type { Insight, Suggestion } from '@/types'

export type InsightStreamProps = {
  insights: Insight[]
  suggestions: Suggestion[]
  onConfirm: (requestId: string) => void
  onDismiss: (requestId: string) => void
}

type StreamItem =
  | { kind: 'insight'; data: Insight }
  | { kind: 'suggestion'; data: Suggestion }

function getTimestamp(item: StreamItem): number {
  const t = new Date(item.data.createdAt).getTime()
  return isNaN(t) ? 0 : t
}

function mergeItems(insights: Insight[], suggestions: Suggestion[]): StreamItem[] {
  const items: StreamItem[] = [
    ...insights.map((i) => ({ kind: 'insight' as const, data: i })),
    ...suggestions.map((s) => ({ kind: 'suggestion' as const, data: s })),
  ]
  return items.sort((a, b) => getTimestamp(b) - getTimestamp(a))
}

export default function InsightStream({
  insights,
  suggestions,
  onConfirm,
  onDismiss,
}: InsightStreamProps) {
  const items = mergeItems(insights, suggestions)
  const hasContent = items.length > 0

  return (
    <div className="flex-1 flex flex-col min-w-0">
      <div className="px-6 h-10 shrink-0 flex items-center justify-between border-b border-border-color">
        <span className="text-xs font-semibold text-ink-primary">实时洞察</span>
        <span className="text-xs font-mono text-ink-muted">
          {items.length} 条
        </span>
      </div>
      <ScrollArea className="flex-1 px-6 py-5">
        {!hasContent ? (
          <div className="flex flex-col items-center justify-center h-full text-ink-muted gap-2 min-h-[200px]">
            <Activity className="w-8 h-8 opacity-20" />
            <p className="text-sm">准备就绪，等待对话开始</p>
            <p className="text-xs text-ink-muted">点击上方「开始录音」或「上传音频」开始会谈，AI 分析结果将实时显示在此处</p>
          </div>
        ) : (
          <div>
            {items.map((item) =>
              item.kind === 'suggestion' ? (
                <SuggestionCard
                  key={item.data.requestId}
                  suggestion={item.data}
                  onConfirm={onConfirm}
                  onDismiss={onDismiss}
                />
              ) : (
                <InsightCard key={item.data.id} insight={item.data} />
              )
            )}
          </div>
        )}
      </ScrollArea>
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/insights/InsightStream.tsx
git commit -m "feat(insights): InsightStream 合并 insights + suggestions 按时间排序

统一列表渲染，最新在最上面

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 9: 更新前端 reducer 测试

**Files:**
- Modify: `frontend/src/__tests__/sessionReducer.test.ts:19-35`

- [ ] **Step 1: 更新 insight.ready 测试**

原测试：

```typescript
it('insight.ready → 加到 insights 头部', () => {
  const s = recv({ type: 'insight.ready', id: 'ins_1', utt_id: 'u1', text: '洞察' })
  expect(s.insights).toHaveLength(1)
  expect(s.insights[0]).toMatchObject({ id: 'ins_1', uttId: 'u1', text: '洞察' })
})
```

改为：

```typescript
it('insight.ready → 加到 insights 头部并携带 createdAt', () => {
  const s = recv({ type: 'insight.ready', id: 'ins_1', utt_id: 'u1', text: '洞察', created_at: '2026-05-31T10:00:00Z' })
  expect(s.insights).toHaveLength(1)
  expect(s.insights[0]).toMatchObject({ id: 'ins_1', uttId: 'u1', text: '洞察', createdAt: '2026-05-31T10:00:00Z' })
})
```

- [ ] **Step 2: 更新 analysis.proposed 测试**

原测试事件构造：

```typescript
const evt: ServerEvent = {
  type: 'analysis.proposed', request_id: 'req_1', utt_id: 'u1',
  topic: 'T', rationale: 'R',
}
```

改为：

```typescript
const evt: ServerEvent = {
  type: 'analysis.proposed', request_id: 'req_1', utt_id: 'u1',
  topic: 'T', rationale: 'R', created_at: '2026-05-31T10:00:00Z',
}
```

并在断言中验证 `createdAt`：

```typescript
expect(s1.suggestions[0]).toMatchObject({ status: 'pending', topic: 'T', createdAt: '2026-05-31T10:00:00Z' })
```

- [ ] **Step 3: 运行测试**

```bash
cd frontend && pnpm test
```

Expected: 全部通过。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/__tests__/sessionReducer.test.ts
git commit -m "test(reducer): 更新 insight.ready / analysis.proposed 用例验证 createdAt

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage：**
- ✅ 后端事件模型加 `created_at` → Task 1
- ✅ Orchestrator 填入时间戳 → Task 2
- ✅ 前端事件类型同步 → Task 4
- ✅ Reducer 使用时间戳 → Task 5
- ✅ Suggestion 添加 `source` → Task 6
- ✅ 历史加载按 source 分拣 → Task 7
- ✅ InsightStream 合并排序 → Task 8
- ✅ 测试覆盖 → Task 3, Task 9

**2. Placeholder scan：**
- ✅ 无 TBD / TODO
- ✅ 所有步骤包含具体代码和命令

**3. Type consistency：**
- ✅ `created_at`（后端 snake_case）对应 `createdAt`（前端 camelCase）
- ✅ `source` 类型前后端一致：`'direct' | 'gated'`
