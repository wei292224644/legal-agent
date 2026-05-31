# 律师 utterance 触发的快答补充

## 背景与问题

当前系统在律师与当事人的会谈中只关注**当事人话语**：

- `orchestrator.py:161` 显式跳过 `speaker == "lawyer"` 的 ProfileAgent 提取（设计上画像只针对当事人，这条约束是对的）。
- HeavyAgent 的系统提示（`prompts.py:118-137`）只写"旁听律师与客户、给律师快答"，并未对"输入是律师自己说的话"作出差异化指令。

这造成一个产品缺口：**律师说错话、漏问关键事实、给的建议不全面时，系统没有任何机制提示律师**。律师本身的话术质量同样影响会谈结果，但当前 AI 辅助完全不覆盖这块。

技术现状的额外暴露：

- RelevanceGate（`relevance_gate.py:1-104`）实际上**对所有 speaker 都跑** gate 判定，gate=true 时也会触发 HeavyAgent。但 BERT 训练数据几乎肯定是当事人话，对律师句的判定分布未知；同时 HeavyAgent prompt 没有针对"输入来自律师"的分支，模型只能按既有口径对律师"说话"，体验混乱。
- `events.py:21-26` 刚契约化的 `InsightReady` 没有携带"本条快答因谁的话而起"的信息，前端无法区分。
- `models.py:88-90` 的 `Suggestion.source` 字段语义是 `'direct' | 'gated'`（快答 vs 深析），**不是** lawyer/client，必须新加字段，不能复用。

## 目标

- 律师 utterance 也能触发快答，给律师**关于自己刚说那句话**的实时补充。
- 三种补充：**纠错**（法条/数字/事实硬错）、**补全**（漏问/漏覆盖的关键点）、**换角度**（策略/法律路径提示）。
- 与当事人快答同流展示，前端以**颜色/样式**区分两类卡片（不依赖文字标签）。
- 当事人主路（PA 写画像、深析提议、确认/忽略/超时）行为 100% 保留，零回归。

## 非目标

- ❌ 律师快答不专门走深析路径（prompt 软约束"lawyer trigger 时不要调 deep_analysis"；违反时不兜底，正常 paused 流程走通）。
- ❌ ProfileAgent 仍不提取律师话（`prompts.py:70` 硬约束保留）。
- ❌ 不做"会谈后回顾报告"、不做沟通口径建议、不做律师工作画像。
- ❌ 不重训 BERT；RelevanceGate 直接复用现有 0.5 阈值，对律师句不准是已知技术债，未来再换 lawyer 专用模型。
- ❌ 不引入律师快答的去重、节流、合并窗口（MVP 不预防性加复杂度）。
- ❌ 不做向后兼容；`Suggestion` 表 drop + recreate，旧数据直接抛弃。

## 架构决策

### 单 HeavyAgent + role-aware prompt（方案 D）

不开第二个 HeavyAgent 实例。原因：

1. 对话本质是配对的（当事人 turn ↔ 律师 turn）。双 ha 各看各的 trigger，无法在一次推理里联动判断"律师 turn 是否充分回应了客户 turn"，输出端容易冗余/打架。
2. 单 ha 在同一次推理里同时看到双方 turn + 完整 history + profile，天然满足配对性。
3. 未来要扩"律师工作分析"维度时，只需 prompt 加分支，不用合并架构。

### 工具集统一

不为律师 trigger 物理禁用 `deep_analysis` 工具。`prompts.py` 系统提示里写软约束："trigger_speaker=lawyer 时不要调 deep_analysis"。

实测违反率高再升级到运行时启停。当前选择"违反时不兜底"——律师 trigger 触发 paused，照常 emit `AnalysisProposed`、进 `_pending`、走 confirm/dismiss 流程。Orchestrator 一行不动。

### emit 走 typed event 路径

新功能从一开始就走最新的 typed event 通道（`events.py`），不沿用 dict + suggestion_callback 的旧路径。`InsightReady` 加 `trigger_speaker` 必填字段。

## 数据流

```
handle_utterance(utt):
    append_utterance(utt)                          # 现状
    gate_task    = safe_gate(utt)                  # 现状（lawyer 也过 gate）
    pa_task      = (speaker != "lawyer") ? extract : None  # 现状保留
    await pa_task → enqueue_profile_update         # 现状
    if await gate_task:
        spawn _run_child(utt, generation)          # 现状
            └─ ha.arun(utt)                        # 单实例
                 └─ build_child_user_prompt 已传 trigger_speaker
                 └─ system prompt 内部按 trigger_speaker 分流
                 └─ 输出 → InsightReady(trigger_speaker=utt.speaker)
                          或 AnalysisProposed（违反软约束时）
```

`_run_child` 中除了把 `utt.speaker` 透传到 emit 与 repo，无其他逻辑变更。

## 改动清单

### prompts.py

`get_child_system_prompt()` 末尾追加分支段（原"两种工作方式 / 工具 / 风格"完全不动）：

