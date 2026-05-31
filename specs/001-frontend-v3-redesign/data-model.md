# Data Model: 前端 V3 重构

**Date**: 2026-05-30
**Feature**: 前端 V3 重构

本文档定义前端视角的数据实体、字段和状态流转。

## 实体定义

### Profile（当事人画像）

```typescript
type Profile = {
  // 基本信息
  role: string;           // 角色，如 "当事人（被告）"
  caseType: string;       // 案件类型，如 "合同纠纷"
  sessionRound: string;   // 会谈轮次，如 "第 2 次"

  // 情绪状态
  emotion: {
    label: string;        // 如 "冷静"
    score: number;        // 0-100，用于进度条
    description: string;  // 如 "较首次会谈明显更理性..."
  };

  // 关键主张
  claims: Array<{
    text: string;
    variant: 'default' | 'danger';  // 用于圆点颜色区分
  }>;

  // 风险暴露
  risks: Array<{
    level: 'high' | 'medium' | 'low';
    description: string;
  }>;

  // 已确认事实
  facts: Array<{
    text: string;
    confirmed: boolean;   // 默认 true，用于勾选图标
  }>;
};
```

### Insight（洞察卡片）

```typescript
type InsightCategory =
  | 'law_citation'    // 法规引用
  | 'risk_warning'    // 风险提示
  | 'contract_clause' // 合同条款
  | 'behavior_analysis'; // 行为分析

type Insight = {
  id: string;
  category: InsightCategory;
  title: string;
  content: string;
  citation?: string;      // 关联法律条文，如 "《民法典》第五百七十七条"
  riskLevel?: 'high' | 'medium' | 'low';  // 仅风险提示类型使用
  createdAt: string;      // ISO 时间戳
};
```

### Suggestion（可分析意图）

```typescript
type SuggestionStatus = 'pending' | 'running' | 'ready' | 'expired' | 'dismissed';

type Suggestion = {
  id: string;
  requestId: string;
  status: SuggestionStatus;
  topic: string;          // 预览主题
  rationale: string;      // 预览理由
  text: string | null;    // 深度分析完成后的文本内容
  progress?: number;      // 0-100，运行中的进度（可选，如后端未提供则用模拟进度）
  createdAt: string;
};
```

### Transcript（转写文本）

```typescript
type SpeakerRole = 'lawyer' | 'client' | 'uncertain';

type TranscriptLine = {
  id: string;
  speaker: SpeakerRole;
  text: string;
  timestamp: number;      // 相对于会谈开始的时间（秒）
};
```

### Session（会谈会话状态）

```typescript
type ConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'reconnecting';
type RecordingStatus = 'idle' | 'recording' | 'paused';

type Session = {
  sessionId: string;
  connectionStatus: ConnectionStatus;
  recordingStatus: RecordingStatus;
  profile: Profile | null;
  insights: Insight[];
  suggestions: Suggestion[];
  transcripts: TranscriptLine[];
  // UI 本地状态
  isTranscriptPanelOpen: boolean;  // 桌面端转写面板折叠状态
  activeMobileTab: 'insights' | 'profile' | 'transcript';  // 移动端当前 Tab
};
```

## 状态流转

### Suggestion 生命周期

```
┌─────────┐   系统识别    ┌─────────┐   用户点击      ┌─────────┐
│  (无)   │ ────────────→ │ pending │ ──────────────→ │ running │
└─────────┘               └─────────┘  "生成深度分析"  └─────────┘
                              │                              │
                              │ 用户点击 "忽略"               │ 分析完成
                              ▼                              ▼
                         ┌─────────┐                    ┌─────────┐
                         │dismissed│                    │  ready  │
                         └─────────┘                    └─────────┘
```

### ConnectionStatus 生命周期

```
┌───────────┐   连接成功    ┌───────────┐   网络断开      ┌─────────────┐
│connecting │ ────────────→ │connected  │ ──────────────→ │disconnected │
└───────────┘               └───────────┘                 └─────────────┘
                                 ▲                              │
                                 │      自动重连成功               │ 重连中
                                 └───────────────────────────────┘
                                        reconnecting
```

## 字段验证规则

- `Profile.emotion.score`: 0 ≤ score ≤ 100
- `Suggestion.progress`: 如存在，0 ≤ progress ≤ 100
- `TranscriptLine.timestamp`: ≥ 0
- `Insight.riskLevel`: 仅当 `category === 'risk_warning'` 时允许非空
- `Profile.claims`: 最少 0 条，最多 10 条（超出时截断并提示）
- `Profile.risks`: 最少 0 条，最多 5 条
