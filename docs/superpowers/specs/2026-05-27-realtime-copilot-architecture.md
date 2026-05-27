# 实时法律会谈 Copilot — 三轨异步架构

**日期:** 2026-05-27
**状态:** 已确认
**取代:** `2026-05-27-agent-architecture-design.md`, `2026-05-27-bert-intent-router.md`

## 概述

为律师客户会谈现场设计的实时 copilot 后端。律师与客户对话时,系统旁听并:

1. 实时把对话转录为分轨字幕(律师/客户)
2. 在合适时机给律师推送建议(法条引用、合同模板、风险提示)

核心架构挑战是延迟:大模型响应需要 3-5 秒,但实时对话的容忍度是亚秒级。本设计的核心命题是 **不让 LLM 跑得更快,而是从用户感知路径上拆走 LLM 延迟**——通过三轨异步把"按 utterance 跳出的近实时字幕"和"可以异步的分析"分离,用占位卡片 + 流式填充 + 预取等手段让律师感觉不到等待。

## 问题

前两次架构尝试都在延迟上失败:

**多 Agent 编排**(见 `2026-05-27-agent-architecture-design.md`):Judge Agent + Simple Analysis Agent + Executor Agent 三层 Agno Agent,每次 observe 触发 3-5s 主路径延迟。即使内部全部 fire-and-forget,主调度 LLM 自身的延迟无法掩盖。

**BERT 意图分类**(见 `2026-05-27-bert-intent-router.md`):用 `bge-large-zh-v1.5` 做意图分类替代 Judge Agent。法律术语下分类精度不足(测试表明 simple/complex 区分不可靠),且专业细分仍依赖 LLM 二次判断,引入 BERT 反而增加了一层无用的复杂度。

**FunASR 内置 diarization**:`spk_model=cam++` 在 batch 模式做多说话人聚类,错误率高,会把同一个人切成多个 speaker 或把两个人合并。

## 设计原则

1. **STT 的 ASR 是唯一持续运行的实时管线**——VAD + 流式 ASR 始终在跑;但 transcript 事件按 utterance 为单位关闭后发出(只发 final,不发 partial),real-time 体感由"短 utterance 软切 + 占位卡片"补足,而不是靠流式 token 抢秒数。
2. **判断用 LLM,路由用代码**——不做 LLM 调度 LLM。意图分类是确定性任务,用单跳 LLM(非 Agent);执行型任务(查 + 思 + 写)才用 Agent。
3. **意图分类与重分析解耦**——轻量意图 ≤1s 触发占位卡片,重分析 3-5s 在卡片内流式填充。
4. **窗口由对话节奏驱动,不是固定时间**——VAD 沉默 ≥1.5s 关闭 utterance,累计说话 ≥8s 进入软切待机(下一个 ≥0.3s 微停顿处切)。
5. **预取一切可预取的**——意图识别一旦提到"劳动合同",立刻把劳动法 RAG / 模板拉到内存。
6. **建议幂等可取消**——同一窗口的重复请求按 content_hash 去重;新分析取消 in-flight 的旧分析。

## 架构