```
# 触发分流
看 user 消息开头的 trigger_speaker：

- trigger_speaker = client：按上述"快答 / 深析"两种工作方式行事。
- trigger_speaker = lawyer：切换为「对律师本人的补充」。
  - 只做三类输出：
    1. 纠错：律师引的法条编号、数字、事实硬错时立即指出"刚说的 XX 应为 YY"
    2. 补全：律师转向下个话题但有关键事实没问到/没强调时提示"还可以追问 X / 注意 Y"
    3. 换角度：律师给当事人建议时提示"也可考虑 Z 路径"
  - 不调 deep_analysis（律师自己刚说的话不适合让他停下来读结构化分析）
  - 口径：对律师直说，"你刚才说的..."、"建议补一句..."；不评论律师沟通技巧、不点评用词
  - 没有要补充的就沉默（沉默原则同样适用）
```

同时确认 `build_child_user_prompt` 是否真的把 `trigger_speaker` 渲染进 prompt 文本（不只是参数没用上）。

### events.py

```python
class InsightReady(BaseModel):
    type: Literal["insight.ready"] = "insight.ready"
    id: str
    utt_id: str
    text: str
    trigger_speaker: Literal["client", "lawyer"]  # 必填，无默认值
```

字段命名选 `trigger_speaker` 而非 `source`，理由：`Suggestion.source` 在 DB 层已用作 `direct/gated` 语义，复用会撞语义。`trigger_speaker` 与 `Utterance.speaker` 命名对齐。

### db/models.py

`Suggestion` 表加列：

```python
trigger_speaker: Mapped[str] = mapped_column(String, nullable=False)
# 'client' | 'lawyer'，表示触发本条快答的 utterance 说话人
```

### alembic 迁移

迁移文件直接 `drop_table('suggestions')` + `create_table(...)` 新结构。不写 backfill。旧数据全部抛弃（用户授权）。

### repositories/suggestions.py

`insert_direct` / `upsert_pending` 签名加 `trigger_speaker: str`，必填。`upsert_ready` 不加（深析续跑结果时调用，trigger_speaker 已在 pending 行确定）。

### agent/orchestrator.py

- `_RepoWriter` protocol 的 `insert_direct` / `upsert_pending` 同步加参数。
- `_run_child` 中 emit 与 repo 调用都带 `trigger_speaker=utt.speaker`（`utt.speaker` 此处已归一为 `lawyer` 或 `client`，见 `orchestrator.py:151-154`）。

### main.py

`_DbRepoWriter.insert_direct` / `upsert_pending` 转发新参数到 `SuggestionRepository`。

### frontend

- `frontend/src/types/index.ts` 加 `trigger_speaker: 'client' | 'lawyer'`
- 洞察卡片组件按 `trigger_speaker` 渲染不同颜色/样式（具体视觉由 v3 设计稿决定，本 spec 只要求"视觉可区分"）
- `/history` 接口前端解析自然带 trigger_speaker，会话恢复时复用同一卡片渲染逻辑

## 错误处理与降级

| 边界场景 | MVP 处理 | 升级触发条件 |
|---|---|---|
| LLM 违反 lawyer 软约束调 deep_analysis | 不额外处理，正常走 paused 流程 | 实测违反率高且律师反感 → 物理禁用工具 |
| BERT gate 对 lawyer 不准 | 沿用 0.5 阈值 + log 决策 | 实测触发率严重偏离预期 → 降阈值或重训 |
| lawyer 输出污染 client history（Agno session 共享） | 不处理，依赖 trigger_speaker 区分 | 实测客户主路输出对客户说"你刚才说..." → 加 prompt 校正 |
| generation stale | 沿用现有逻辑（直接丢弃，`orchestrator.py:242-243`） | 不变 |
| 重复快答（同主题 30s 内多次触发） | 不去重 | 实测重复严重 → 加滑动窗口语义指纹 cache |
| VAD 切句导致半句触发 | 不处理 | 实测半句触发占比 > 20% → 加 800ms 合并窗口 |

核心原则：MVP 不预防性加复杂度，所有兜底都对应"实测发现 X → 再做 Y"的明确触发条件。

## 测试策略

### 单元

- `test_child_system_prompt_contains_lawyer_branch`：断言系统 prompt 包含 lawyer 分支段
- `test_child_user_prompt_renders_trigger_speaker`：断言 prompt 文本含 "lawyer" 标识
- `test_insight_ready_requires_trigger_speaker`：缺字段抛 `ValidationError`
- `test_insight_ready_rejects_invalid_speaker`：非 client/lawyer 抛 `ValidationError`
- `test_insert_direct_stores_trigger_speaker_lawyer`：repo 插入后字段值正确
- `test_insert_direct_requires_trigger_speaker`：缺参抛 TypeError

### 集成（扩展 `tests/agent/test_orchestrator_emitter.py`）

