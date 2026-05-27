# Agent 架构设计

**日期:** 2026-05-27
**状态:** 已确认

## 概述

三层 Agent 架构，用于实时法律会谈辅助。系统旁听律师与客户的对话，持续维护用户画像，在恰当的时机主动提供法条引用和分析——不阻塞、不打断、不浪费。

## 架构

```
每句客户话
  │
  └─ LegalAgent.observe(text, speaker)  →  fire-and-forget（不 await，不 cancel）
       │
       └─ Judge Agent（1 个实例，每句触发，极轻量）
            │  输入：用户画像 + 最近 N 句上下文
            │  决策：通过 tool 调用决定下一步
            │
            ├─ 只调 update_fact ──→ 事实追加到画像，结束
            │
            ├─ 调 update_fact + trigger_simple_analysis
            │     └─ fire-and-forget → Simple Analysis Agent
            │                              └─ AnalysisResult → push 侧边栏
            │
            └─ 调 update_fact + trigger_complex_intent
                  └─ push Intent Card 到前端
                       └─ 律师点「确认」
                            └─ fire-and-forget → Executor Agent
                                                     └─ list[AnalysisResult] → push 侧边栏
```

所有 fire-and-forget 任务独立运行。Agent 之间互不阻塞。没有任何 Agent 被 cancel。

## 三个 Agent

全部使用 Agno + 同一个 Deepseek 模型（`deepseek-v4-flash`，OpenAI 兼容 API）。各自独立的 `Agent` 实例，`instructions`、`tools`、`output_schema` 各不相同。

### Judge Agent

- **触发：** 每句客户话（`observe()` 内 fire-and-forget）
- **职责：** 提取事实、追加到用户画像、判断是否需要介入
- **成本：** 极低——窄 prompt，98% 以上调用只调 `update_fact` 后结束
- **Agno 配置：** `Agent(model=..., instructions=JUDGE_PROMPT, tools=[update_fact, trigger_simple_analysis, trigger_complex_intent])`
- **不需要 output_schema。** Judge 通过调 tool 来做决策，不通过返回值。不调 tool = 什么都不做。
- **三个 tool（全部不阻塞，<1ms 返回）：**

| tool | 参数 | 行为 |
|------|------|------|
| `update_fact` | `key: str, value: str` | 追加 `{value, ts}` 到 `LegalAgent._user_profile[key]`，即时返回 |
| `trigger_simple_analysis` | `topic: str` | `asyncio.create_task(_run_simple_analysis(topic))`，fire-and-forget |
| `trigger_complex_intent` | `question: str, context: str` | 创建 IntentResult → 存入 `_pending_intents` → 调 `_on_intent` callback → push 前端 |

### Simple Analysis Agent

- **触发：** Judge 调了 `trigger_simple_analysis`
- **职责：** 针对具体话题做快速法律分析——法条引用、合同建议、风险提示
- **Agno 配置：** `Agent(model=..., instructions=SIMPLE_ANALYSIS_PROMPT, output_schema=SimpleAnalysisOutput, use_json_mode=True)`
- **输出：** `list[AnalysisResult]`，直接 push 侧边栏，无需律师确认
- **输入：** topic + 当前用户画像 + 最近上下文窗口

### Executor Agent

- **触发：** 律师在 Intent Card 上点「确认」→ `confirm_intent(intent_id)` → `asyncio.create_task`
- **职责：** 深度法律分析——法规引用、合同模板、风险评估的完整报告
- **Agno 配置：** `Agent(model=..., instructions=EXECUTOR_PROMPT, output_schema=ExecutorOutput, use_json_mode=True)`
- **输出：** `list[AnalysisResult]`，push 侧边栏
- **输入：** 完整 IntentResult + 创建 intent 时的上下文窗口快照 + 当前用户画像

## 数据结构

### 用户画像

Append-only dict，每个 key 下是时间戳记录列表：

```python
user_profile = {
    "employment_date": [
        {"value": "2024.11", "ts": "2026-05-27T13:01:20"},
    ],
    "contract_status": [
        {"value": "一年期合同，到期未续签", "ts": "2026-05-27T13:01:22"},
    ],
}
```

事实只追加不覆盖。同一 key 有多个版本时，分析 Agent 优先采信时间戳最新的值。

### AnalysisResult

```python
@dataclass
class AnalysisResult:
    category: str       # "statute" | "contract" | "risk"
    title: str
    content: str
    citation: str | None
    level: str | None   # "高" | "中" | "低"（仅 risk）
```

### IntentResult

```python
@dataclass
class IntentResult:
    intent_id: str      # UUID
    question: str       # 如 "需要查《劳动合同法》第82条吗？"
    context: str        # 触发该 intent 的对话片段
```

## 关键设计决策

1. **不 debounce，不 cancel。** 每句客户话 fire 一个 Judge 任务。多个任务可并发。各自 snapshot 当前状态。LLM 调用不浪费（judge 极轻量，98% 返回 none）。

2. **Judge 不做分析。** Judge 只提取事实 + 判断 yes/no + type。真正的法律分析由 Simple Analysis 或 Executor 执行，且全部 fire-and-forget。

3. **Append-only 用户画像 + 时间戳。** 事实跨次累积，不丢不覆。后续分析优先采信较新时间戳。

4. **复杂分析必须律师确认。** Intent Card 机制保证律师有完全控制权。

5. **全部使用 Agno。** Judge 用 Agno + tools 模式，Simple Analysis 和 Executor 用 Agno + output_schema + use_json_mode 模式。三个 Agent 共用同一个 Deepseek 模型，通过 role_map 兼容（`system→system`，Deepseek 不支持 `developer` role）。

## 源文件

| 文件 | 职责 |
|------|------|
| `backend/src/agent.py` | `LegalAgent` 类——observe/confirm/dismiss，状态管理，tool 实现 |
| `backend/src/agno_agents.py` | Agno Agent 工厂函数——judge、simple analysis、executor |
| `backend/main.py` | FastAPI + WebSocket，将 agent 连接到前端 |
| `backend/tests/test_agent.py` | LegalAgent 单元测试 |
| `backend/tests/test_agno_agents.py` | Agno Agent 配置和解析测试 |
