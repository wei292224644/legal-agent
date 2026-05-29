# CONTEXT — legal-agent

领域术语表。只记术语定义，不记实现细节。

---

## 核心角色

**律师 (Lawyer)**
使用系统的专业用户。会谈中的主持方，负责与客户沟通并作出法律判断。AI 的所有辅助行为都以律师为服务对象。

**客户 (Client)**
接受法律咨询的当事人。其陈述是 AI 分析需求的主要来源。

---

## 会谈流程

**会谈 (Session)**
一次律师与客户的完整咨询过程，对应一个 WebSocket 连接和一个 session_id。

**发言 (Utterance)**
STT 输出的一句话，含文字、时间戳、关闭原因（vad / soft_cap）和说话人标签（lawyer / client / uncertain，声纹未定时为 None）。系统贯穿始终的核心数据对象。

**上下文窗口 (Context Window)**
ContextStore 维护的最近 N 句对话记录（滑动窗口），供 IntentRouter / ProfileAgent 判断当前需求。

---

## Agent 体系

**Orchestrator（中央调度器）**
消费事件总线，对每句发言并行触发 IntentRouter + ProfileAgent，按分类结果决定：忽略 / 快速响应（simple）/ 挂起等确认（complex）。管理 pending 请求。

**IntentRouter（意图分类）**
对每句发言做角色感知分类，输出 severity（ignore / simple / complex）和 intent_type。绝大多数返回 ignore。当前为 LLM（千问）实现，计划替换为本地 BERT。

**ProfileAgent（画像提取）**
LLM 事实提取器，仅对客户（及 uncertain）发言触发——律师发言不提取。从滑动窗口上下文抽取结构化法律事实，append-only 写入用户画像。与 IntentRouter 是两次独立调用，刻意不合并（为 BERT 化预留）。

**HeavyAgent（深度分析 Agent）**
基于 Agno + DeepSeek，两种模式：
- `analyze_quick`：severity=simple 时由 Orchestrator fire-and-forget 触发，1-3 句快速回答直接推送，无需律师确认；带 generation 检查防过期结果。
- `analyze`：severity=complex 时先推 pending 卡片，律师确认后才触发，注入领域 Skill 做完整深度分析。

**用户画像 (User Profile)**
ProfileAgent 持续构建的 append-only 数据结构，存于 ContextStore。每个 key 下保留所有历史记录（不同时间戳不同值），深度分析时优先采信时间戳最新的值。会话级别生命周期。

**Skill（领域技能包）**
注入到 `HeavyAgent.analyze` 的领域知识单元，包含操作步骤定义和分析报告格式。

---

## 触发机制

**逐句触发**
每句发言经事件总线投递给 Orchestrator。IntentRouter 对每句分类，ProfileAgent 仅对客户 / uncertain 发言提取——二者在消费者内并行触发后等待结果。simple 命中时，快速分析（`analyze_quick`）以独立 task fire-and-forget 派发，不阻塞后续 utterance；complex 命中时推 pending 卡片等待律师确认。

---

## 意图处理

**Intent（意图）**
IntentRouter 识别到的、需要律师确认才执行的复杂（complex）需求。包含触发发言和分类 meta。

**Intent Card（意图卡片）**
complex 命中时推送给前端的待确认提示，对应 WebSocket 消息 `suggestion.pending`（text=null + meta）。律师确认（`confirm`）或忽略（`dismiss`）。

**Pending Intent（待确认意图）**
已识别但尚未被律师确认或忽略的 complex 请求，暂存于 `Orchestrator._pending`（按 request_id 索引）。

**简单任务 (Simple Task)**
`HeavyAgent.analyze_quick` 可直接完成并自动推送结果的需求，无需律师确认。

**复杂任务 (Complex Task)**
需要深度执行、由律师主动确认后才触发 `HeavyAgent.analyze` 的需求。

---

## 分析结果

**Suggestion（分析建议）**
HeavyAgent 的单条输出，经 `suggestion.ready` 推送：一段 Markdown 文本（`text`）+ meta（severity / intent_type / law_domain / entities / utt_id）。
> 注：早期设计的结构化 AnalysisResult（类别 / 标题 / 风险等级）尚未落地，前端 `AnalysisData` 类型为该旧设计的残留，当前数据流不产生它。

---

## 事件层

**事件总线 (UtteranceBus)**
会话级别的有界异步队列（maxsize=10），承载 STT 产出的 Utterance，按序分发给 Orchestrator 消费者。解耦 STT（生产者）与 Agent（消费者）的速率差异；队列满时丢弃新消息以防内存堆积。

---

## WebSocket 协议

单一端点 `/ws/{session_id}`。

| 方向 | 类型 | 说明 |
|------|------|------|
| C→S | (binary) | 16-bit PCM 音频帧 |
| C→S | `ping` | 心跳 |
| C→S | `confirm` | 律师确认 pending，带 `request_id`，触发 `HeavyAgent.analyze` |
| C→S | `dismiss` | 律师忽略，带 `request_id`，清除 pending |
| S→C | `transcript` | 转写结果（含 speaker、t_start/t_end、closed_by） |
| S→C | `suggestion.pending` | 待确认建议（text=null + meta） |
| S→C | `suggestion.ready` | 已就绪建议（text + meta） |
| S→C | `pong` / `confirm_ack` / `error` | 心跳回应 / 确认回执 / 错误 |
