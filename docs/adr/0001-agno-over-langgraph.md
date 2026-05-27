# ADR 0001: 使用 Agno 而非 LangGraph 作为 Agent 框架

**状态:** 已决定  
**日期:** 2026-05-27

## 背景

系统需要一个 Agent 框架支撑两层架构：分析 Agent（常驻、可中断）+ 编排 Agent（按需触发、可并发）。

LangGraph 的核心优势是原生 human-in-the-loop interrupt，对应本系统的「律师确认 intent 后才执行」流程。

## 决策

使用 Agno。

## 原因

Skill（领域技能包）需要在每个 session 启动时**动态注入**，包含不同法律领域的操作步骤定义和报告格式。

LangGraph 的图拓扑在 `compile()` 时固定，动态变更操作步骤需要预注册所有可能节点或每次重新编译，引入不可接受的复杂度。

Agno 在 Agent 实例化时直接传入 `instructions`，Skill 内容自然流入 Agent 行为，无需绕过任何框架约束。

## 权衡

LangGraph 的 `interrupt()` 是更优雅的 human-in-the-loop 实现。本系统用 `_pending_intents: dict[str, CaseBrief]` 替代：分析 Agent 和编排 Agent 是两次独立的 Agno 运行，`confirm_intent` 消息触发第二次运行。这是可接受的 workaround，代价是约 5 行额外状态管理代码。
