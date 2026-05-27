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

**特征提取 Agent (Feature Extractor)**
轻量 Agent，逐句提取结构化事实（入职日期、合同状态、社保缴纳等），输出 key-value 对带时间戳。只做提取不做法律判断，速度快、不可中断。产出的所有事实追加到用户画像，永不覆盖旧记录。

**用户画像 (User Profile)**
特征提取 Agent 持续构建的 append-only 数据结构。每个 key 下保留所有历史记录（不同时间戳不同值），深度分析时优先采信时间戳最新的值。会话级别生命周期，不跨会话持久化。

**分析 Agent (Analysis Agent)**
常驻 Agent，接收用户画像 + 最近对话，提炼案情摘要和识别法律需求。由客户停顿（debounce）触发，不被后续句子中断。输出案情摘要或 Intent。

**案情摘要 (Case Brief)**
分析 Agent 提炼的结构化输出：当事人基本情况、争议焦点、涉及法律领域。是编排 Agent 的输入。

**编排 Agent (Orchestration Agent)**
按需触发的执行 Agent，接收案情摘要 + 全量上下文，决定调用哪些工具并行执行，返回分析结果列表。可同时存在多个实例（一个 intent 一个）。

**Skill（领域技能包）**
注入到编排 Agent 的领域知识单元，包含操作步骤定义和分析报告格式。不同法律领域（劳动法、商业合同、隐私合规等）对应不同 Skill。

---

## 触发机制

**Debounce（停顿触发）**
客户说话后若 N 秒内无新客户句子到达，视为停顿。停顿触发分析 Agent，之前的句子仅在画像中积累，不触发分析。避免逐句 cancel 导致的 LLM 调用浪费。

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

## WebSocket 协议扩展

在原有 transcript / analysis / status 基础上新增：

| 方向 | 类型 | 说明 |
|------|------|------|
| S→C | `intent` | 推送 Intent Card，律师确认或忽略 |
| C→S | `confirm_intent` | 律师确认，触发编排 Agent |
| C→S | `dismiss_intent` | 律师忽略，清除 Pending Intent |
