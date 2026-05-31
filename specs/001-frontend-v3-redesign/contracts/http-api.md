# HTTP API Contracts

**Date**: 2026-05-30
**Feature**: 前端 V3 重构

本文档定义前端与后端 HTTP API 的接口契约。

## 已有接口（复用，无需后端修改）

### GET /api/sessions/{sessionId}/history

获取指定会话的历史数据，用于页面刷新或重连后回填。

**Request**:
```
GET /api/sessions/{sessionId}/history
```

**Response 200**:
```typescript
{
  session_id: string;
  status: string;
  utterances: Array<{
    id: string;
    text: string;
    t_start: number;
    t_end: number;
    speaker: "lawyer" | "client" | "uncertain" | null;
    closed_by: string;
  }>;
  suggestions: Array<{
    id: string;
    utt_id: string;
    request_id: string | null;
    source: "direct" | "gated";
    status: "pending" | "running" | "ready" | "expired" | "dismissed";
    preview_topic: string | null;
    preview_rationale: string | null;
    text: string | null;
    error: string | null;
    confirmed_at: string | null;
    created_at: string;
  }>;
}
```

**Response 404**: 会话不存在，返回 `null`。

## 前端内部组件契约

### ProfilePanel Props

```typescript
type ProfilePanelProps = {
  profile: Profile | null;    // null 时展示占位状态
};
```

### InsightStream Props

```typescript
type InsightStreamProps = {
  insights: Insight[];
  suggestions: Suggestion[];
  onConfirm: (requestId: string) => void;
  onDismiss: (requestId: string) => void;
};
```

### TranscriptPanel Props

```typescript
type TranscriptPanelProps = {
  transcripts: TranscriptLine[];
  isOpen: boolean;
  onToggle: () => void;
};
```
