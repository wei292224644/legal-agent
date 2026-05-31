# 当事人画像数据打通 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 后端 `ProfileAgent` 提取的法律事实（ProfileEntry）通过 WebSocket 实时推送到前端 `ProfilePanel` 展示。

**Architecture:** 在 `Orchestrator` 增加 `profile_callback`，PA 提取完成后回调通知 WS handler。WS handler 构建 `profile_update` 消息推前端。前端 `useWebSocket` 新增 `onProfileUpdate` 回调，`LiveSession` 累积 entries 并转换 Profile 交给 Panel 渲染。HTTP history 接口同步补上 profile_entries 用于页面刷新恢复。

**Tech Stack:** Python (FastAPI + WebSocket), TypeScript (React + Vite)

---

### Task 1: Orchestrator 增加 profile_callback

**Files:**
- Modify: `backend/src/agent/orchestrator.py`

- [ ] **Step 1: 在 `__init__` 中初始化 `_profile_callback`**

在 `__init__` 方法中，`self._ttl_task = None` 之后添加：

```python
self._profile_callback = None
```

- [ ] **Step 2: 添加 `set_profile_callback` 方法**

在 `set_expiry_callback` 方法之后添加：

```python
def set_profile_callback(self, callback) -> None:
    self._profile_callback = callback
```

- [ ] **Step 3: 在 `handle_utterance` 中 PA 提取成功后调用回调**

在 `handle_utterance` 方法中，`await self._ctx.enqueue_profile_update(utt.id, entries)` 之后，`except Exception as e:` 之前添加：

```python
if self._profile_callback is not None:
    try:
        result = self._profile_callback(entries)
        if asyncio.iscoroutine(result):
            await result
    except Exception:
        logger.warning("profile callback failed", exc_info=True)
```

完整上下文改动：

```python
# 找到这段代码（约第 141-150 行）：
        if pa_task is not None:
            try:
                entries = await pa_task
                if entries:
                    for entry in entries:
                        entry.timestamp = utt.t_start
                    await self._ctx.enqueue_profile_update(utt.id, entries)
            except Exception as e:
                logger.warning("ProfileAgent.extract failed for utt %s: %s", utt.id, e)

# 改为：
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
            except Exception as e:
                logger.warning("ProfileAgent.extract failed for utt %s: %s", utt.id, e)
```

- [ ] **Step 4: 提交**

```bash
git add backend/src/agent/orchestrator.py
git commit -m "feat(orchestrator): 增加 profile_callback 回调机制

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 2: WebSocket 推送 profile_update 消息

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: 在 WS handler 中实现 profile 推送回调**

在 `legal_session` 函数中，`orch.set_suggestion_callback(on_suggestion)` 之后（约第 306 行），添加 profile callback：

```python
async def on_profile_update(entries):
    await _safe_send_json(ws, {
        "type": "profile_update",
        "entries": [
            {
                "key": e.key,
                "value": e.value,
                "subject": e.subject,
            }
            for e in entries
        ],
    })

orch.set_profile_callback(on_profile_update)
```

- [ ] **Step 2: 提交**

```bash
git add backend/main.py
git commit -m "feat(ws): WebSocket 推送 profile_update 消息

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 3: HTTP history 接口增加 profile_entries

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: 在 `get_history` 中查询 profile_entries 并返回**

修改 `get_history` 函数（约第 85-114 行），在查询 suggestions 之后增加 profile 查询：

```python
@app.get("/api/sessions/{session_id}/history")
async def get_history(session_id: str):
    from repositories.profile_entries import ProfileEntryRepository
    from repositories.sessions import SessionRepository
    from repositories.suggestions import SuggestionRepository
    from repositories.utterances import UtteranceRepository

    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的 session_id 格式") from None

    async with _maker() as s:
        row = await SessionRepository(s).get(sid)
        if row is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        utts = await UtteranceRepository(s).list_by_session(sid)
        sugs = await SuggestionRepository(s).list_by_session(sid)
        profile_entries = await ProfileEntryRepository(s).list_by_session(sid)

    return {
        "session_id": str(sid),
        "status": row.status,
        "utterances": [
            {
                "id": u.id, "text": u.text, "t_start": u.t_start,
                "t_end": u.t_end, "speaker": u.speaker, "closed_by": u.closed_by,
            } for u in utts
        ],
        "suggestions": sugs,
        "profile_entries": [
            {
                "key": e.key,
                "value": e.value,
                "subject": e.subject,
            }
            for e in profile_entries
        ],
    }
```

- [ ] **Step 2: 提交**

```bash
git add backend/main.py
git commit -m "feat(http): history 接口增加 profile_entries 字段

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 4: 前端类型定义更新

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/api/sessions.ts`

