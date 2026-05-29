# Session 前后端对齐检查交接

**日期:** 2026-05-29
**状态:** 对齐检查完成，发现 2 个未对齐点待修复

---

## 背景

本次检查聚焦「前后端是否打通」以及「session 逻辑是否对上」。核心文件已审阅：

| 路径 | 说明 |
|------|------|
| `backend/main.py` | WebSocket 主路由，`/ws/{session_id}`，session 生命周期管理 |
| `backend/src/session/manager.py` | SessionManager：CRUD、排他连接、快照、TTL |
| `backend/src/session/models.py` | `SessionState` dataclass，状态机 `active → disconnected → closed` |
| `backend/src/session/serializer.py` | 序列化/反序列化 |
| `frontend/src/hooks/useWebSocket.ts` | WebSocket hook：session_id 生成、重连、消息分发 |
| `frontend/src/pages/LiveSession.tsx` | 实时会谈页面：转写、分析、建议 UI |

---

## 对齐情况总览

| 能力 | 状态 | 说明 |
|------|------|------|
| WebSocket 连接 + session_id | ✅ | 前端 UUID → `/ws/{id}`，后端 get/restore/create 三级回退 |
| 排他连接 | ✅ | 后端 `attach_ws` 拒绝重复连接（code=1008），前端自动重连 |
| `transcript` 消息 | ✅ | 字段 `text`, `speaker`, `is_final` 一致 |
| `suggestion.pending` / `ready` | ✅ | meta 字段（`intent_type`, `law_domain`, `request_id` 等）一致 |
| `confirm` / `dismiss` | ✅ | 前端发 confirm/dismiss，后端调 `orch.confirm_analysis` / `dismiss_pending` |
| ping/pong 心跳 | ✅ | 两端都有 |
| **后端发送 `analysis` 消息** | ❌ **缺失** | 前端注册了 `onAnalysis` 回调，后端**没有任何地方发 `type: "analysis"`** |
| **前端结束 session (`close`)** | ⚠️ **缺失** | 后端支持 `close` 消息生成 summary 并关闭，前端无结束按钮/调用 |

---

## 未对齐点详情

### 1. `analysis` 消息缺失（主要）

**现象：**
- 前端 `LiveSession.tsx:232` 定义了 `onAnalysis` 回调，会把结果加入左侧「实时洞察」面板
- 后端 `main.py` 里只有 `on_suggestion` 回调发送 `suggestion.pending` / `suggestion.ready`
- 后端**没有任何代码发送 `type: "analysis"` 的消息**
- 前端 `analysis` UI 区域永远不会被填充（永远显示"系统正在监听并分析对话内容…"）

**需要确认：**
Orchestrator 是否有分析产出（非 suggestion）需要走 `analysis` 通道？还是所有洞察都通过 suggestion 下发？

**修复选项：**
- **选项 A**（有独立 analysis 产出）：在后端 `main.py` WS 循环里加 `analysis` 消息发送逻辑
- **选项 B**（没有独立 analysis）：删掉前端 `onAnalysis` 回调和相关类型，避免误导

### 2. 结束 session 的 UI/调用缺失

**现象：**
- 后端 `main.py:199-204` 支持 `type: "close"` 消息：生成 summary、标记 `closed`、触发最终快照
- 前端 `useWebSocket.ts` 没有暴露发送 `close` 的函数
- `LiveSession.tsx` 没有结束会谈的按钮或逻辑
- Session 只能通过关闭页面（触发 `detach_ws` → `disconnected`）或 TTL 超时来结束，无法主动生成 summary

**修复：**
- 前端加一个「结束会谈」按钮 → 调用 `ws.send(JSON.stringify({ type: 'close' }))`
- 或页面 `beforeunload` 时自动发 `close`

---

## 文件定位

```
backend/main.py:72-224          # WebSocket 路由，需补充 analysis 消息发送
backend/main.py:199-204         # close 消息处理
frontend/src/hooks/useWebSocket.ts:58-156   # 需暴露 closeSession
frontend/src/pages/LiveSession.tsx:214-473  # 需加结束按钮
```

---

## 建议的后续动作

1. **确认产品设计**：`analysis` 和 `suggestion` 是两个独立通道还是合并为一路？
2. **按决策修复**：要么补后端 analysis 发送，要么清前端 analysis 消费
3. **补结束 session**：前端加「结束会谈」按钮，调用 close → 后端生成 summary → 可展示总结