```
┌──────────────────────────────────────────────────────────────────┐
│  UI 层 (React,本阶段不实现,留作接口契约)                          │
│  ┌──────────────────────┐  ┌──────────────────────────────────┐  │
│  │ 近实时字幕区          │  │ Copilot 建议区(卡片流)            │  │
│  │ • 按 utterance 整句  │  │ • 占位卡片(200ms) → 流式填充      │  │
│  │ • speaker 异步回填   │  │ • simple:自动展开                 │  │
│  │   (灰→上色)         │  │ • complex:折叠"分析?"按钮         │  │
│  └──────────────────────┘  └──────────────────────────────────┘  │
└────────────────────────┬───────────────────────────┬─────────────┘
                         │ WS: transcript            │ WS: suggestion
                         ▼                           ▼
┌──────────────────────────────────────────────────────────────────┐
│  Orchestrator (FastAPI + asyncio)                                 │
│   • Utterance Buffer (id / content_hash / speaker)               │
│   • Window Manager (VAD 边界 + 30s 滑窗 + 触发器)                 │
│   • Dispatcher (去重 / 取消 / 优先级)                             │
└────┬───────────────┬──────────────────┬────────────────┬─────────┘
     │ Track 1       │ Track 2          │ Track 3a       │ Track 3b
     ▼               ▼                  ▼                ▼
┌─────────┐  ┌──────────────┐  ┌────────────────┐  ┌──────────────┐
│ 流式 STT │  │ 声纹分轨      │  │ Intent Router  │  │ Heavy Worker │
│          │  │              │  │ (裸 LLM 单跳)  │  │ (Agno Agent  │
│paraformer│  │ cam++ +      │  │                │  │  + skills)   │
│-zh-      │  │ 余弦匹配      │  │ 输出 JSON      │  │ 流式输出     │
│streaming │  │ 律师声纹      │  │                │  │              │
│+fsmn-vad │  │              │  │                │  │              │
│+ct-punc  │  │ 三态匹配     │  │                │  │              │
│utterance │  │ + uncertain  │  │                │  │              │
│-final    │  │ 1-2s 回填    │  │                │  │              │
│~2s 后发  │  │              │  │ 500-800ms      │  │ 3-5s 流式    │
└─────────┘  └──────────────┘  └────────────────┘  └──────────────┘
```

### 三轨的职责边界

| 轨道 | 延迟(speaker 停说话起算) | 触发 | 输出 | 用户体感 |
|------|------|------|------|----------|
| Track 1 STT | ~2s(1.5s VAD + ~500ms 处理) | utterance 关闭 | `transcript.final`(整句) | 字幕按 utterance 跳出,不是 token 流 |
| Track 2 分轨 | +1-2s | Track 1 输出后 | `transcript.speaker`(回填) | 灰色 → 上色 |
| Track 3a Intent | +500-800ms | Track 1 输出后 | 意图 JSON + 占位卡片 | 200ms 内占位卡片可见 |
| Track 3b Heavy | +3-5s | 意图触发 / 律师确认 | 流式建议 | 卡片内边写边显 |

## 组件

### 1. STT + 声纹分轨(全栈 FunASR)

整条音频管线只用 FunASR 生态,不引入 pyannote / silero / speechbrain。

**模型组合**:

| 模型 | 大小 | 角色 |
|------|------|------|
| `paraformer-zh-streaming` | 220M | 流式 ASR |
| `fsmn-vad` | 0.4M | VAD,识别 utterance 边界 |
| `cam++` | 7.2M | 说话人 embedding(**独立调用,不挂在 STT 链上**) |
| `ct-punc` | 290M | 标点恢复(对 final utterance 加标点) |

**两条独立加载路径**——这是和 FunASR 推荐用法的关键差异:

```python
# 路径 A:实时 STT(链式:VAD + 流式 ASR + 标点)
stt = AutoModel(
    model="paraformer-zh-streaming",
    vad_model="fsmn-vad",
    punc_model="ct-punc",
)
# 注意:不挂 spk_model——FunASR 自带的多说话人聚类正是要避开的痛点

# 路径 B:声纹 embedding(对关闭后的 utterance 音频单独调用)
embed_model = AutoModel(model="cam++")
embed = embed_model.generate(input=utterance_audio_pcm)
```

#### 1.1 Transcript 事件契约

**只发 final,不发 partial**。partial 会引入 UI 双状态(interim/final)和 Intent Router 触发去抖的复杂度,本架构不接受。

```json
// utterance 关闭时发出,文本稳定,带标点
{
  "type": "transcript.final",
  "utt_id": "u_42",
  "text": "我上周被公司突然辞退了,就一句话说'组织架构调整'。",
  "t_start": 0.5,
  "t_end": 4.3,
  "speaker": null
}

// utterance 关闭后 1-2s 内异步回填
{"type": "transcript.speaker", "utt_id": "u_42", "speaker": "client"}
```

`speaker` 字段共有 4 个状态(语义两两不同):

| 值 | 含义 |
|---|------|
| `null` | 初始态,声纹尚未算完(异步过程中) |
| `"lawyer"` | 终态:相似度 ≥ τ_high |
| `"client"` | 终态:相似度 ≤ τ_low |
| `"uncertain"` | 终态:算完了但拿不准(音频过短或落在双阈值之间) |

