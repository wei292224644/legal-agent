# 全链路实时 E2E 报告 — STT→Agent 稳定性与延迟

- **日期:** 2026-05-29
- **脚本:** `tests/e2e_full_pipeline.py`(镜像 `main.py` 生产接线,喂录好的完整对话音频)
- **音频:** `劳动仲裁对话_完整版.wav`,448s,16kHz mono,**1x 真实节奏**
- **产物:** `tests/runs/20260529-140236_full_pipeline/{events.jsonl,metrics.json}` + `runs/judgments_full_pipeline_20260529_*.jsonl`
- **链路:** 音频 → `stream_stt`(fsmn-vad 切句 + paraformer 转写 + cam++ 声纹) → `UtteranceBus(maxsize=10)` → `Orchestrator` → IR(千问)/PA(千问)/HA(DeepSeek)

---

## 一、稳定性 — ✅ 通过

| 指标 | 结果 | 判读 |
|---|---|---|
| utterance 产出 | 55 | — |
| **bus 丢弃** | **0** | 有界队列从未满,STT→agent 无背压丢数据 |
| **IR 调用 / utterance** | **55 / 55(差值 0)** | 每句都过了 agent,无漏处理 |
| PA 调用 | 26 | = 非律师句数(29 律师句按设计跳过 PA),一致 |
| speaker=None | 0 | 声纹链路接通,无降级告警 |
| 崩溃 / 异常 | 0 | 全程 exit 0 |

**结论:你最担心的"STT 吐出的数据能否被 agent 稳定识别处理"——答案是稳。** 7.5 分钟连续真实节奏下零丢失、零崩溃、零漏处理。

---

## 二、延迟 — 真实 STT ≈ 1.0s,agent 影响 ≈ 0(两个旧结论都是测量假象)✅

> **更正历程(两次纠错):** 初版说"agent 拖慢 7x"——错(是我并发占 CPU);二版说"5.8s 结构性 + enrollment +4.7s"——也错(是冷模型加载偏移)。下面是经埋点 + 产出 trace + 修复验证后的最终结论。

定向埋点(`tests/_instrument.py`,monkeypatch `asyncio.to_thread` 测排队/执行 + loop-lag 探针)+ 四次跑对照:

| 跑法(均 1x,同音频) | STT 产出延迟 avg | 说明 |
|---|---|---|
| baseline:STT+cam++,无 agent | 5.47s | 含冷模型加载偏移 |
| full:STT+cam++ **+ agent** | 5.63s | **vs baseline 仅 +0.16s** → agent 无影响 |
| 隔离:无 agent,关埋点 | 5.81s | 埋点开销 ≈ 0 |
| **预热模型后(修复测量bug)** | **1.03s** | **去掉冷加载偏移 = 真实延迟** |

**埋点分解(baseline,无竞争):**

| to_thread 环节 | 排队 queue | 纯执行 exec | 次数 |
|---|---|---|---|
| VAD | 0.1ms | 26ms | 4481 |
| ASR | 0ms | 761ms | 55 |
| cam++ | 0ms | 58ms | 55 |
| **loop-lag** | — | avg 1.0ms,阻塞占比 0.4% | — |

**三个嫌疑全部证伪:**
- **A 线程池排队** → queue 全 ~0ms,排除
- **B 事件循环阻塞** → loop-lag 1ms / 阻塞 0.4%,排除
- **C CPU 争用** → exec 在有/无 agent 下完全一致,排除
- **agent 影响** → full vs baseline 仅 +0.16s(噪声内),排除

### 真相:5.8s 是测量假象,真实 STT 延迟 ≈ 1.0s

产出路径 trace(`STT_TRACE=1`,在 `funasr_stream` 产出点拆解每句各阶段)定位:

| 阶段(enrollment ON) | 耗时 avg |
|---|---|
| ① 段检测滞后(音频结束→可产出) | 172ms |
| ② 等投机 ASR | 788ms |
| ③ cam++ await | 67ms |
| **④ generator 内部 yield 总延迟** | **1027ms** |
| consumer 实测(预热前) | 5647ms |

generator 内部从音频结束到 yield 只要 **1.0s**,但 consumer 收到是 5.6s——中间 **4.7s 是常量偏移**(consumer 延迟跨度只有 580ms,= 内部 1027ms±580ms + 固定 4686ms)。

**根因 = 冷启动模型加载被算进了每句延迟。** VAD/ASR 模型在 `stream_stt` 首次 pull 时才惰性 `_get_models()` 加载(直测冷启动 ~5–12s),而 e2e 的 `stream_start` 锚点打在 `async for` **之前**,把这一次性加载摊进了每一句的延迟。历史"无 enrollment 1.1s"是 pytest 里跑的——前序测试早把模型暖好了,所以没这偏移。**`enrollment 1.1 vs 5.8` 是红鲱鱼:不是 enrollment,是冷模型 vs 暖模型。**

