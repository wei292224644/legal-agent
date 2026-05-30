# Step 1: 数据底座 — PostgreSQL Schema + SessionManager 改造

## 范围

1. 在 PostgreSQL 中建四张表（users / sessions / session_contexts / voiceprints）
2. 重写 `PersistenceBackend` → `PostgresBackend`（替换 SQLiteBackend）
3. 改造 `SessionManager`：新增 `user_id` 维度、去掉 `disconnected` 状态、简化 `attach_ws`/`detach_ws`
4. 改造 `SessionState` 模型：加 `user_id`，status 改为 `live | closed`
5. 提供迁移脚本（DDL only，不迁移旧 SQLite 数据）

## 不变的部分

- `ContextStore` / `Orchestrator` 的 to_dict/from_dict 逻辑
- `Enrollment` 序列化
- `SessionSerializer` 的核心逻辑（调整适配新字段）
- 60s 快照、600s TTL 内存驱逐机制

## 详细设计

### 表结构（DDL）

```sql
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    phone       TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status      TEXT NOT NULL DEFAULT 'live',
    summary     TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_sessions_user_status ON sessions(user_id, status);

CREATE TABLE session_contexts (
    session_id    UUID PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    context_store JSONB NOT NULL DEFAULT '{}',
    orchestrator  JSONB NOT NULL DEFAULT '{}',
    enrollment    JSONB NOT NULL DEFAULT '{}',
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE voiceprints (
    user_id    UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    embedding  FLOAT8[] NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### PostgresBackend

在现有 `persistence.py` 中新增 `PostgresBackend(PersistenceBackend)`：

```
- 构造时接受 asyncpg pool 或连接串
- save(session_id, data): 写 sessions + session_contexts 两张表（事务）
- load(session_id): JOIN 两张表，拼回 dict
- delete(session_id): DELETE FROM sessions（CASCADE 自动删 context）
- list_ids(): SELECT session_id FROM sessions
- list_by_user(user_id): 新增方法，供 API 用
```

`SQLiteBackend` 和 `InMemoryBackend` 保留（测试用），但设为 deprecated。

### SessionState 模型变更

```python
@dataclass
class SessionState:
    session_id: str
    user_id: str                          # 新增
    created_at: float
    last_active_at: float
    context_store: dict
    orchestrator: dict
    enrollment: dict
    status: Literal["live", "closed"]     # 去掉 "disconnected"
    summary: str | None = None
```

### SessionManager 变更

**`attach_ws` — 简化：**

```python
async def attach_ws(self, session_id: str, ws: WebSocket) -> WebSocket | None:
    """绑定 ws。返回旧 ws（如果有）供调用方关掉。"""
    async with self._lock:
        old = self._ws_map.pop(session_id, None)
        self._ws_map[session_id] = ws
        return old
```

不再检查 status、不再探测 DISCONNECTED、不再返回 False。

**`detach_ws` — 保持不变：**

保留 `ws` 参数做竞态保护 —— 这是必要的，一个旧连接的 finally 不能误删新连接的引用。

**新增 `create_session` 签名：**

```python
async def create_session(
    self, user_id: str, enrollment: Enrollment, session_id: str | None = None
) -> str:  # returns session_id
```

**`restore_session` → `load_session`：**

不再隐式恢复"断开的 session"。调用方（WS handler）显式传入 session_id，从 DB 加载。只有 status=live 的才可加载。

### 迁移脚本

`backend/scripts/migrate_to_postgres.sql` — 纯 DDL，手动执行。

本地开发：在现有 `legal_agent` 库中执行 DDL，与 Agno 表共存。

## 验证标准

1. DDL 在本地 PostgreSQL 执行成功
2. `PostgresBackend` 的 save/load/delete/list_ids 通过单元测试
3. `SessionManager.create_session` + `attach_ws` + `detach_ws` 通过单元测试
4. 现有测试套件（除直接引用 SQLite 的测试外）全部通过

## 文件变更清单

| 文件 | 操作 |
|------|------|
| `backend/src/session/models.py` | 改：SessionState 加 user_id，status 去掉 disconnected |
| `backend/src/session/persistence.py` | 加：PostgresBackend |
| `backend/src/session/manager.py` | 改：create_session 签名、attach_ws 简化、restore→load |
| `backend/src/session/serializer.py` | 改：适配新字段 |
| `backend/main.py` | 改：替换 SQLiteBackend → PostgresBackend |
| `backend/scripts/migrate_to_postgres.sql` | 新：DDL 迁移脚本 |
| `backend/tests/` | 新/改：PostgresBackend + SessionManager 测试 |