- `test_lawyer_trigger_direct_insight_emits_with_lawyer_speaker`：lawyer utterance → emit `InsightReady(trigger_speaker="lawyer")` + repo 带 lawyer + PA 未被调用
- `test_lawyer_trigger_paused_still_goes_through`：lawyer 触发 + HA paused → 正常 emit `AnalysisProposed` + 进 `_pending` + confirm 流程能走完（守护"不特殊处理"决定）
- `test_lawyer_utterance_skips_profile_agent`：显式断言 PA.extract 在 lawyer utterance 时不被调用

### 端到端（`@pytest.mark.slow`）

`tests/e2e/test_lawyer_quickreply_e2e.py` 三场景：

1. 纠错：构造错的法条编号，断言输出含"应为"或正确条号
2. 补全：构造律师跳过情绪表达的对话，断言输出指出"未回应情绪"或"建议先共情"
3. 换角度：构造律师给单一路径建议，断言输出含"也可考虑"或类似的策略另解

判定用关键词集合 + 长度阈值 + 称呼检查，不用字符串等值。

### 前端

- 单元测试断言 `trigger_speaker='lawyer'` 时容器有差异化 class
- 浏览器手测：在同一会话内同时产生 client / lawyer 两种 trigger 的卡片，肉眼可一眼区分

### 不做的测试

- 不测 BERT gate 对 lawyer 句的判定准确率（已知不准，无意义）
- 不测 LLM 在 lawyer trigger 下的违反率（靠生产观测）
- 不补充 ProfileAgent 测试（未改动，原测试守住）

## 验收标准

- **AC-1**：律师说出"根据《劳动合同法》第 86 条，加班费按 1.5 倍"（编号错），系统 ≤ 5 秒内弹出含"应为 XX 条"或"刚说的法条编号有误"语义的卡片
- **AC-2**：当事人说"我老公被警察带走了，我快崩溃了"，律师下一句直接问"哪个派出所"，系统 ≤ 5 秒内弹出含"未回应情绪"或"建议先共情"语义的卡片
- **AC-3**：当事人触发的快答与律师触发的快答视觉上明显不同（颜色/样式可区分，非技术用户一眼能辨）
- **AC-4**：律师快答从不导致 `ProfileEntry` 表新增行（lawyer utterance 不入画像硬约束守住）
- **AC-5**：会话断开重连后，`/history` 接口返回包含本会话所有 lawyer trigger 快答，`trigger_speaker` 字段值为 "lawyer"
- **AC-6**：当事人主路所有现有功能行为零变化（现有测试套全绿）
- **AC-7**：律师触发的 utterance 若 HeavyAgent 调了 `deep_analysis`，弹出的"可分析意图"卡片与现有 client trigger 的卡片完全一致（确认"不特殊处理"决定）

## 实施顺序

| Step | 内容 | 依赖 |
|---|---|---|
| 1 | events.py 加 `trigger_speaker` 必填 + 前端 types 同步 | — |
| 2 | models.py 加列 + alembic drop+recreate + repo 加参 | — |
| 3 | Orchestrator emit 接线 + main.py `_DbRepoWriter` 转发 | 1, 2 |
| 4 | prompts.py 加 lawyer 分支段 + 渲染验证 | 3 |
| 5 | 前端洞察卡片按 trigger_speaker 渲染差异化样式 | 1 |
| 6 | /history 接口验证 + 会话恢复手测 | 全部 |

Step 4 与 Step 5 可在 3 之后并行。

## 已接受的技术债

| # | 项 | 升级条件 |
|---|---|---|
| TD-1 | RelevanceGate 对 lawyer 句不准 | 一周观察期触发率 < 5% 或 > 60% |
| TD-2 | LLM 可能违反 lawyer 软约束 | 一周观察期违反率 > 10% |
| TD-3 | lawyer 输出进 Agno history 可能污染 client 推理 | 实测客户主路对客户说"你刚才说..." |
| TD-4 | 同主题快答可能重复 | 抽样 30s 内同语义重复 ≥ 2 次 |
| TD-5 | VAD 切句导致半句触发 | 实测半句触发占比 > 20% |

## 与其他 feature 的关系

- **001-frontend-v3-redesign**：本 feature 的前端改动（卡片样式区分）应作为 v3 的一个补丁项加入 `specs/001-frontend-v3-redesign/tasks.md`，不另起前端 spec 分支。
- **typed-ws-events**（commit `eb3f363`）：本 feature 是事件契约首次扩展，`InsightReady.trigger_speaker` 字段必须前后端类型同步。
- **profile-agent-window-context**：本 feature 不动 PA 任何行为。

## 上线后观察期（1 周）

观察以下指标，决定 TD-1 ~ TD-5 是否需要升级：

- 律师 trigger 触发率（gate=true 占律师 utterance 数比例）
- 律师 trigger 中 LLM 违反软约束调 deep_analysis 的比例
- 律师快答中"自然语言相似"重复对数
- 律师手动反馈（如果产品有反馈通道）

期望基线：律师 trigger 每会话每分钟 5~15 次（基于"律师说话频率 × gate 命中率"的粗估）。