#### 1.2 Utterance 关闭策略(VAD 优先 + 软切兜底)

| 触发 | 行为 |
|------|------|
| `fsmn-vad` 检测沉默 ≥ 1.5s | 正常关闭(主路径,覆盖典型对话节奏的 ≥85% 场景) |
| 累计说话时长 ≥ 8s | 进入"软切待机":从**下一次**任意 ≥ 0.3s 微停顿处切 |

8s 的 cap 是律师视觉刷新周期的舒适上限(超此值副屏看起来"卡死")。**不硬切**——硬切在数字 / 法条编号中间("两万五" → "两万" + "五")会摧毁下游意图识别。脚本里 L19 / L65 那种 17-25s 的长独白靠软切处理。

#### 1.3 说话人判定(白名单 + 三态)

声纹注册一次性,产物全局单例:

```
backend/voiceprints/
  lawyer.npy           # cam++ embedding (float32)
  lawyer.meta.json     # 注册时间、注册音频时长、self-similarity 校验值
```

运行时对每个关闭的 utterance:

1. utterance 音频时长 < 1s(应答词:"嗯"、"对"、"好的") → **直接标 `uncertain`**,不调 cam++(节省推理 + 短音频 embedding 本就不稳)
2. 否则 cam++ 算 embedding,与律师 embedding 求余弦相似度 `s`:
   - `s ≥ τ_high` → `lawyer`
   - `s ≤ τ_low` → `client`
   - 中间 → `uncertain`(UI 显示灰色:"算了但拿不准")

阈值校准方法(架构定方法,具体数值由测试数据回归得到):
- `τ_high = self_similarity_min(律师注册音频内分段) - 0.05`
- `τ_low = 0.5`(余弦相似度"明显不像"的常用边界)

`backend/voiceprints/lawyer.npy` 缺失时:STT 管线仍正常启动,所有 speaker 落 `uncertain`,启动日志明确报错(不静默)。

#### 1.4 热词(Hotwords)— 领域分包

```
config/hotwords/
  劳动法.txt          # 一行一个词,可带权重:"竞业限制 20"
  合同法.txt          # 后续扩展
  ...
```

不上热词的具体损失(用脚本可验):"竞业限制" → "经业限制"、"代通知金" → "代通之金"、"N+1" 可能被翻成中文。这些会让下游 Intent Router 漏触发或 Heavy Worker RAG 召回为 0。

会谈开始前,律师在 UI(或 API)选案件大类,后端 STT 初始化时载入对应热词包。本期只做劳动法包。

#### 1.5 异步回填语义

utterance 关闭时立刻发 `transcript.final`(`speaker=null`);cam++ 完成后发 `transcript.speaker` 回填。两个事件共享 `utt_id`。字幕展示完全实时,颜色变化是"补充信息"而非"等待结果"。

### 2. Utterance Buffer 与 Window Manager

数据模型:

```python
@dataclass
class Utterance:
    id: str             # 稳定 ID(基于 t_start 的 hash)
    text: str           # final 文本,带标点(若启用 ct-punc)
    t_start: float
    t_end: float
    # 4 态:null=声纹尚未算完;lawyer/client=终态匹配;uncertain=算完但拿不准
    speaker: "lawyer" | "client" | "uncertain" | None
    content_hash: str   # sha1(text)[:12],用于去重
    closed_by: "vad" | "soft_cap"  # 关闭原因(诊断用)
```

Window Manager 维护一个 30 秒滑窗(utterance 列表),按以下规则触发分析:

- **轻触发**(Intent Router):每个 utterance 关闭时立即触发
- **重触发**(Heavy Worker)满足任一即触发:
  - Intent Router 输出 `severity = simple` 时立即触发
  - Intent Router 输出 `severity = complex` 时挂起,等律师确认
  - 累计 ≥3 个 utterance 未触发重分析
  - 距上次重分析 ≥12s
- **静默期短路**:窗口内说话时长 <3s(寒暄、应答词)不触发任何分析

### 3. Intent Router(单跳裸 LLM,不是 Agent)

