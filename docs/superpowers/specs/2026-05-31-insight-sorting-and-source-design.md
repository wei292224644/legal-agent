# 实时洞察排序与类型区分 — 设计文档

## 问题

1. **时间戳缺失**：后端实时事件 `insight.ready` / `analysis.proposed` 没有 `created_at` 字段，前端 `Insight`/`Suggestion` 的 `createdAt` 为空，导致 `InsightStream` 无法按时间排序。
2. **类型区分缺失**：历史数据加载时，后端 `suggestions` 表中同时存放 `direct`（快速洞察）和 `gated`（深度分析）记录，但前端 `LiveSession.tsx` 未按 `source` 字段分拣，导致历史中的 `direct` 洞察被错误渲染为 `SuggestionCard`（深度分析卡片）。

## 方案

采用**方案 A**：后端事件加 `created_at` + 前端历史加载按 `source` 分拣到对应数组 + `InsightStream` 合并排序统一列表。

### 后端

#### 1. 事件模型（`backend/src/agent/events.py`）

给 `InsightReady` 和 `AnalysisProposed` 各加一个 `created_at: str` 字段：

```python
class InsightReady(BaseModel):
    type: Literal["insight.ready"] = "insight.ready"
    id: str
    utt_id: str
    text: str
    created_at: str          # 新增

class AnalysisProposed(BaseModel):
    type: Literal["analysis.proposed"] = "analysis.proposed"
    request_id: str
    utt_id: str
    topic: str
    rationale: str
    created_at: str          # 新增
```

`AnalysisReady` 不改——它只是状态更新，不产生新时间戳。

#### 2. Orchestrator（`backend/src/agent/orchestrator.py`）

在生成事件时填入当前 UTC 时间：

- `InsightReady(..., created_at=datetime.now(UTC).isoformat())`
- `AnalysisProposed(..., created_at=datetime.now(UTC).isoformat())`

`PendingRequest` 内部已有的 `created_at: float`（用于 TTL 计算）保持不变，emit 时单独生成 ISO 字符串即可。

#### 3. 数据库

`repositories/suggestions.py` 的 `list_by_session` 已经返回 `created_at`，`suggestions` 表已有 `source` 字段。**无需数据库迁移。**

### 前端

#### 1. 事件类型同步（`frontend/src/types/events.ts`）

镜像后端改动：

```typescript
export type InsightReady = {
  type: 'insight.ready'
  id: string
  utt_id: string
  text: string
  created_at: string        // 新增
}

export type AnalysisProposed = {
  type: 'analysis.proposed'
  request_id: string
  utt_id: string
  topic: string
  rationale: string
  created_at: string        // 新增
}
```

#### 2. Reducer 使用后端时间戳（`frontend/src/context/sessionReducer.ts`）

`insight.ready` 和 `analysis.proposed` 处理时，把 `evt.created_at` 写入 `createdAt`：

```typescript
case 'insight.ready': {
  const insight: Insight = {
    id: evt.id,
    uttId: evt.utt_id,
    text: evt.text,
    createdAt: evt.created_at,   // 从后端来
  }
  return { ...state, insights: [insight, ...state.insights] }
}
```

`ADD_INSIGHT` / `ADD_SUGGESTION`（历史回填路径）保持透传——历史接口已经带了 `created_at`。

#### 3. 历史加载按 source 分拣（`frontend/src/pages/LiveSession.tsx`）

`HistorySuggestion` API 类型已有 `source: "direct" | "gated"`。在历史回填 `map` 中：

- `source === 'direct'` → 组装成 `Insight` 类型，调用 `addInsight()`
- `source === 'gated'` → 组装成 `Suggestion` 类型（带上 `source: 'gated'`），调用 `addSuggestion()`

这样历史数据就和实时流收敛到同一个数组结构里。

#### 4. `InsightStream` 合并排序统一列表（`frontend/src/components/insights/InsightStream.tsx`）

`InsightStream` 接收的 props 不变（还是 `insights[]` + `suggestions[]`），内部做合并：

```typescript
type StreamItem =
  | { kind: 'insight'; data: Insight }
  | { kind: 'suggestion'; data: Suggestion }

const items = [
  ...insights.map(i => ({ kind: 'insight' as const, data: i })),
  ...suggestions.map(s => ({ kind: 'suggestion' as const, data: s })),
].sort((a, b) =>
  new Date(b.data.createdAt).getTime() - new Date(a.data.createdAt).getTime()
)
```

渲染时按 `kind` 分发到 `InsightCard` / `SuggestionCard`。

## 边界情况

- **空 `createdAt`**：历史数据中极少数旧记录可能缺少 `created_at`（实际上数据库有默认值，不会缺）。排序 comparator 对 `Invalid Date` 回退到 `0`，确保不会抛异常。
- **同时到达**：如果 `insight.ready` 和 `analysis.proposed` 同时生成，它们的 `created_at` 会有微妙差异（微秒级），排序稳定。
- **时区**：后端使用 `datetime.now(UTC).isoformat()`，前端 `new Date()` 自动识别 ISO 字符串中的时区信息，跨时区安全。

## 测试

- 后端：运行现有测试确保事件序列化/反序列化正常
- 前端：
  - `sessionReducer.test.ts` 更新 `insight.ready` / `analysis.proposed` 测试用例，验证 `createdAt` 被正确写入
  - 新增 `InsightStream` 排序测试：传入混合顺序的 insights + suggestions，验证渲染顺序按 `createdAt` 降序
