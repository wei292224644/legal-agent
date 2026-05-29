# Session 架构方案

> 由 /plan-eng-review 生成，2026-05-29
> 目的：支持多用户/多 session，WebSocket 断开后可重连恢复

---

## 已确认的设计决策

| 编号 | 决策项 | 选择 |
|---|---|---|
| D1 | 范围 | 完整版本（100%） |
| D2 | 持久化策略 | 定期快照（每 N 句/每 M 分钟）+ 断开时快照 |
| D3 | 存储后端 | SQLite（零运维，单文件） |
| D4 | 连接模型 | 排他连接（同一 Session 同一时间只能有一个 WS） |
| D5 | 序列化范围 | 仅纯数据（排除 asyncio 运行时对象） |
| D6 | 快照失败处理 | 静默降级（打日志，不中断 session） |
| CQ1 | 持久化抽象 | 现在就做 `PersistenceBackend` ABC |

---

## 核心修正：Session ≠ WebSocket

原始想法"一个 WebSocket 当做一个 session"在**法律会谈场景下不可行**——律师刷新页面后所有上下文丢失。

修正后的模型：
- **Session** = 一场法律会谈（持久化实体，有 session_id）
- **WebSocket Connection** = 一个客户端连接（临时实体）
- 一个 Session 可以有多个 WebSocket Connection（不同时刻），也可以没有（离线时）

---

## 架构图

### 系统架构

```
┌─────────────────┐     WS connect     ┌─────────────────┐
│   Client (FE)   │ ─────────────────► │   FastAPI WS    │
│                 │                    │   /ws/{sid}     │
│ useWebSocket    │ ◄───────────────── │                 │
│ (reconnect)     │     WS messages    └────────┬────────┘
└─────────────────┘                              │
                                                 ▼
                                        ┌─────────────────┐
                                        │ SessionManager  │
                                        │ (app.state)     │
                                        │                 │
                                        │ active: dict    │
                                        │ _schedule_ttl() │
                                        │ _schedule_snap()│
                                        └────────┬────────┘
                                                 │
                              ┌──────────────────┼──────────────────┐
                              ▼                  ▼                  ▼
                       ┌────────────┐    ┌────────────┐    ┌────────────┐
                       │  Session   │    │  Session   │    │  Session   │
                       │ (active)   │    │ (detached) │    │ (persisted)│
                       │            │    │            │    │            │
                       │ ctx_store  │    │ ctx_store  │    │ in SQLite  │
                       │ orch       │    │ orch       │    │            │
                       │ ws: WebSock│    │ ws: None   │    │            │
                       │ last_active│    │ last_active│    │            │
                       └────────────┘    └────────────┘    └────────────┘
                              │                  │                  │
                              │ WS 断开          │ 10min TTL        │ load
                              ▼                  ▼                  ▼
                       触发快照 ──────────► 从内存移除 ────► 反序列化恢复
```

### WebSocket Handler 新流程

```
legal_session(ws, session_id):
  │
  ├─► SessionManager.get_or_restore(session_id)
  │     │
  │     ├─ 内存中存在且 active? ──► 拒绝/踢掉旧连接
  │     │                           (发送 displaced 消息)
  │     │
  │     ├─ 内存中存在但 detached? ──► attach 新 WS，恢复为 active
  │     │
  │     ├─ 内存中不存在，SQLite 中有? ──► deserialize，attach 新 WS
  │     │
  │     └─ 都不存在? ──► 创建全新 Session，attach 新 WS
  │
  ├─► 启动定期快照任务（每 5 句或每 30 秒）
  │
  ├─► 消息循环（同现有逻辑，但委托给 Session 对象）
  │     bytes ──► audio_q ──► STT ──► Bus ──► Orchestrator
  │     text  ──► confirm/dismiss/ping
  │
  ├─► WS 断开（WebSocketDisconnect）
  │     │
  │     ├─► Session.detach_ws()
  │     ├─► 触发快照（serialize → SQLite）
  │     └─► 启动 10min TTL timer
  │         10min 后从内存移除（SQLite 仍保留）
```

### Session 状态机