**职责单一:输入 utterance → 输出结构化意图 JSON**。云 API 调用(DeepSeek-V3 / Qwen-Flash / Claude Haiku 任选低延迟模型),约 500-800ms。

输出契约:

```json
{
  "intent": "query_law" | "draft_clause" | "compute_compensation" | "summarize" | "record_only" | "ignore",
  "severity": "simple" | "complex",
  "slots": {
    "law_domain": "劳动法" | null,
    "contract_type": "劳动合同" | null,
    "entities": ["违约金", "竞业限制"],
    "parties": ["客户", "前雇主"]
  },
  "rationale": "客户描述竞业限制纠纷,需查劳动合同法第23、24条"
}
```

**意图语义**:

| intent | 语义 |
|--------|------|
| `query_law` | 需要引用具体法条 / 判例 |
| `draft_clause` | 需要起草或推荐合同条款 |
| `compute_compensation` | 需要按法律公式算赔偿 / 加班费 / 年假折算 |
| `summarize` | 律师在做阶段性总结,系统应给出诉求清单 / 关键事实摘要 |
| `record_only` | 关键信息打点(证据清单、SOP 步骤),不主动推送建议 |
| `ignore` | 寒暄、应答词、无信息量 |

**路由决策**(确定性代码,非 LLM):

| intent × severity | 处理 |
|-------------------|------|
| `simple + query_law` | 直查 RAG 法条全文,**不调 Heavy Worker** |
| `simple + draft_clause` | 直拉模板库,**不调 Heavy Worker** |
| `simple + compute_compensation` | 走确定性计算器(工龄 × 月薪等公式),**不调 LLM** |
| `complex + *` 或 `summarize` | UI 推折叠卡"分析?",律师点击后调 Heavy Worker |
| `record_only` | 仅打点摘要,不出建议卡片 |
| `ignore` | 丢弃 |

**为什么不是 Agent**:Intent Router 的工作是确定性分类,无需工具、无需多步推理。用 Agent 反而引入延迟和不确定性。这是和 Heavy Worker 最大的边界区别。

### 4. Heavy Worker(Agno Agent,带 skills + 多轮)

系统里**唯一**的 Agent,使用 Agno 框架。

**Skills**(按意图按需加载,不是每次全集):

| skill | 用途 |
|-------|------|
| `search_law` | 法条向量检索 + 全文回查 |
| `search_case` | 判例库检索 |
| `load_template` | 标准合同模板加载 |
| `draft_clause` | 条款起草 |
| `compare_clauses` | 条款对比 |
| `summarize_facts` | 对话事实归纳 |

**Skill 路由**:Intent Router 输出的 `intent` 决定本次 Agent 加载哪些 skill。例如 `query_law` 只加载 `search_law` + `search_case` + `summarize_facts`,不加载 `draft_clause`——既减少干扰也减少 LLM 上下文。

**多轮能力**:
- Agent 可在单次任务内自主多步推理(先查法条 → 再找判例 → 再总结)
- 跨任务保留**会话级记忆**:同一场会谈的历史 utterance + 已推送过的建议 + 律师标记的关注点都注入 Agent context,避免重复建议、支持"基于刚才那条再展开"这类追问

**编排约束**(保护"看似实时"的体感):

- **可取消**:每个任务带 `request_id`,新任务到达时旧任务 `asyncio.CancelledError` 沿 Agno 调用栈传播
- **去重**:同一窗口 `content_hash` 命中缓存直接返回
- **超时熔断**:单次执行硬上限 8s,超时则卡片显示"分析超时,点击重试"
- **Skill 调用预算**:单次任务内 skill 调用次数 ≤4,防止 Agent 自由发挥导致延迟失控

### 5. 预取层

Intent Router 一旦识别到 slot,异步把对应资源拉进内存缓存:

- `law_domain` → 该领域 top-N 高频条款 embedding
- `contract_type` → 标准模板
- `entities` → 关联判例摘要

律师真要看时,这层延迟为 0。命中失败回退到 Heavy Worker 实时查。

## 延迟隐藏("骗过用户")策略