- [ ] **Step 1: 在 types/index.ts 中添加 ProfileEntryItem 类型**

在 `Profile` 类型定义之前添加：

```typescript
export type ProfileEntryItem = {
  key: string;
  value: string;
  subject: string;
};
```

- [ ] **Step 2: 扩展 Profile 类型，添加 entries 字段和可选字段**

将 Profile 类型修改为：

```typescript
export type Profile = {
  entries: ProfileEntryItem[];
  role: string;
  caseType: string;
  sessionRound: string;
  emotion: {
    label: string;
    score: number;
    description: string;
  } | null;
  claims: Array<{
    text: string;
    variant: 'default' | 'danger';
  }>;
  risks: Array<{
    level: 'high' | 'medium' | 'low';
    description: string;
  }>;
  facts: Array<{
    text: string;
    confirmed: boolean;
  }>;
};
```

改动要点：`emotion` 改为 `| null`，新增 `entries: ProfileEntryItem[]`。

- [ ] **Step 3: 在 sessions.ts 中增加 ProfileEntry API 类型和字段**

在 `SessionHistory` 类型中添加 `profile_entries` 字段：

```typescript
export type HistoryProfileEntry = {
  key: string;
  value: string;
  subject: string;
};

export type SessionHistory = {
  session_id: string;
  status: string;
  utterances: HistoryUtterance[];
  suggestions: HistorySuggestion[];
  profile_entries: HistoryProfileEntry[];
};
```

- [ ] **Step 4: 添加 entriesToProfile 转换函数**

在 `types/index.ts` 末尾添加：

```typescript
export function entriesToProfile(entries: ProfileEntryItem[]): Profile {
  return {
    entries,
    role: '',
    caseType: '',
    sessionRound: '',
    emotion: null,
    claims: entries
      .filter((e) => e.subject === '当事人')
      .map((e) => ({ text: `${e.key}: ${e.value}`, variant: 'default' as const })),
    risks: [],
    facts: entries.map((e) => ({ text: `${e.key}: ${e.value}`, confirmed: true })),
  };
}
```

- [ ] **Step 5: 提交**

```bash
git add frontend/src/types/index.ts frontend/src/api/sessions.ts
git commit -m "feat(frontend): 添加 ProfileEntryItem 类型和 entriesToProfile 转换函数

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 5: useWebSocket 增加 onProfileUpdate 回调

**Files:**
- Modify: `frontend/src/hooks/useWebSocket.ts`

- [ ] **Step 1: 添加 ProfileEntry 类型和回调定义**

在文件顶部的 `Callbacks` 类型中添加 `onProfileUpdate`，并添加 `ProfileEntryData` 类型：

```typescript
type ProfileEntryData = {
  key: string
  value: string
  subject: string
}

type Callbacks = {
  onTranscript?: (data: TranscriptData) => void
  onAnalysis?: (data: AnalysisData) => void
  onSuggestion?: (data: SuggestionData) => void
  onConfirmAck?: (data: { request_id: string; ok: boolean }) => void
  onProfileUpdate?: (entries: ProfileEntryData[]) => void
}
```

- [ ] **Step 2: 在 onmessage 中处理 profile_update 消息**

在 `ws.onmessage` 回调中，`if (msg.type === 'pong') return` 之后添加：

```typescript
if (msg.type === 'profile_update') {
  const entries = (msg.entries as ProfileEntryData[]) ?? []
  callbacksRef.current.onProfileUpdate?.(entries)
  return
}
```

- [ ] **Step 3: 提交**

```bash
git add frontend/src/hooks/useWebSocket.ts
git commit -m "feat(frontend): useWebSocket 增加 onProfileUpdate 回调

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 6: LiveSession 处理 profile 数据

**Files:**
- Modify: `frontend/src/pages/LiveSession.tsx`

- [ ] **Step 1: 导入 entriesToProfile**

在文件顶部 import 中添加：

```typescript
import { entriesToProfile, type ProfileEntryItem } from '@/types'
```

- [ ] **Step 2: 从 SessionContext 中取出 setProfile**

在 `useSession()` 解构中添加 `setProfile`（当前未使用）：

检查约第 38-49 行的解构，确保 `setProfile` 被取出：

```typescript
const {
    state,
    addInsight,
    addSuggestion,
    updateSuggestion,
    dismissSuggestion,
    addTranscript,
    setConnectionStatus,
    setSessionId,
    setProfile,    // 确保这一行存在
    hydrate,
    toggleTranscriptPanel,
  } = useSession()
```

（当前代码中 `setProfile` 可能未被解构，需要检查并添加。）

- [ ] **Step 3: 添加 onProfileUpdate 回调**

在 WebSocket callbacks 对象中（约第 206-215 行），`onConfirmAck` 之后添加：