```
                    ┌─────────────┐
                    │   不存在    │
                    └──────┬──────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
    WS connect          WS connect        WS connect
    sid 在内存          sid 在 SQLite    sid 不存在
    active              但不在内存        且不在 SQLite
         │                 │                 │
         ▼                 ▼                 ▼
    ┌─────────┐      ┌─────────┐      ┌─────────┐
    │ 拒绝/踢掉│      │ 反序列化│      │ 创建新  │
    │ 旧连接   │      │ + attach│      │ Session │
    └────┬────┘      └────┬────┘      └────┬────┘
         │                 │                 │
         ▼                 ▼                 ▼
    ┌─────────────────────────────────────────────┐
    │                  active                     │
    │  (有 WebSocket 连接，可收发消息)              │
    └────────────────────┬────────────────────────┘
                         │
                    WS 断开
                         │
                         ▼
    ┌─────────────────────────────────────────────┐
    │                 detached                    │
    │  (无 WebSocket，但仍在内存中保留 10 分钟)     │
    │  (期间快照已写入 SQLite)                     │
    └────────────────────┬────────────────────────┘
                         │
                    10min TTL 到期
                         │
                         ▼
    ┌─────────────────────────────────────────────┐
    │               persisted                     │
    │  (仅存在于 SQLite，内存中无副本)             │
    └─────────────────────────────────────────────┘
```

---

## 数据模型

### Session

```python
@dataclass
class Session:
    session_id: str
    ctx: ContextStore          # 运行时对象（不可序列化）
    orch: Orchestrator         # 运行时对象（不可序列化）
    enrollment: Enrollment     # 运行时对象（不可序列化）
    ws: WebSocket | None       # 当前 WS 连接（不可序列化）
    state: Literal["active", "detached"]
    created_at: float
    last_active: float
    detached_at: float | None
    # 运行时对象（不可序列化）
    _audio_q: asyncio.Queue | None
    _stt_task: asyncio.Task | None
    _snapshot_task: asyncio.Task | None
```

### SessionState（纯数据，可序列化）

```python
@dataclass
class SessionState:
    session_id: str
    context_state: dict        # ContextStore.to_dict()
    orchestrator_state: dict   # Orchestrator.to_dict()
    enrollment_data: dict      # Enrollment.to_dict()
    created_at: float
    last_active: float
```

---

## 详细修改清单

### 新增文件

| 文件 | 行数估算 | 职责 |
|---|---|---|
| `backend/src/session/__init__.py` | 5 | 包入口 |
| `backend/src/session/models.py` | 40 | Session, SessionState, ConnectionInfo |
| `backend/src/session/manager.py` | 120 | SessionManager: registry, TTL, 快照调度 |
| `backend/src/session/persistence.py` | 80 | PersistenceBackend ABC, SQLiteBackend, InMemoryBackend |
| `backend/src/session/serializer.py` | 60 | ContextStore/Orchestrator/Enrollment 序列化 |

### 修改文件

| 文件 | 修改内容 |
|---|---|
| `backend/main.py` | 重构 `legal_session()`: 连接时查 registry，断开时 detach + 快照。增加 Session 生命周期管理（~+100 行） |
| `backend/src/agent/context_store.py` | 增加 `to_dict()` / `from_dict()`（~+30 行） |
| `backend/src/agent/orchestrator.py` | 增加 `to_dict()` / `from_dict()`，shutdown 触发快照（~+30 行） |
| `backend/src/diarization/enrollment.py` | 增加 `to_dict()` / `from_dict()`（~+20 行） |
| `backend/src/models/utterance.py` | 增加 `to_dict()` / `from_dict()`（~+20 行，如果还没有） |
| `backend/src/config.py` | 新增 SESSION_SNAPSHOT_INTERVAL, SESSION_TTL_SECONDS（~+5 行） |
| `frontend/src/hooks/useWebSocket.ts` | 重连时携带相同 session_id（~+10 行） |

---

## 关键实现点

### 1. ContextStore 序列化

只保存纯数据：
- `_utterances: list[Utterance]` → JSON
- `_profile: list[ProfileEntry]` → JSON
- `_generation: int` → JSON

不保存运行时对象：
- `_lock: asyncio.Lock` → 反序列化时重建
- `_worker_task: asyncio.Task` → 反序列化时重建
- `_profile_queue: asyncio.Queue` → 反序列化时重建
- `_shutdown: bool` → 反序列化时设为 False，重建 worker

### 2. Orchestrator 序列化

只保存纯数据：
- `_pending: dict[str, PendingRequest]` → JSON（PendingRequest 中的 Utterance 需序列化）

不保存运行时对象：
- `_suggestion_callback` → 反序列化后由 main.py 重新绑定
- `_bus` / `_bus_task` → 反序列化后重新 attach
- `_ir`, `_pa`, `_ha` → 反序列化后重新创建（或复用单例）

### 3. 排他连接实现

