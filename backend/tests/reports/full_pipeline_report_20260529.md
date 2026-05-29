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

## 二、头号问题 — STT 产出延迟 ~5.8s,**结构性,与 agent 无关** ⚠️

> **更正:** 本节初版结论是"agent 并发把 STT 拖慢 7x",**该结论错误**,已被定向埋点 + 同配置对照实验推翻。第一次跑测到的 7.7s 是当时本机被并发的分析脚本/grep 占了 CPU 所致,不是 agent。下面是修正后的、有埋点证据的结论。

定向埋点(`tests/_instrument.py`,monkeypatch `asyncio.to_thread` 测排队/执行 + loop-lag 探针)+ 四次跑对照:

| 跑法(均 1x,同音频) | STT 产出延迟 avg | 说明 |
|---|---|---|
| 历史 STT 单侧,**无 enrollment** | 1.1s | 不跑 cam++ |
| baseline:STT+cam++,无 agent,**带埋点** | 5.47s | — |
| full:STT+cam++ **+ agent**,带埋点 | 5.63s | **vs baseline 仅 +0.16s** |
| 隔离:STT+cam++,无 agent,**关埋点**(生产配置) | 5.81s | 埋点开销 ≈ 0 |

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

**真凶 = soft_cap 流式切句算法的结构性产出滞后。** 每句总计算量才 ~0.85s(26+761+58),但延迟 5.8s——**~4.9s 是算法"等"出来的,不是算出来的**(详见 §三:连续语音下要等 merged 段长过 8s 才切首段)。三个 agent 都是原生异步网络 IO,不抢 CPU、不阻塞 loop,所以对 STT 延迟几乎零影响。

**一个未解但可复现的点:** 无 enrollment 1.1s vs 有 enrollment 5.8s(各跑 2-3 次稳定),但 cam++ exec 只有 58ms,这 4.7s 差**不在 exec/queue/loop 里**,埋点抓不到。推测与 async generator pull-based 拉取 + cam++ inline `await` 的调度交互有关,需加产出路径 trace(记录"段进入 bounds → 真正 yield"的间隔)才能定位。**它直接决定生产真实 STT 延迟是 1.1s 还是 5.8s。**

**影响:** 现场律师看到转写比真实说话滞后 ~5.8s(生产配置),叠加 agent 反应 ~2.5s,语音→建议 ≈ 8s。这是 STT 切句算法 + cam++ 路径的代价,**与 agent 无关**——优化要往 STT 那边使劲,不是 agent。

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
- 注意:以上 agent 延迟本身已被 STT 的 7.7s 滞后"喂晚了"——真实墙钟链路是 7.7s(转写) + 反应。

---

## 五、画像质量 — 较好,多主体归因生效

29 条事实,**当事人/对方主体标签清晰**(如 离职原因:当事人"组织架构调整" vs 对方"经协商一致解除";加班费支付/拒付理由都正确归到对方)。说明上一轮 subject 改动在真实长对话里站得住。少量噪声(同 key 多值)源于跨说话人段污染,会随 §三 的 speaker-aware split 一并改善。

---

## 六、建议优先级

1. **(高)砍 STT 结构性产出滞后(~5.8s)** —— 这是头号延迟,**与 agent 无关,优化往 STT 使劲**。两条线索:(a) soft_cap 切首段要等 merged 段长过 8s,可改成"累计够 8s 立即在最近微停顿切"而非等整段;(b) 先钉死 enrollment 路径那 4.7s(见下)。
2. **(高/待定)钉死 enrollment 的 +4.7s** —— 无 enrollment 1.1s vs 有 5.8s,埋点抓不到,需产出路径 trace。决定生产真实延迟是 1.1s 还是 5.8s。
3. **(高)speaker-aware split** —— 在声纹切换处切段,根治跨说话人合并 + 大部分 uncertain + 词中截断。
4. (中)IR 换本地 BERT —— 降 IR 延迟 + 去一个 LLM 依赖。
5. (低)HA quick 优化 —— 你已定调后续拆独立 agent。

> **已用埋点证伪:** agent 拖慢(+0.16s)、线程池排队(queue~0)、loop 阻塞(lag 1ms)、CPU 争用(exec 不变)。
> **已验证稳定性:** bus 无丢弃、IR/PA 调用数一致、speaker 无 None、uncertain→client 兜底命中真实边界段。
> **未隔离:** enrollment 路径 +4.7s 的精确机制(需产出路径 trace)。
>
> 诊断埋点:`tests/_instrument.py` + `e2e_full_pipeline.py` 的 `INSTRUMENT=1` / `NO_AGENT=1` 开关(默认关,零开销)。
