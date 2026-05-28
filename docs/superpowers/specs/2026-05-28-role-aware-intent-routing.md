# 角色感知意图路由 — 设计文档

**日期:** 2026-05-28
**状态:** 已实现
**关联:** `2026-05-27-realtime-copilot-architecture.md`

## 问题

上一版 IntentRouter 存在两个缺陷：

1. **不区分角色** — 律师说"好的"和客户说"好的"被同等对待，但律师的确认可能是策略决策点，客户的是无信息应答
2. **不区分简单/复杂** — `simple` 和 `complex` 都走 HeavyAgent 深度分析，但简单查询（法条引用、金额计算）可以用更轻量的路径直接回答

## 设计

### 1. 角色感知的 IntentRouter

`IntentRouter.classify()` 新增 `speaker` 参数，prompt 按角色给出不同判断标准：

| 说话人 | ignore 标准 | simple 标准 | complex 标准 |
|--------|------------|------------|-------------|
| client | 寒暄、确认、无法律信息 | 明确的法条查询或计算需求 | 策略判断、风险评估 |
| lawyer | 常规事实询问、流程引导 | 可直接补充的法条/计算 | 分析存在遗漏 |
| uncertain | 按 client 规则 | 按 client 规则 | 按 client 规则 |

### 2. 结构化输出（instructor）

用 Pydantic 模型约束 LLM 输出，替代手动 JSON 解析：

```python
class IntentResult(BaseModel):
    severity: Literal["ignore", "simple", "complex"]
    intent_type: Literal["query_law", "compute_compensation", 
                         "draft_clause", "summarize", "record_only", "none"]
    law_domain: str | None
    entities: list[str]
    rationale: str
```

使用 `instructor` 库的 JSON 模式，稳定性优于裸 JSON + `extract_json_from_markdown`。

### 3. 路由分化

`Orchestrator` 根据 `severity` 走不同路径：

| severity | 路径 | 行为 |
|----------|------|------|
| ignore | 不触发 | 不调任何 Agent |
| simple | `HeavyAgent.analyze_quick()` | 用精简 prompt（无 skills），要求 1-3 句直接回答 |
| complex | `HeavyAgent.analyze()` | 完整 Agent + skills + 多步推理 |

### 4. HeavyAgent 双模式

- `analyze()` — 完整 legal analysis agent（skills + 深度推理）
- `analyze_quick()` — 精简 agent，不带 skills，针对简单查询快速响应

## 改动文件

| 文件 | 改动 |
|------|------|
| `backend/src/agent/intent_router.py` | 重写：Pydantic 模型 + instructor + 角色感知 prompt |
| `backend/src/agent/orchestrator.py` | speaker 传递 + severity 路由分化 |
| `backend/src/agent/heavy_agent.py` | 新增 `analyze_quick()` 双模式 |
| `backend/tests/conftest.py` | 新增 `mock_ir_client` fixture |
| `backend/tests/test_intent_router.py` | 重写：5 个角色感知测试 |
| `backend/tests/test_orchestrator.py` | 适配新接口 |
| `backend/tests/test_heavy_agent.py` | 适配新接口 + quick 模式测试 |
| `backend/pyproject.toml` / `uv.lock` | 新增 `instructor` 依赖 |

## 验收

- [x] IR 按角色差异化判断
- [x] simple → analyze_quick / complex → analyze
- [x] ignore 不触发任何 Agent
- [x] 全部 29 个单元测试通过
- [ ] 真实对话 E2E 测试（待门 3 验收）