```python
# main.py: 连接时
existing = manager.get_active(session_id)
if existing and existing.ws is not None:
    # 踢掉旧连接
    await existing.ws.send_json({"type": "displaced"})
    await existing.ws.close()
    manager.detach(session_id)
```

### 4. 定期快照调度

```python
# SessionManager
async def _snapshot_loop(self, session_id: str):
    while session := self._active.get(session_id):
        await asyncio.sleep(self._snapshot_interval)
        if session.state == "active":
            await self._persist(session)
```

### 5. 静默降级

```python
async def _persist(self, session: Session):
    try:
        state = serialize(session)
        await self._backend.save(state)
    except Exception as e:
        print(f"[WARN] Snapshot failed for {session.session_id}: {e}")
        # 不 raise，不中断 session
```

---

## Code Quality 发现

| 编号 | 问题 | 推荐处理 |
|---|---|---|
| CQ1 | 持久化层可插拔 | ✅ 已确认：定义 PersistenceBackend ABC |
| CQ2 | SessionManager 单例 | 放在 `app.state.session_manager`，避免全局变量 |
| CQ3 | 序列化运行时对象 | 明确定义"可序列化"边界，运行时对象重建 |
| CQ4 | 类型安全 | SessionState dataclass 确保序列化结构稳定 |
| CQ5 | 错误边界 | 快照失败、反序列化失败、SQLite 写入失败均需优雅降级 |

---

## Test Review

### 覆盖率图

```
CODE PATHS
[+] backend/src/session/manager.py
  ├── get_or_restore() — [GAP] 全部 4 个分支
  ├── create_session() — [GAP]
  ├── attach_ws() — [GAP]
  ├── detach_ws() — [GAP]
  ├── _persist() — [GAP]
  ├── _cleanup_ttl() — [GAP]
  └── _snapshot_loop() — [GAP]

[+] backend/src/session/persistence.py
  ├── InMemoryBackend.save/load/delete — [GAP]
  └── SQLiteBackend.save/load/delete — [GAP]

[+] backend/src/session/serializer.py
  ├── serialize_context_store() — [GAP]
  ├── deserialize_context_store() — [GAP]
  ├── serialize_orchestrator() — [GAP]
  └── deserialize_orchestrator() — [GAP]

[+] backend/main.py (重构后)
  ├── 连接: session 不存在 → 创建 — [GAP]
  ├── 连接: session 在 SQLite → 恢复 — [GAP]
  ├── 连接: session active → 踢掉旧 — [GAP]
  ├── 断开: detach + 快照 — [GAP]
  └── 消息: confirm/dismiss 委托给 Session — [GAP]

[+] backend/src/agent/context_store.py
  ├── to_dict() — [GAP]
  └── from_dict() — [GAP]

[+] backend/src/agent/orchestrator.py
  ├── to_dict() — [GAP]
  └── from_dict() — [GAP]

COVERAGE: 0%（全部新增或修改路径无测试）
QUALITY: 0 ★★★, 0 ★★, 0 ★  |  GAPS: 20+
```

### 新增测试文件

| 测试文件 | 覆盖内容 |
|---|---|
| `backend/tests/session/test_manager.py` | SessionManager: 创建、恢复、重连、TTL、排他 |
| `backend/tests/session/test_persistence.py` | InMemoryBackend + SQLiteBackend 读写删 |
| `backend/tests/session/test_serializer.py` | ContextStore/Orchestrator 序列化往返 |
| `backend/tests/session/test_integration.py` | WebSocket 重连恢复全流程 |
| `backend/tests/test_main_reconnect.py` | main.py 重构后的 WebSocket 连接场景 |

---

## Performance Review

| 编号 | 问题 | 风险 | 缓解措施 |
|---|---|---|---|
| P1 | SQLite 全局写锁 | 并发高时快照阻塞 | 快照在后台 asyncio task 执行，不阻塞主路径 |
| P2 | 大 session 序列化 | utterances 积累多后 JSON 序列化慢 | 增量快照（只保存新增 utterances），定期全量快照 |
| P3 | 内存中保留断开 session | 并发会话多时内存紧张 | 设置 `MAX_DETACHED_SESSIONS`，LRU 淘汰到 SQLite |
| P4 | 反序列化重建开销 | 恢复大 session 时需重建大量对象 | 懒加载：只恢复活跃 session 的完整状态，其余按需恢复 |

---

## Failure Modes（生产故障分析）