**修复 + 验证:** e2e 在打 `stream_start` 前预热 VAD/ASR。修复后 consumer 实测 **1027ms**,与内部 trace(1027ms)分毫不差,4.7s 偏移消失。

**结论:真实稳态 STT 产出延迟 ≈ 1.0s(主要是 ASR 788ms),完全正常。** cam++ 仅 67ms,agent 仅 +0.16s,均可忽略。之前报告的"5.8s 结构性""agent 7x"两个结论**都是测量假象**(分别是冷启动 / 我自己并发占 CPU),已全部更正。

**影响:** 现场律师看到转写滞后 ≈ 1.0s + agent 反应 ≈ 2.5s,语音→建议 ≈ 3.5s。STT 延迟不是问题。

---

## 三、切句 — soft_cap 主导(54/55),跨说话人合并

- VAD_SILENCE_MS=400,SOFT_CAP_MS=8000。本段录音语速连续,8s 内罕有 ≥400ms 停顿,所以几乎全靠 8s 硬截断切句。
- 副作用 1:**切在词中** —— 例:`…你大概记了多少小` | `时有没有考勤记录…`("小时"被劈开)。
- 副作用 2:**一段里混了两个说话人** —— 例 `…有没有结清 没有 不仅是辞退补…`(律师问 + 客户答挤在一段)。
- **4 个 uncertain 全部是这种跨说话人段** —— cam++ 对混合声纹正确地返回 uncertain。这反过来印证了 agent 端 **uncertain→client 兜底**是对的(拿不准的本就是边界混音段)。
- **真正的根治** = speaker-aware split(在说话人切换处切段),即声纹测试里标注的 "Cycle 6c"。这才是你一直困扰的"人物分离不稳定"的病根,而不是阈值。

---

## 四、各 Agent 延迟

| Agent | 调用 | avg | p95 | max | 备注 |
|---|---|---|---|---|---|
| IR(意图) | 55 | 1.4s | 2.5s | 4.4s | max 偏高;计划换本地 BERT 可解 |
| PA(画像) | 26 | 1.0s | 2.2s | 2.5s | 健康;空返回 38%(都是提问句,合理) |
| HA quick(简单反馈) | 3 | 11.6s | 13.8s | 13.9s | DeepSeek+工具,慢;你说过可后续拆 |

- **端到端反应延迟**(STT 产出→推出建议):pending 卡片 ~1–2.4s;唯一 ready(compute_compensation 走 quick 分析)= 9.2s。
- 语音→建议全链路 ≈ STT 1.0s + 反应 ~2.5s ≈ 3.5s(pending 卡片);需深度分析的走确认后异步,不在关键路径。

---

## 五、画像质量 — 较好,多主体归因生效

29 条事实,**当事人/对方主体标签清晰**(如 离职原因:当事人"组织架构调整" vs 对方"经协商一致解除";加班费支付/拒付理由都正确归到对方)。说明上一轮 subject 改动在真实长对话里站得住。少量噪声(同 key 多值)源于跨说话人段污染,会随 §三 的 speaker-aware split 一并改善。

---

## 六、建议优先级

延迟已不是问题(STT ≈1.0s、agent 无影响)。剩下的真问题都在切句质量:

1. **(高)speaker-aware split** —— 在声纹切换处切段,根治跨说话人合并 + 大部分 uncertain + 词中截断。这是你一直困扰的"人物分离不稳定"的病根。
2. (中)soft_cap 词中截断 —— 8s 硬截断切在词中,可考虑在最近微停顿优先切;但优先级低于 split。
3. (中)IR 换本地 BERT —— 降 IR p95(2.5s)+ 去一个 LLM 依赖。
4. (低)HA quick 优化 —— 你已定调后续拆独立 agent。

> **延迟三连证伪(全有数据):**
> - agent 拖慢 → +0.16s(full vs baseline);队列排队 queue~0;loop 阻塞 lag 1ms;CPU 争用 exec 不变。
> - "5.8s" → 冷模型加载偏移(产出 trace:内部 1.0s vs consumer 5.6s = 固定 4.7s);预热后 consumer 1.03s == 内部,偏移消失。
> - 真实稳态 STT ≈ **1.0s**(ASR 788ms 为主),cam++ 67ms。
>
> **已验证稳定性:** bus 无丢弃、IR/PA 调用数一致(55/55、26/26)、speaker 无 None、uncertain→client 兜底命中真实边界段。
>
> **诊断工具(默认关,生产零开销):** `tests/_instrument.py`(to_thread 排队/执行 + loop-lag);env 开关 `INSTRUMENT=1`(埋点)/ `NO_AGENT=1`(纯STT baseline)/ `NO_ENROLL=1`(跳cam++)/ `STT_TRACE=1`(产出路径分阶段);`funasr_stream.py` 的 trace 同为 env-gated。`e2e_full_pipeline.py` 已修预热,STT 延迟测量不再含冷启动。
