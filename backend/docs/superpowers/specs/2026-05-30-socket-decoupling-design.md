# Socket 解耦：Session 显式创建 + 后来者接管

## 范围

- 加 `POST /api/sessions` REST 端点，session 创建不再由 WS 隐式完成
- `attach_ws` 改为"后来者胜"：旧连接被主动关掉，新连接接管
- WS handler 不再有创建能力，只做验证 + 传输
- 前端 `useWebSocket` 重写，删 localStorage session_id、stableConnectionMs、WsLike/WsFactory
- 前端入口页加"开始新会谈"按钮

## 不变

- 数据库：继续 SQLite，表结构不动
- `ContextStore` / `Orchestrator` / `Enrollment` 序列化
- `SessionState` 模型保留（含 disconnected 状态，留着后续平台重构时再清理）
- 后端音频循环逻辑、文本消息处理
- 前端 LiveSession 页面的 UI

---

## Backend

### 新增 `POST /api/sessions`

```python
@app.post("/api/sessions")
async def create_session():
    enrollment = await asyncio.to_thread(_session_enrollment)
    session_id = await session_manager.create_session(enrollment)
    return {"session_id": session_id}
```

做的事就是现在 `legal_session` handler 里那段"session 不存在时创建"的逻辑，搬到这里。

### WS handler 简化

```
WS /ws/{session_id}

握手：
1. state = get_state 或 restore_session（从 DB 恢复）
2. 不存在 → 4002 关闭
3. status = closed → 4001 关闭
4. attach_ws(session_id, ws):
   - 若 _ws_map 中已有旧 ws → 用 4000 关掉旧 ws
   - _ws_map[session_id] = ws
5. 进入音频循环（不变）
6. finally: detach_ws(session_id, ws)
```

删掉："session 不存在就创建"那段。

### attach_ws 简化

```python
async def attach_ws(self, session_id: str, ws: object) -> object | None:
    """返回旧 ws（若有），调用方负责关掉。"""
    async with self._lock:
        old = self._ws_map.pop(session_id, None)
        self._ws_map[session_id] = ws
        return old
```

删掉：DISCONNECTED 探测、status 检查、1008 返回 False 分支。

### 关闭码

| code | 含义 |
|------|------|
| `4000` | 被新连接接管 |
| `4001` | 会话已结束 |
| `4002` | 会话不存在 |
| 其他 | 网络原因 |

---

## Frontend

### useWebSocket 重写

**删掉：**
- `getOrCreateSessionId` / `localStorage` 读 session_id
- `stableConnectionMs` + `stableTimerRef`
- `WsLike` 接口 + `WsFactory` 类型 + `factory` 参数
- `1008` 特判逻辑

**改成：**

```ts
function useWebSocket(sessionId: string, callbacks: Callbacks) {
  const wsUrl = `ws://localhost:8000/ws/${sessionId}`

  const onclose = (e: CloseEvent) => {
    if (e.code >= 4000 && e.code < 5000) return  // 业务关闭
    if (attempts < 3) setTimeout(connect, 2000)
  }
  // ...
}
```

- `sessionId` 直接当参数传入，从 `useParams()` 取
- `onclose` 里特判 `code >= 4000`，不重连
- 3 次重连、2s 间隔保留

### 入口页

改 `/`（现在是 redirect 到 `/register`）为一个简单页面：

- 按钮"开始新会谈"→ `POST /api/sessions` → 拿到 `{ session_id }` → `navigate('/session/' + id)`
- 或者最简单的做法：直接让 `/register` 页的路由暂时当入口，加一个按钮

当前 `App.tsx` 路由：

```
/ → redirect /register
/register → VoiceprintRegister
/session/:id → LiveSession
```

最小改动：把 `/` 改成直接显示一个按钮页，或者把 VoiceprintRegister 页加个"开始会谈"入口，声纹注册作为子功能。

## 文件变更清单

| 文件 | 操作 |
|------|------|
| `backend/main.py` | 加 `POST /api/sessions`；WS handler 删隐式创建、简化为校验+传输 |
| `backend/src/session/manager.py` | `attach_ws` 简化 |
| `frontend/src/hooks/useWebSocket.ts` | 重写 |
| `frontend/src/pages/LiveSession.tsx` | `useWebSocket` 调用适配新签名 |
| `frontend/src/App.tsx` | `/` 改为入口页 |
| `frontend/src/hooks/useWebSocket.test.ts` | 适配改动 |

## 验证标准

1. `POST /api/sessions` 返回 `session_id`
2. 带 session_id 连 WS → 握手成功 → 能收发音频和分析结果
3. 同一个 session_id 开第二个 tab → 旧 tab 的 WS 收到 4000，新 tab 正常
4. close session 后再连 → 收到 4001，不重连
5. 不存在的 session_id → 收到 4002，不重连
6. 前端刷新页面 → session_id 在 URL 上不变 → 重连成功，会话继续
7. 现有后端测试全部通过