| 场景 | 测试覆盖 | 错误处理 | 用户可见 |
|---|---|---|---|
| 快照时 SQLite 锁冲突 | [GAP] | 静默降级，打日志 | 无感知 |
| 反序列化失败（schema 变更） | [GAP] | 创建新 session，旧数据丢失 | 律师发现上下文清空 |
| 同一 session_id 双连接 | [GAP] | 踢掉旧连接 | 旧设备收到 "displaced" |
| TTL 期间服务器崩溃 | [GAP] | 数据在 SQLite 中，可恢复 | 无感知 |
| 内存溢出（大量 detached session）| [GAP] | LRU 淘汰 | 无感知 |

**Critical gap:** 反序列化失败时创建新 session — 律师的会谈上下文会丢失，但当前没有告警。建议反序列化失败时向前端发送 `type: "session_reset"` 并记录原因。

---

## NOT in scope

| 项目 | 原因 |
|---|---|
| 用户认证/授权 | 当前 focus 是 session 管理，用户系统可后续叠加 |
| Redis 实现 | SQLite 足够当前需求，PersistenceBackend ABC 预留了扩展点 |
| 多设备同时连接 | 已确认排他连接，多端协作是 P2 |
| 多方会谈（3+ 说话人） | 声纹系统当前只支持 lawyer/client 二分，需独立改造 |
| 前端状态持久化（localStorage） | 纯体验优化，不影响核心架构 |
| Session 审计日志/数据分析 | 后续可基于 SQLite 扩展 |
| 分布式部署/多进程共享 | 当前单机部署，SQLite 够用 |

---

## What already exists

| 现有代码 | 是否复用 |
|---|---|
| WebSocket `/ws/{session_id}` 端点 | ✅ 复用，重构 handler |
| `ContextStore`（内存存储） | ✅ 复用，增加序列化 |
| `Orchestrator`（调度器） | ✅ 复用，增加序列化 |
| `UtteranceBus`（事件总线） | ✅ 复用，但 Session 重建后需重新 attach |
| `Enrollment`（声纹） | ✅ 复用，增加序列化 |
| 每次连接独立创建对象的模式 | ❌ 废弃，改为 SessionManager 集中管理 |

---

## TODOS.md 新增项

```markdown
### P2 — Session 架构

- [ ] **T16** — Session 管理核心：SessionManager + SessionState + 排他连接
  - 文件：`backend/src/session/manager.py`, `models.py`, `persistence.py`, `serializer.py`
  - 验证：`uv run pytest backend/tests/session/`
  - 估时：human ~3h / CC ~30min

- [ ] **T17** — WebSocket handler 重构：连接恢复、断开快照、TTL
  - 文件：`backend/main.py`
  - 验证：WebSocket 重连测试
  - 估时：human ~2h / CC ~20min

- [ ] **T18** — Agent 状态序列化：ContextStore + Orchestrator to_dict/from_dict
  - 文件：`backend/src/agent/context_store.py`, `orchestrator.py`
  - 验证：序列化往返测试
  - 估时：human ~1h / CC ~15min

- [ ] **T19** — 前端重连支持：useWebSocket 携带 session_id
  - 文件：`frontend/src/hooks/useWebSocket.ts`
  - 验证：手动刷新页面测试
  - 估时：human ~30min / CC ~10min

- [ ] **T20** — Session 模块完整测试（5 个测试文件）
  - 估时：human ~2h / CC ~20min
```

---

## Implementation Tasks

