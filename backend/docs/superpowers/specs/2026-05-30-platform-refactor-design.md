# 平台重构：多用户、Session 生命周期、Socket 解耦

## 概述

将 legal-agent 从"单机 demo"改造为多用户平台。核心变化：

1. **数据底座**：SQLite → PostgreSQL，新增 User / Session / SessionContext / Voiceprint 四张表
2. **登录系统**：手机号 + 验证码(1234) + JWT
3. **Session 生命周期**：REST API 显式创建/关闭，不再由 WS 隐式创建
4. **WebSocket 纯传输**：session 与 socket 解耦，后来者接管
5. **声纹管理**：挂在 User 上，不再进程级单例
6. **前端**：多页面路由(登录 → 列表 → 会谈 → 声纹设置)

---

## 架构总览

```
┌──────────────────┐     HTTP/REST       ┌──────────────┐      WS       ┌──────────┐
│   前端 SPA        │ ◄─────────────────► │   FastAPI     │ ◄───────────► │  浏览器   │
│                   │     JWT Bearer      │              │    音频流      │  麦克风   │
│  /login           │                     │  /api/auth/* │              └──────────┘
│  /sessions        │                     │  /api/sessions/*
│  /session/:id     │                     │  /api/voiceprint
│  /voiceprint      │                     │  /ws/{session_id}
└──────────────────┘                     └──────┬───────┘
                                                │
                                          ┌─────▼──────┐
                                          │  PostgreSQL │
                                          │  (已有实例)  │
                                          └────────────┘
```

---

## 数据模型

所有新表建在现有 PostgreSQL 实例中（`AGNO_DB_URL` 已指向 `localhost:5432/legal_agent`）。

