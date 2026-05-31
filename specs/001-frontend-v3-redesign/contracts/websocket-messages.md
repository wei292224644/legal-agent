# WebSocket Message Contracts

**Date**: 2026-05-30
**Feature**: 前端 V3 重构

本文档定义前端与后端 WebSocket 通道的消息格式契约。

## 服务端 → 客户端（下行消息）

### transcript（转写文本）

```typescript
{
  type: 'transcript';
  text: string;        // 转写内容
  speaker: string;     // 说话人标识，如 "lawyer" | "client" | "uncertain"
  is_final: boolean;   // 是否为最终结果（true=确定，false=中间结果）
}
```

### analysis（实时洞察）

```typescript
{
  type: 'analysis';
  category: string;    // 洞察类型，如 "law_citation" | "risk_warning" | "contract_clause" | "behavior_analysis"
  title: string;       // 洞察标题
  content: string;     // 洞察详细内容
  citation?: string;   // 可选：关联法律条文
}
```

### suggestion.pending（可分析意图 - 待确认）

```typescript
{
  type: 'suggestion.pending';
  text: null;
  meta: {
    utt_id: string;           // 关联的 utterance ID
    request_id: string;       // 分析请求 ID
    preview: {
      topic: string;          // 预览主题
      rationale: string;      // 预览理由
    };
  };
}
```

### suggestion.ready（可分析意图 - 已完成）

```typescript
{
  type: 'suggestion.ready';
  text: string | null;        // 深度分析结果文本（可能为 null 如果分析失败）
  meta: {
    utt_id: string;
    request_id: string;
    preview?: {
      topic: string;
      rationale: string;
    };
  };
}
```

### confirm_ack（确认回执）

```typescript
{
  type: 'confirm_ack';
  request_id: string;   // 对应的分析请求 ID
  ok: boolean;          // 确认是否成功接受
}
```

### pong（心跳响应）

```typescript
{
  type: 'pong';
}
```

## 客户端 → 服务端（上行消息）

### ping（心跳）

```typescript
{
  type: 'ping';
}
```

### confirm（确认生成深度分析）

```typescript
{
  type: 'confirm';
  request_id: string;   // 要确认的分析请求 ID
}
```

### dismiss（忽略可分析意图）

```typescript
{
  type: 'dismiss';
  request_id: string;   // 要忽略的分析请求 ID
}
```

### audio_end（音频结束标记）

```typescript
{
  type: 'audio_end';
}
```

### audio chunk（音频数据）

- **Format**: 二进制 `ArrayBuffer`（非 JSON）
- **Content**: PCM 或 WebM 编码的音频数据块
- **Note**: 直接发送二进制，不包装 JSON