| 编号 | 优先级 | 组件 | 任务 | 文件 | 验证 |
|---|---|---|---|---|---|
| T1 | P1 | session | 新增 `PersistenceBackend` ABC + `InMemoryBackend` | `backend/src/session/persistence.py` | `pytest backend/tests/session/test_persistence.py` |
| T2 | P1 | session | 新增 `SQLiteBackend` | `backend/src/session/persistence.py` | `pytest backend/tests/session/test_persistence.py` |
| T3 | P1 | session | 新增 `SessionState` + `Session` 模型 | `backend/src/session/models.py` | 类型检查通过 |
| T4 | P1 | session | 新增 `ContextStore`/`Orchestrator` 序列化器 | `backend/src/session/serializer.py` | `pytest backend/tests/session/test_serializer.py` |
| T5 | P1 | session | 新增 `SessionManager`（registry + TTL + 快照） | `backend/src/session/manager.py` | `pytest backend/tests/session/test_manager.py` |
| T6 | P1 | main | 重构 `legal_session()` 支持重连恢复 | `backend/main.py` | `pytest backend/tests/test_main_reconnect.py` |
| T7 | P2 | agent | `ContextStore.to_dict()` / `from_dict()` | `backend/src/agent/context_store.py` | `pytest backend/tests/session/test_serializer.py` |
| T8 | P2 | agent | `Orchestrator.to_dict()` / `from_dict()` | `backend/src/agent/orchestrator.py` | `pytest backend/tests/session/test_serializer.py` |
| T9 | P2 | diarization | `Enrollment.to_dict()` / `from_dict()` | `backend/src/diarization/enrollment.py` | `pytest backend/tests/session/test_serializer.py` |
| T10 | P2 | models | `Utterance.to_dict()` / `from_dict()` | `backend/src/models/utterance.py` | `pytest backend/tests/session/test_serializer.py` |
| T11 | P2 | config | 新增 SESSION_SNAPSHOT_INTERVAL, SESSION_TTL_SECONDS | `backend/src/config.py` | 配置加载测试 |
| T12 | P2 | frontend | useWebSocket 重连携带 session_id | `frontend/src/hooks/useWebSocket.ts` | 手动测试 |
| T13 | P2 | session | WebSocket 集成测试（重连全流程） | `backend/tests/session/test_integration.py` | `pytest` |
| T14 | P3 | session | LRU 淘汰大内存 detached sessions | `backend/src/session/manager.py` | 压力测试 |
| T15 | P3 | session | 增量快照优化 | `backend/src/session/manager.py` | 性能测试 |

---

## 依赖关系与并行策略

```
Lane A (数据层，可独立):
  T1 → T2 → T3 → T4
  (persistence + models + serializer)

Lane B (Agent 序列化，可独立):
  T7 → T8 → T9 → T10
  (context_store + orchestrator + enrollment + utterance)

Lane C (主流程，依赖 A 和 B):
  T5 (SessionManager) → T6 (main.py 重构)
  依赖: Lane A 完成

Lane D (前端 + 集成，依赖 C):
  T12 (前端) + T13 (集成测试)
  依赖: Lane C 完成
```

**执行顺序：**
1. 并行启动 Lane A + Lane B（两个 worktree 或同一分支）
2. Lane C 等 A+B 完成后启动
3. Lane D 等 C 完成后启动

---

## CEO Review 扩展决策

由 `/plan-ceo-review` 生成，2026-05-29。

### 接受的扩展

| 编号 | 扩展 | 决策 | 原因 |
|---|---|---|---|
| EXP1 | 会谈 AI 摘要 | ✅ 接受 | 利用已有 HeavyAgent，成本低，律师价值极高 |

### 跳过的扩展

| 编号 | 扩展 | 决策 | 原因 |
|---|---|---|---|
| EXP2 | 前端"历史会谈"页面 | ❌ 跳过 | 用户选择跳过 |

### 推迟的扩展

| 编号 | 扩展 | 决策 | 原因 |
|---|---|---|---|
| EXP3 | 会谈数据导出 | ⏸️ 推迟 | 等 Session 架构稳定后再做 |

### 安全确认

| 编号 | 决策 | 选择 |
|---|---|---|
| SEC1 | session_id 生成方式 | UUID（`uuid.uuid4()`） |

---

## CEO Review 关键发现

### 架构（Section 1）
- AI 摘要应在 Session 关闭时**异步触发**，不阻塞 WS 关闭流程
- Session 持久化后，数据层成为所有上层功能（案件管理、洞察、导出）的基础设施

### 安全（Section 3）
- ✅ 已确认：session_id 使用 UUID，防止遍历攻击
- ⚠️ 匿名模式下 session_id 既是定位符也是密码——需在 UI 中明确告知律师"保存好 session_id"
- ⚠️ 反序列化攻击风险：恶意构造的 SQLite 数据可能导致代码执行——需验证 schema 版本号

### 长期轨迹（Section 10）
- 匿名模式 → 用户系统的迁移路径：加 `users` 表，`sessions.user_id` 从 nullable → required
- SQLite → Redis/PostgreSQL 迁移路径：`PersistenceBackend` ABC 已预留接口
- 数据债务：匿名模式下会谈数据无法归属到真实律师——需在上线前完成用户系统

---

## Next Steps

1. **生成 plan 文件** ← 已完成
2. **如需实现**：按 Implementation Tasks 逐个完成（建议 Lane A + B 并行启动）
3. **AI 摘要**：在 Session 关闭流程中集成 HeavyAgent 调用（EXP1）
3. **如需进一步 review**：可运行 `/ship` 在代码完成后做 diff review
