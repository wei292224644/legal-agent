# 角色感知意图路由 — 设计文档

**日期:** 2026-05-28
**状态:** 待实现
**关联:** `2026-05-27-realtime-copilot-architecture.md`

## 问题

上一版 IntentRouter 存在三个缺陷：

1. **不区分角色** — 律师说"好的"和客户说"好的"被同等对待
2. **不区分简单/复杂** — `simple` 和 `complex` 都直接调 HeavyAgent
3. **complex 没有确认机制** — 复杂任务直接推送给律师，但律师可能不需要

## 设计

### 1. 角色感知的 IntentRouter

`IntentRouter.classify()` 新增 `speaker` 参数，prompt 按角色差异化判断：

| 说话人 | ignore | simple | complex |
|--------|--------|--------|---------|
| client | 寒暄、确认、无法律信息 | 明确法条查询/计算 | 策略判断、风险评估 |
| lawyer | 常规事实询问、流程引导 | 可直接补充的法条/计算 | 分析存在遗漏 |
| uncertain | 按 client 规则 | 按 client 规则 | 按 client 规则 |

### 2. 结构化输出（instructor）

用 Pydantic 模型 + `instructor` 库替代手动 JSON 解析：

```python
class IntentResult(BaseModel):
    severity: Literal["ignore", "simple", "complex"]
    intent_type: Literal["query_law", "compute_compensation",
                         "draft_clause", "summarize", "record_only", "none"]
    law_domain: str | None
    entities: list[str]
    rationale: str
```

### 3. 路由分化 + 确认机制

| severity | 行为 |
|----------|------|
| ignore | 不调任何 Agent |
| simple | 立即调 `HeavyAgent.analyze_quick()`，直接推送 `kind: "ready"` |
| complex | **不立即调 Agent**，推送 `kind: "pending"`（text=null, 含 request_id），等待律师确认 |

**确认流程：**

```
complex 识别 → WebSocket 推送 suggestion.pending（含 request_id, expires_in=30s）
                  ↓
         前端显示"分析?"确认按钮，30s 倒计时
                  ↓
     ┌─ 律师点击确认 → POST /confirm/{request_id} → Orchestrator.confirm_analysis()
     │                                                      ↓
     │                                            HeavyAgent.analyze()
     │                                                      ↓
     │                                            推送 suggestion.ready（完整分析结果）
     │
     └─ 律师忽略/超时 → 前端 dismiss → POST /dismiss/{request_id}
                           → Orchestrator.dismiss_pending()
                           → 后端超时清理（30s 过期自动移除）
```

### 4. Suggestion 事件契约

```json
// simple: 直接推送完整结果
{
  "kind": "ready",
  "text": "根据劳动法第87条，违法解除应支付2N赔偿金……",
  "meta": {
    "severity": "simple",
    "intent_type": "query_law",
    "law_domain": "劳动法",
    "entities": ["违法解除", "2N"],
    "utt_id": "u_42"
  }
}

// complex: 推送确认请求（不包含分析结果）
{
  "kind": "pending",
  "text": null,
  "meta": {
    "severity": "complex",
    "intent_type": "query_law",
    "law_domain": "劳动法",
    "entities": ["违法解除", "举证责任"],
    "utt_id": "u_42",
    "request_id": "req_a1b2c3d4",
    "expires_in": 30
  }
}
```

### 5. HeavyAgent 双模式

- `analyze_quick()` — 精简 prompt，不带 skills，1-3 句直接回答（simple 用）
- `analyze()` — 完整 Agent + skills + 多步推理（complex 确认后用）

### 6. 时效限制

| 层级 | 机制 |
|------|------|
| 后端 | pending 30s 过期，`cleanup_expired()` 移除；`confirm_analysis()` 拒绝过期请求 |
| 前端 | 倒计时 30s，超时自动关闭卡片，调 `dismiss` 接口 |

## 改动范围

| 文件 | 改动 |
|------|------|
| `intent_router.py` | Pydantic 模型 + instructor + 角色感知 prompt |
| `orchestrator.py` | speaker 传递 + severity 路由 + PendingRequest + confirm/dismiss/cleanup |
| `heavy_agent.py` | 新增 `analyze_quick()` |
| `main.py` (WebSocket) | 新增 confirm/dismiss 路由 |

## 验收

- [ ] IR 按角色差异化判断（client/lawyer/uncertain）
- [ ] simple → `analyze_quick()` → 直接推送 ready
- [ ] complex → 推送 pending（text=null），不调 analyze
- [ ] confirm → 调 `analyze()` → 推送 ready
- [ ] dismiss → 移除 pending，不调 analyze
- [ ] 过期请求 confirm 返回 false
- [ ] cleanup 自动清理超时 pending
