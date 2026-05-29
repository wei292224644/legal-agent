# 实时会谈 Agent 路由架构重构 — 设计文档

**Date:** 2026-05-29
**Status:** 设计已收敛,待评审 → 实现计划
**起因:** IntentRouter 被业务裹挟,意图模型(计划换 BERT)的训练目标里混入了产品策略,难以独立训练与演进。

---

## 1. 背景与问题

当前链路:`Utterance → IntentRouter(Qwen, 判 severity + intent_type) → Orchestrator(硬路由) → HeavyAgent(被动执行)`。

`IntentResult` 在一个模型输出里塞了两类性质完全不同的东西:

- **语言事实**(只随说话内容变):意图语义、`law_domain`、`entities`。
- **产品策略**(随运营决策频繁变,与语言无关):`severity`(ignore/simple/complex)= 「何时打断律师、何时要确认」的产品哲学;`intent_type` 的枚举设计绑死了具体动作/skill。

后果:产品每改一次交互策略、每加一个 skill,就要重新标注 + 重训模型。**模型成了业务规则的人质。** 这违反 CLAUDE.md 第 5 条(判断给模型,确定型给代码)。

此外 IntentRouter 还越权替 Agent 做了「是否响应、响应多深、用什么能力」的判断——这些恰恰是需要全上下文的判断,而 IR 只看单句。

---

## 2. 设计目标 / 非目标

**目标**

1. 给 BERT 一个**干净、稳定、业务无关**的训练目标。
2. 把「判断」收归有全上下文的 Agent,把「机械」收归代码。
3. 解除「同一语义理解做两次」(IR 一遍 + HA 一遍)。
4. 不丢失重要内容(过滤不影响画像记录)。

**非目标 / 明确不动**

- BERT(IR 后继)保持**独立组件**,不与 PA / HA 合并。
- 不做「LLM 协调器 / Agno Team 动态委派」——YAGNI。
- 浅答的双模型成本优化:不在本次范围(见 §11)。

---

## 3. 架构总览

四个角色:三个判断者(BERT / PA / HA-child)+ 一个纯机械的连接层(代码 Orchestrator,零语义判断,故意不算 agent)。

```
                  每条 utterance(已带 speaker,已 append 进 context)
                                 │
            ┌────────────────────┴────────────────────┐  并行
            ▼                                          ▼
      ① BERT(本地 · 所有句 · 二分类)          ② PA(LLM · 仅 client 句 · 串行单写者)
         法律/需求相关? 要不要叫醒 HA           抽画像 → 写 memory/上下文(唯一写口)
            │ 要叫醒(只 gate spawn,不 gate PA)
            ▼
      代码 Orchestrator(纯管道,零判断)
         spawn 一个 HA-child run(并发)
            │
            ▼
      ③ HA-child(LLM · 并发多实例 · 对共享状态只读)
         自选 skill/tool、自判深浅
         简单 → 答完(run completed)→ 代码自动推
         复杂 → 踩 gated 工具 → run paused → HITL 等律师确认

      共享状态(一份):ContextStore(转写) + Agno memory(画像) + Agno db(HITL run 状态)
         写者唯一 = PA;所有 HA-child 只读
```

---

## 4. 组件契约

### 4.1 BERT(IntentRouter 后继)

- **性质:** 本地模型,独立,对**所有** utterance(含律师)都过一遍,轻量串行。
- **职责(唯一):** 二分类——这句话是否法律/需求相关、值不值得叫醒 HA。
- **明确不做:** 不分意图类型、不判复杂度、不做路由。
- **输出:** 一个布尔(放行 / 丢弃)。**不再输出 `severity`,不再输出绑死动作的 `intent_type` 枚举。**(语义标签等富输出本次不要——最省的训练目标。)
- **训练目标:** 标注者无需知道任何产品策略 / skill 列表,只凭「法律/需求相关性」即可一致标注 → 加 skill、改交互策略,模型权重不动。
- **只 gate spawn,不 gate PA**(见 §6 的画像兜底)。
- **注意盲区:** BERT 在**律师句**上的漏判没有兜底(PA 不跑律师句),所以训练数据要保证它对律师的「帮我查 X / 算 Y」类请求足够敏感。

### 4.2 ProfileAgent(PA)

- **性质:** LLM(Agno,Qwen),**串行单写者**,仅对 client 句抽取。
- **职责:** 抽取客户陈述的事实 → 写画像;以及上下文转写的写入。**是共享状态的唯一写口。**
- **明确不做:** 不 spawn child、不判断响应深浅、不做唤醒决策。
- **与 BERT 并行**:两者读同一句话,目的正交,互不 gate。
- **单写者的来由:** 并发 HA-child 同时写画像会竞态;写路径必须单一串行。这是 PA 作为独立组件最硬的理由。
- **实现取向:** 可用 Agno `MemoryManager`(同 db + 同 `user_id`/`session_id`)作为底层,使 PA 与 HA 共享同一份 memory。是否从结构化 `subject/key/value` 迁到 Agno 自然语言 memory,取决于前端画像面板是否需要结构化字段——**此点留待实现前确认,不在本设计强行决定。**