```sql
-- 用户
CREATE TABLE users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    phone       TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 会话（列表查询用，不含大字段）
CREATE TABLE sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status      TEXT NOT NULL DEFAULT 'live',   -- 'live' | 'closed'
    summary     TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_sessions_user_status ON sessions(user_id, status);

-- 会话上下文（大 blob，与 sessions 分表避免列表查询扫全量）
CREATE TABLE session_contexts (
    session_id    UUID PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    context_store JSONB NOT NULL DEFAULT '{}',
    orchestrator  JSONB NOT NULL DEFAULT '{}',
    enrollment    JSONB NOT NULL DEFAULT '{}',
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 用户声纹（一个用户一套，不是每个 session 一份）
CREATE TABLE voiceprints (
    user_id    UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    embedding  FLOAT8[] NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 声纹数据流

1. 用户上传注册音频 → 提取 embedding → upsert `voiceprints`
2. 创建 session 时：读 `voiceprints` → 构建 `Enrollment`(client_embedding=NULL) → 写入 `session_contexts.enrollment`
3. session 期间双声纹自举写 `client_embedding` → 存在 session 自己的 enrollment 副本中 → 不污染 user 模板

### 与现有 Agno 表的关系

Agno 框架已经在同一个 PostgreSQL 库里维护自己的表（agno_sessions 等），新增四张表与 Agno 表共存，互不冲突。

---

## API 设计

所有 `/api/*` 路径（除 `/api/auth/*`）需要 JWT 认证。JWT 通过 `Authorization: Bearer <token>` header 传入。

### JWT 中间件

- `JWT_SECRET` 从 `.env` 读取，开发环境用固定值
- token 有效期 7 天
- 解析后注入 `request.state.user_id`

### 登录

```
POST /api/auth/send-code
  body: { "phone": "13800138000" }
  → 200 { "ok": true }
  # 验证码固定 "1234"，不真正发送短信

POST /api/auth/verify
  body: { "phone": "13800138000", "code": "1234" }
  → 200 { "token": "eyJ...", "user": { "id": "uuid", "phone": "..." } }
  # 新手机号自动创建用户，已存在则直接返回 token
```

### 会话

```
POST   /api/sessions
  → 201 { "id": "uuid", "created_at": "..." }
  # 后端动作: 读 user voiceprint → 构建 Enrollment → INSERT sessions + session_contexts

GET    /api/sessions
  → 200 { "sessions": [{ "id", "status", "summary", "created_at", "updated_at" }, ...] }
  # 按 created_at DESC，可选 ?status=live 过滤

GET    /api/sessions/{id}
  → 200 { "id", "status", "summary", "created_at", "updated_at" }
  # 详情不含 context blob

POST   /api/sessions/{id}/close
  → 200 { "ok": true }
  # status: live → closed（终态，不可逆）
  # 后端动作: 关掉该 session 的 WS（若存在）→ 生成 summary → UPDATE status

DELETE /api/sessions/{id}
  → 200 { "ok": true }
  # 硬删除 + ON DELETE CASCADE 自动删 session_contexts
```

### 声纹

```
GET    /api/voiceprint
  → 200 { "has_voiceprint": true, "created_at": "...", "updated_at": "..." }

PUT    /api/voiceprint
  body: multipart/form-data, file: "audio.wav"
  → 200 { "ok": true }
  # 提取 embedding → upsert voiceprints

DELETE /api/voiceprint
  → 200 { "ok": true }
```

---

## WebSocket — Session 与 Socket 解耦

```
WS /ws/{session_id}?token=<jwt>
```

### 握手流程

```
1. 验证 token → user_id
2. 查 sessions 表:
   - 不存在              → 4002 关闭
   - user_id 不匹配       → 4003 关闭
   - status = 'closed'   → 4001 关闭
   - status = 'live'     → 继续

3. 查 session_contexts → 恢复 enrollment / context_store / orchestrator
4. attach(session_id, ws):
   - 若 _ws_map 中已有旧 ws → 用 code=4000 关掉旧 ws
   - _ws_map[session_id] = ws
5. 进入音频循环（与现在逻辑一致）
6. finally: detach_ws(session_id, ws)
```

WS handler 不再负责 session 创建——那是 REST 的事。

### 关闭码语义

| code | 含义 | 前端行为 |
|------|------|----------|
| `4000` | 被新连接接管 | 提示"会话已在其他窗口打开"，不重连 |
| `4001` | 会话已结束 | 提示"会话已结束"，跳转 /sessions |
| `4002` | 会话不存在 | 提示"会话不存在"，跳转 /sessions |
| `4003` | 无权访问 | 提示"无权访问"，跳转 /sessions |
| 其他 | 网络原因 | 退避重连（最多 3 次，间隔 2s） |

### Session 状态机

```
           POST /sessions        POST .../close
  (不存在) ─────────────────► live ─────────────► closed (终态)
                               │
                               │ WS 断开（网络/刷新）
                               ▼
                             live  ← 状态不变
                               │
                               │ 新 WS 连接
                               ▼
                             live  ← 接管继续
```

只有 `live` 和 `closed` 两个业务状态。不再有 `disconnected`。

### _ws_map 精简

```python
async def attach_ws(self, session_id: str, ws: WebSocket) -> WebSocket | None:
    """绑定 ws 到 session。若有旧 ws 则关掉并返回。"""
    async with self._lock:
        old = self._ws_map.pop(session_id, None)
        self._ws_map[session_id] = ws
        return old

async def detach_ws(self, session_id: str, ws: WebSocket) -> None:
    """解绑。仅当 ws 匹配时才移除。"""
    async with self._lock:
        if self._ws_map.get(session_id) is ws:
            self._ws_map.pop(session_id, None)
```

不再需要：DISCONNECTED 探测、旧 ws client_state 判断、1008 拒绝分支。

---

## 前端

### 路由

| 路径 | 页面 | 鉴权 |
|------|------|------|
| `/login` | 登录 | 否 |
| `/sessions` | 会话列表 | 是 |
| `/session/:id` | 实时会谈 | 是 |
| `/voiceprint` | 声纹管理 | 是 |
| `/` | → 重定向到 `/sessions`（有 token）或 `/login`（无 token） | — |

### Auth 上下文

```tsx
// AuthContext: 全局持有 token + user，子路由通过 ProtectedRoute 守卫
<AuthProvider>
  <Routes>
    <Route path="/login" element={<Login />} />
    <Route element={<ProtectedRoute />}>
      <Route path="/sessions" element={<SessionList />} />
      <Route path="/session/:id" element={<LiveSession />} />
      <Route path="/voiceprint" element={<VoiceprintSettings />} />
    </Route>
  </Routes>
</AuthProvider>
```

### useWebSocket 清理

现状问题点 → 改后：

| 现状 | 改后 |
|------|------|
| `getOrCreateSessionId()` 读 localStorage | **删除**，sessionId 从 `useParams()` 取 |
| url 参数 | `(sessionId, token, callbacks)` |
| `stableConnectionMs = 5000` | 不再需要（不会再有 open→close 死循环） |
| `code === 1008` 特判 | 换成 `code >= 4000 && code < 5000` |
| 3 次重连、2s 间隔 | 保留 |
| `WsLike` 接口、`WsFactory` | 删除（测试需要时直接 mock WebSocket） |

### localStorage 用途

| 存什么 | 用途 |
|--------|------|
| `auth_token` | JWT token，登录后写入，退出时清除 |
| 不再存 `session_id` | session id 从 URL 来 |

---

## 实现步骤

按依赖关系排序，每步独立 spec + 独立 PR：

```
Step 1: 数据底座     — PostgreSQL schema 迁移 + SessionManager 改造
Step 2: 登录系统     — JWT 中间件 + /api/auth/* + 前端登录页 + AuthContext
Step 3: 会话 CRUD    — /api/sessions/* + 前端列表页
Step 4: 声纹管理     — /api/voiceprint + 前端声纹设置页
Step 5: Socket 解耦  — WS handler 改造 + useWebSocket 重写 + 关闭码
Step 6: 端到端联调   — 全流程走通 + 回归测试 + 清理废弃代码
```

---

## 边界条件与向后兼容

- **现有 SQLite 数据**：不迁移。开发阶段数据量小，直接丢弃。旧的 `sessions.db` 文件不再被读取。
- **旧的 `/register` 路由和 VoiceprintRegister 页面**：在 Step 4 中被新声纹设置页替代。
- **旧的 `session_manager.create_session` 签名**：改为接受 `user_id` + `enrollment`。
- **Agno agent 状态持久化**：不变，仍使用 Agno 自己的 PostgreSQL 表。
- **现有测试**：Step 1-5 每步完成后跑相关测试，Step 6 做全量回归。

---

## 未覆盖事项（后续 spec）

- 发送真实短信验证码
- 注销/登出（当前只需清前端 token）
- 会话搜索/分页
- 多律师并发（当前一个 user 可以有多个 live session，但 WS 排他是按 session 粒度的）
- session 录音回放