```typescript
onProfileUpdate: (entries: ProfileEntryItem[]) => {
  const merged = [...state.profile?.entries ?? [], ...entries]
  setProfile(entriesToProfile(merged))
},
```

- [ ] **Step 4: hydrate 时恢复 profile_entries**

在 `hydrate` 调用处（约第 94 行），添加 `profile_entries` 处理：

```typescript
const profileEntries: ProfileEntryItem[] = (h.profile_entries ?? []).map(
  (e: { key: string; value: string; subject: string }) => ({
    key: e.key,
    value: e.value,
    subject: e.subject,
  })
)

hydrate({
  transcripts,
  suggestions,
  profile: profileEntries.length > 0 ? entriesToProfile(profileEntries) : null,
})
```

注意：`hydrate` 的 `Partial<SessionState>` 包含 `profile`，所以直接传入 profile 对象即可。

- [ ] **Step 5: backfillHistory 中也恢复 profile**

在 `backfillHistory` 回调中（约第 108 行），同样处理 `profile_entries`：

在 `fetchHistory(sid)` 返回后，添加 profile 恢复逻辑。在 `existingSuggestionIds` 逻辑之后，`newSuggestions.forEach` 之前添加：

```typescript
const profileEntries: ProfileEntryItem[] = (h.profile_entries ?? []).map(
  (e: { key: string; value: string; subject: string }) => ({
    key: e.key,
    value: e.value,
    subject: e.subject,
  })
)
if (profileEntries.length > 0) {
  setProfile(entriesToProfile(profileEntries))
}
```

- [ ] **Step 6: 提交**

```bash
git add frontend/src/pages/LiveSession.tsx
git commit -m "feat(frontend): LiveSession 接入 profile 实时推送和历史恢复

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 7: ProfilePanel 适配真实数据

**Files:**
- Modify: `frontend/src/components/profile/ProfilePanel.tsx`

- [ ] **Step 1: 添加 PendingModule 组件**

在 `EmptyModule` 函数之后添加：

```tsx
function PendingModule({ label, icon: Icon }: { label: string; icon: React.ElementType }) {
  return (
    <div className="py-3 px-1">
      <div className="flex items-center gap-2 mb-2">
        <Icon className="w-3 h-3 text-ink-muted" />
        <span className="text-[11px] font-mono tracking-wide text-ink-muted uppercase">{label}</span>
      </div>
      <p className="text-xs text-ink-muted">分析进行中…</p>
    </div>
  );
}
```

- [ ] **Step 2: 修改 ProfilePanel 主渲染逻辑**

当 `profile !== null` 时，将 `BaseInfo`、`EmotionState`、`RiskExposure` 替换为 `PendingModule`：

找到约第 203-216 行的渲染部分，将：

```tsx
<div className="flex-1 overflow-auto px-5 py-4 space-y-5">
  <BaseInfo profile={profile} />
  <EmotionState profile={profile} />
  <KeyClaims profile={profile} />
  <RiskExposure profile={profile} />
  <ConfirmedFacts profile={profile} />
</div>
```

改为：

```tsx
<div className="flex-1 overflow-auto px-5 py-4 space-y-5">
  <PendingModule label="基本信息" icon={User} />
  <PendingModule label="情绪状态" icon={Heart} />
  <KeyClaims profile={profile} />
  <PendingModule label="风险暴露" icon={ShieldAlert} />
  <ConfirmedFacts profile={profile} />
</div>
```

- [ ] **Step 3: 提交**

```bash
git add frontend/src/components/profile/ProfilePanel.tsx
git commit -m "feat(frontend): ProfilePanel 适配真实数据，空模块显示分析进行中

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

### Task 8: 端到端验证

- [ ] **Step 1: 启动后端**

```bash
cd backend && uv run uvicorn main:app --reload
```

- [ ] **Step 2: 启动前端**

```bash
cd frontend && pnpm dev
```

- [ ] **Step 3: 验证 WebSocket 实时推送**

1. 浏览器打开前端，创建新会话
2. 说话（当事人角色），观察 WebSocket 消息中是否出现 `type: "profile_update"`
3. 打开浏览器 DevTools Network WS 面板，确认收到 `profile_update` 消息
4. 确认 ProfilePanel 的"已确认事实"和"关键主张"模块实时显示新条目

- [ ] **Step 4: 验证 HTTP 刷新恢复**

1. 刷新页面
2. 确认 ProfilePanel 恢复了之前的画像数据
3. 检查 `/api/sessions/{id}/history` 返回中包含 `profile_entries`

- [ ] **Step 5: 验证律师发言不触发推送**

1. 律师角色说话
2. 确认 WebSocket 中没有新的 `profile_update` 消息

- [ ] **Step 6: 运行后端测试确保无回归**

```bash
cd backend && uv run pytest -v
```
