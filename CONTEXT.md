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

**转录结果 (TranscriptResult)**
STT 输出的一句话，包含文字内容和说话人角色标签（律师 / 客户 / 未知）。

**上下文窗口 (Context Window)**
分析 Agent 维护的最近 N 句对话记录（滑动窗口），用于判断当前需求。

---

## Agent 体系

**Judge Agent（判断 Agent）**
三层架构的核心。每句客户话触发，fire-and-forget。只做两件事：提取结构化事实追加到用户画像、判断是否需要介入（none / simple / complex）。不阻塞、不被 cancel。98% 以上的调用返回 none。

**Simple Analysis Agent（简单分析 Agent）**
Judge 判定 simple 时触发，fire-and-forget。针对具体话题快速产出法条引用、合同建议或风险提示，直接推送到前端侧边栏，无需律师确认。

**Executor Agent（编排 Agent）**
Judge 判定 complex 时先弹 Intent Card，律师点确认后才触发。深度法律分析，输出完整报告（法规 + 合同 + 风险）。可同时存在多个实例。

**用户画像 (User Profile)**
Judge Agent 持续构建的 append-only 数据结构。每个 key 下保留所有历史记录（不同时间戳不同值），深度分析时优先采信时间戳最新的值。会话级别生命周期。

**Skill（领域技能包）**
注入到 Executor Agent 的领域知识单元，包含操作步骤定义和分析报告格式。

---

## 触发机制

**Fire-and-forget（触发即忘）**
每句客户话即刻触发 Judge Agent，不 await、不 cancel、不 debounce。Judge 自行判断是否需要介入，介入时再派发 Simple Analysis 或 Intent Card，均为独立的 fire-and-forget 任务。

---

## 意图处理

**Intent（意图）**
分析 Agent 识别到的、需要律师确认才执行的复杂需求。包含一个问句形式的提示和触发上下文。

**Intent Card（意图卡片）**
推送给前端的 UI 提示，以问句形式呈现 Intent（如"需要查《劳动合同法》第82条吗？"），律师可确认或忽略。

**Pending Intent（待确认意图）**
已识别但尚未被律师确认或忽略的 Intent，暂存于 LegalAgent 内部。

**简单任务 (Simple Task)**
分析 Agent 可直接完成并自动推送结果的需求，无需律师确认。

**复杂任务 (Complex Task)**
需要深度执行、由律师主动确认后才触发编排 Agent 的需求。

---

## 分析结果

**AnalysisResult（分析结果）**
编排 Agent 的单条输出，包含类别（法规 / 合同 / 风险）、标题、内容、引用来源、风险等级（仅风险类）。

---

## 事件层

**事件总线 (Event Bus)**
会话级别的消息中间层，接收 STT 产出的领域事件并按序分发给 Agent 消费者。解耦生产者（STT）与消费者（Agent）的速率差异和生命周期。

**发言事件 (UtteranceEvent)**
STT 模块产出的领域事件，代表一次完整的说话检测-识别-声纹判定结果。通过事件总线投递给 Agent 处理。

---

## WebSocket 协议扩展

在原有 transcript / analysis / status 基础上新增：

| 方向 | 类型 | 说明 |
|------|------|------|
| S→C | `intent` | 推送 Intent Card，律师确认或忽略 |
| C→S | `confirm_intent` | 律师确认，触发编排 Agent |
| C→S | `dismiss_intent` | 律师忽略，清除 Pending Intent |