延迟的对手不是"秒数",而是"律师下次看屏幕时屏幕是否有新东西"。律师不在和系统对话,他在和客户对话——系统是个"瞥一眼就有内容"的副屏。

| 手段 | 用户感知 |
|------|---------|
| 按 utterance 整句出字幕 + 软切 8s | "整句蹦出来,且长独白也不会卡死字幕区" |
| 占位卡片 | "系统懂我意图了" |
| 流式填充 | "系统在写答案,不是卡住" |
| 骨架屏 + shimmer | "进度条在动" |
| 预取命中 | "系统好快" |
| 异步说话人回填(灰 → 上色) | 用户根本没注意到延迟 |
| 自然停顿利用 | 用户没在等,在听对方说话 |
| 折叠复杂任务 | 不打扰对话 |

把建议更新频率匹配上对话节奏(10-15s 一次有意义更新),3-5s 的 LLM 延迟就完全在心理预期之内。

## 验收门(后端 5 道门)

| 门 | 覆盖范围 | 关键指标 |
|----|---------|---------|
| 门 1 STT 通 | Track 1 | 文本 CER ≤15%、utterance 关闭(VAD/软切触发)→ `transcript.final` 事件延迟 ≤500ms、长独白下 8s 软切生效 |
| 门 2 声纹分轨通 | Track 1+2 | `lawyer/client` 准确率 ≥95%(`uncertain` 不计入分母)、`uncertain` 占比 ≤15%、回填延迟 P95 ≤2s |
| 门 3 Intent Router 通 | Track 1+2+3a | 意图 Recall ≥80%、误报 ≤30%、P95 延迟 ≤1s |
| 门 4 Heavy Worker 通 | 完整管线 | 首字 ≤1.5s、总耗时 P95 ≤6s、人工评分 ≥4/5 |
| 门 5 端到端时间线对齐 | + 预取 | 律师说话时屏幕 1s 内能看到上一段的建议 |

门 5 通过后才允许启动前端开发。

## 测试数据

后端验证全部基于真实劳动仲裁咨询场景:

| 用途 | 路径 |
|------|------|
| 完整双人对话音频(7.5 分钟,16kHz mono PCM) | `~/Library/.../测试数据/audio/劳动仲裁对话_完整版.wav` |
| 对话脚本 ground truth(标了"律师/客户") | `~/Library/.../测试数据/劳动仲裁对话脚本_角色话版.md` |
| 律师声纹注册音频(24kHz MP3,7.7s) | `~/Library/.../测试数据/audio/律师声纹注册.wav` |

脚本里 ground truth 意图触发点(用于 Intent Router 验收):

- L7 "组织架构调整 / 协商一致解除" → `query_law`
- L19 工龄 + N+1 计算 → `compute_compensation`
- L37 "放弃一切追诉权利" 条款 → `query_law`
- L39 "违法解除 → 2N" → `query_law`
- L51-53 律师证据清单 → `record_only`
- L65 加班费公式 → `compute_compensation`
- L81 总诉求汇总 → `summarize`
- L91 资料整理 SOP → `record_only`

## 范围之外

- **前端**:本架构定义事件流契约(transcript / intent / suggestion 三条 JSONL),前端 React 开发推迟到门 5 之后
- **多语言**:仅普通话,粤语/英文不支持
- **多人会谈**:仅二人(律师 + 一个客户),三人以上不支持
- **本地推理**:LLM 仅云端 API(DeepSeek / Qwen / Claude)。STT / VAD / 声纹本地推理(FunASR 模型)
- **历史会谈跨会话学习**:本期仅会话内记忆,不做跨会话个性化

## 与既有 spec 的关系

- **取代** `2026-05-27-agent-architecture-design.md`(多 Agent 主调度方案,延迟失败)
- **取代** `2026-05-27-bert-intent-router.md`(BERT 意图分类方案,精度失败)
- 当前 spec 的 Heavy Worker(Agno Agent)是原 Executor Agent 的演化:保留"按 skill 工具集思考"的能力,但去掉了主调度 LLM 这一跳
- 当前 spec 的 Intent Router 概念上对应原 Judge Agent 的"判断"职责,实现上是裸 LLM 调用而非 Agent