### 4.3 Orchestrator(代码,纯管道)

- **性质:** 纯代码,**零语义判断**。
- **职责:** spawn、HITL 暂停/恢复管道、超时、状态清理。
- **不做:** 不理解语义、不判复杂度、不预分类。它只对 Agno run 的落地状态(`completed` / `is_paused`)做反应。
- 详见 §5 控制流、§8 状态清理。

### 4.4 HeavyAgent child

- **性质:** LLM(Agno,DeepSeek),**并发多实例**,对共享状态(context + memory)**只读**。
- **职责:** 自己选 skill/tool、自己定响应深浅、决定要不要先问律师。
- **深浅 = 是否踩 gated 工具**(见 §7):简单问题直接答完(run completed);需要深析时调 `requires_confirmation` 的深度工具 → run paused → HITL。
- **明确不做:** 不写共享状态、不管自己的生命周期(spawn/销毁由代码)。
- **成本约束:** 贵的 skill / 多步深析必须放在 **gated 工具体之内**,而非默认挂在 agent 上——这样浅答不碰 skills、贵活儿确认后才烧。(对比现状 `HeavyAgent` 全程 `skills=_load_skills()` 挂着,需要改。)

---

## 5. 控制流

**定调:代码不判断,只对 run 状态做反应。** 「简单 vs 复杂」「要不要确认」合并为同一件事——run 是 `completed` 还是 `paused`,由 child 踩不踩 gated 工具决定。

```python
# Orchestrator,bus consumer 串行处理每条 utterance
generation = await ctx.append_utterance(utt)          # 串行写,单写者

bert_task = asyncio.create_task(bert.is_relevant(utt)) # 并行
pa_task   = asyncio.create_task(pa.extract(utt)) if utt.speaker == "client" else None

if pa_task:                                            # 画像兜底:不被 BERT gate
    entries = await pa_task
    await ctx.enqueue_profile_update(utt.id, entries) # 串行写口

if await bert_task:                                    # 唤醒只听 BERT
    asyncio.create_task(run_child(utt, generation))    # 并发 child
```

```python
async def run_child(utt, generation):
    agent = build_child_agent(db=DB, session_id=SID, user_id=UID)  # 共享 db/memory/context
    run = await asyncio.wait_for(agent.arun(prompt_for(utt)), timeout=RUN_TIMEOUT)

    if not run.is_paused:                              # 简单:答完了
        if ctx.get_generation() == generation:         # 没过期才推
            await emit(run.content, {"kind": "ready"})
        return

    # 复杂:踩了 gated 深度工具,挂起等律师
    req = run.active_requirements[0]
    request_id = new_id()
    pending[request_id] = (run.run_id, generation)
    await emit(None, {"kind": "pending", "request_id": request_id,
                      "preview": req.tool_execution.tool_args})  # tool_args = 给律师的预览
```

```python
async def confirm_analysis(request_id):
    run_id, generation = pending.pop(request_id, (None, None))
    if run_id is None:
        return
    if ctx.get_generation() != generation:             # 等确认期间对话走远 → 作废
        await abandon_run(run_id)
        return
    agent = build_child_agent(db=DB, session_id=SID, user_id=UID)
    for r in requirements_of(run_id):
        r.confirm()
    run = await agent.continue_run(run_id=run_id, requirements=...)  # 续跑同一 run,不重头理解
    await emit(run.content, {"kind": "ready", "request_id": request_id})

async def dismiss_pending(request_id):                 # 律师关卡片 = 不搞
    run_id, _ = pending.pop(request_id, (None, None))
    if run_id:
        await abandon_run(run_id)                      # reject + 清 db
```

三态映射:

| 旧 | 旧的判定者 | 新 | 新的判定者 |
|---|---|---|---|
| ignore | IR severity | BERT 丢弃,不 spawn | BERT |
| simple → `analyze_quick` | IR severity | child 答完(completed),自动推 | **child(未踩 gated)** |
| complex → `analyze`(要确认) | IR severity | child 踩 gated → paused → 确认后深析 | **child(踩了 gated)** |

---

## 6. 共享状态与并发约束(三条不能破的边界)

1. **写者唯一:** 共享状态(ContextStore 转写 + Agno memory 画像)只有 PA 串行写,所有 HA-child 只读 → 并发不竞态。
2. **判断在 ③、机械在代码:** child 决定干什么(含「深不深」);spawn/暂停/恢复/销毁是代码,零语义。
3. **BERT 只管「值不值得进来」,且不 gate PA:** 进来后的一切判断不归它。BERT 的「丢弃」只表示「别叫醒 HA」,绝不阻止 PA 记录。

