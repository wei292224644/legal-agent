# ADR 0002: 引入事件总线解耦 STT 与 Agent

**状态:** 已决定  
**日期:** 2026-05-29

## 背景

当前 `main.py` 通过 `asyncio.create_task(orch.handle_utterance(utt))` 直接耦合 STT 产出与 Agent 消费。这带来两个问题：

1. **职责越界**：WebSocket handler 不应该决定 Agent 的并发策略（每个 utterance 一个独立 task）。
2. **速率失衡**：STT 产出速度（律师说话快时每秒多个 utterance）可能远超 Agent 处理速度（HeavyAgent 调 deepseek-chat 需数秒），无界堆积会导致内存持续增长。

## 决策

引入会话级**事件总线**（`asyncio.Queue`）作为 STT 与 Agent 之间的统一调度层。

- `main.py` 只负责将 STT 产出的 `Utterance` 投递到 Queue：`queue.put(utt)`。
- `Orchestrator` 内部启动独立 consumer task，循环 `queue.get()`，自主决定处理节奏和并发策略。
- Queue 设**有界容量**（`maxsize=N`），满了之后新的 utterance 被丢弃，防止内存无限堆积。

## 原因

1. **解耦 producer 与 consumer**：STT 不需要知道谁在消费、怎么消费；Agent 不需要知道数据从哪来。
2. **Agent 自主管理并发**：IntentRouter + ProfileAgent 串行逐句处理（轻量，qwen3.5-flash 调用快）；HeavyAgent 内部自行维护并发池（重量，deepseek-chat 调用慢）。
3. **轻量**：单进程部署下，`asyncio.Queue` 无需引入外部中间件（Redis/RabbitMQ）。
4. **顺序可控**：前端按 `generation` 对 suggestion 排序展示，后端并发不影响用户体验。

## 权衡

| 放弃的方案 | 代价 |
|---|---|
| 直接调用（现状） | Agent 并发策略硬编码在 WebSocket handler 里，无法根据负载调整 |
| 无界 Queue | 律师连续说话、Agent 慢时内存无限增长 |
| Redis/RabbitMQ | 单进程部署下过度设计，增加运维复杂度 |
| Queue 满了阻塞 STT | 音频处理卡住，影响实时转录 |

**数据丢失风险**：Queue 满时丢弃 utterance，可能丢掉几句转写。法律会谈场景下，丢失零散转写比系统崩溃更可接受；关键内容通常会在后续对话中重复或展开。

## 边界

- 事件总线是**内存级、会话级**的，WebSocket 断开即销毁。
- 未来如需水平扩展（多进程/多实例），需替换为持久化消息队列（Redis Stream 等），届时本 ADR 需重新评估。