**画像兜底(本次采纳的唯一兜底):** BERT 与 PA 并行,PA 不被 gate。即使 BERT 漏判一句重要的客户话,事实仍进画像;HA 下次被唤醒时读画像即可拿到。**漏判的代价是「晚一点响应」,不是「丢失」。**(「唤醒兜底/PA 反向触发 spawn」第二层不做,见 §11。)

- asyncio 并发(单事件循环,非多线程):ContextStore 的同步读相对事件循环原子,安全。
- child 并发读取的画像可能不含「刚说的这句」的事实(PA 尚未写完)——可接受,触发句原文已在 child 的 prompt 里。

---

## 7. HITL 机制(Agno 原生)

Agno 2.6.x 原生支持,核心:`@tool(requires_confirmation=True)` + `run.is_paused` + `continue_run`。

- 「要不要 pending」**不是独立决策**,就是「child 要不要调那个 gated 深度工具」。child 自主选工具的能力天然承载了「自主决定是否先问律师」。
- 暂停时 `requirement.tool_execution.tool_args`(如 `{topic, rationale}`)即给律师的预览;`requirement.confirm()/reject(reason)` 决定放行或否。
- `continue_run(run_id, requirements)` **续跑同一个 run**,Agent 推理状态从 db 重载 → 消除「重复理解」;贵活儿确认后才发生。

---

## 8. 状态清理(native HITL 的复杂度税)

挂起状态同时活在两处:**内存 `pending` 映射** 与 **Agno db(挂起 run + approvals 行)**。

- `confirm / reject / dismiss / 超时` **每条路径都必须两边都清**,漏一个就泄漏挂起 run。
- `abandon_run(run_id)` = `pending.pop` + 删 db 里对应 run/approval 行 + reject 未决 requirement。

两类超时,均由外部(代码)强制(child 卡死时无法可靠自毁):

- **在飞 run 卡死:** `asyncio.wait_for(agent.arun(...), timeout)` → 取消、丢弃。
- **挂起 run 等太久 / 对话走远:** confirm 前与推结果前查 `get_generation() == generation`(stale 作废);加 TTL 后台扫描清理长期无人确认的卡片。

---

## 9. 风险

- **SQLite 写锁:** Agno HITL 需 db;并发 child run 写 db + PA 写 memory,`SqliteDb` 单写者锁会撞。并发量上来后改 `PostgresDb`,或至少给 SQLite 开 WAL。
- **两处状态清理:** §8 的清理散落多条路径,易漏 → 泄漏挂起 run。需在实现与测试中重点覆盖。
- **skills 移入 gated 工具体:** 需改 `HeavyAgent` 现有「全程挂 skills」的写法,否则浅答也付 skill 成本。
- **BERT 律师侧无兜底:** 律师请求漏判无人补救,训练数据需保证律师侧敏感度。

---

## 10. 待清理(本次重构引入的废弃,按 CLAUDE.md「外科手术式」只清自己造成的)

- `IntentResult.severity` 字段及其所有消费点。
- `IntentResult.intent_type` 的多分类枚举(降为 BERT 二分类)。
- `Orchestrator.PendingRequest` + `confirm_analysis` 里「从零重跑 `_ha.analyze`」的逻辑(换成 `continue_run`)。
- `HeavyAgent.analyze_quick` / `analyze` 两方法 + Orchestrator 里按 severity 的 if-else 分支(合并为单一带 gated 工具的 run)。
- Orchestrator 中基于 `intent_type` 的硬路由分支。

---

## 11. 上线后调优(明确不在本次范围)

- **浅答成本优化(双模型):** 便宜模型打底浅答、判断要深析时升级到 DeepSeek+skills。先单模型落地,上线后按实测成本再定。**注意:此优化不能塞回 BERT(BERT 只过滤废话),只能在 child 侧做。**
- **唤醒兜底第二层:** 若实测发现 BERT 在 client 侧漏判偏多,再加「PA 发现该响应却无人响应 → 代码补迟到 spawn」(做成不阻塞快路径的迟到 spawn,且 spawn 决策仍归代码一处)。

---

## 12. 测试意图(验证意图,不只验证行为)

- **BERT 训练目标的稳定性:** 加一个新 skill 后,BERT 标注集/输出契约**不需要改动** → 若需改动则解耦失败。
- **画像兜底:** 一句「无需响应但含关键事实」的 client 话(如「我 2019 年入职」)→ 断言 BERT 丢弃(不 spawn)**且**画像被更新。
- **深浅由 child 涌现:** 简单问 → run completed、无 pending;复杂问 → run paused、产生带预览的 pending。
- **续跑不重头:** confirm 后走 `continue_run`,断言未对同一句重新发起理解(无第二次 base 推理)。
- **并发只读不竞态:** 多个 child 并发期间,画像写入仅来自 PA;child 不产生写。
- **清理无泄漏:** confirm/reject/dismiss/超时 四条路径后,`pending` 与 db 中均无残留挂起 run。
