# BERT 意图路由方案

**日期:** 2026-05-27
**状态:** 方案探讨

## 问题

当前 `analyze_fn()` 一次 Deepseek 调用混合了三个职责：事实提取、意图判断、法律分析。每次调用 3-5s，不管对话是否有法律需求都跑完整流程。

BERT 可以替代意图判断（语义匹配/分类），25ms 完成，但**无法替代事实提取**——事实提取本质是生成任务，仍需 LLM。

## 核心洞察

客户每句话大概率包含法律事实（"入职没签合同"、"加班不给钱"），纯粹的 `none`（无法律需求）占比可能很低。引入 BERT 的真正价值不是"跳过更多调用"，而是：

1. **即时分类：** 25ms 知道要做什么，不傻等 3s
2. **路由：** 不同意图走不同处理链路，prompt 更聚焦
3. **解耦事实提取和分析：** 事实每句提，分析攒够再触发

## 架构

```
observe(text, speaker)
  │
  ├─ speaker ≠ "客户" → return (0ms)
  │
  ├─ BERT intent classify (context[-5:] + current_text, 25ms)
  │    │
  │    ├─ none → return（无需法律介入）
  │    │
  │    ├─ update_fact → fire-and-forget:
  │    │     └─ LLM fact_extract（轻 prompt，只输出 key-value，~1-2s）
  │    │            └─ 追加到 user_profile
  │    │
  │    └─ legal_question → fire-and-forget:
  │          ├─ (可选) LLM fact_extract
  │          ├─ 判断 simple/complex
  │          │    ├─ simple → LLM simple_analysis → push 侧边栏
  │          │    └─ complex → push Intent Card → 律师确认 → Executor
  │          └─ (仅 simple 触发分析；complex 等确认)
  │
  └─ 批处理节流：攒够 N 条新事实 or 距上次分析 > T 秒 → 触发分析
```

## BERT 上下文处理

BERT 通过**拼接上文**解决上下文依赖，不需要维护状态：

```python
class IntentRouter:
    def build_input(self, recent_context: list, current_text: str) -> str:
        # BERT 最大 512 token，保留最近 5-8 轮对话
        dialogue = "\n".join(
            f"{r.speaker}: {r.text}" for r in recent_context[-5:]
        )
        return f"{dialogue}\n客户: {current_text}"

    def classify(self, context, text) -> str:
        input_text = self.build_input(context, text)
        embedding = self.model.encode(input_text)  # ~25ms
        scores = {name: cosine(embedding, intent_emb)
                  for name, intent_emb in self.intent_embeddings.items()}
        return max(scores, key=scores.get)
```

512 token 足够覆盖最近 5-8 轮对话（中文每轮约 30-60 token）。

## 意图定义

| 意图 | 描述（用于 Embedding 匹配） | 行为 |
|------|---------------------------|------|
| `none` | 日常问候、闲聊、与法律无关的话题 | 跳过 |
| `update_fact` | 包含法律相关的事实信息：入职日期、合同签订、工资、加班、社保、辞退、证据等 | LLM 提取事实 → 追加画像 |
| `simple_analysis` | 可直接引用法条回答的简单法律问题 | LLM 实时分析 → push 侧边栏 |
| `complex_analysis` | 涉及多方争议、需要深度法律分析、风险评估的复杂问题 | push Intent Card → 等确认 |

## LLM 调用拆分

### fact_extract（轻量，~1-2s）

短 prompt，只输出 key-value，不做法条引用：

```
从对话中提取法律相关事实，输出 JSON：
{"facts": [{"key": "...", "value": "..."}]}

对话：{dialogue}
```

### simple_analysis（~2-3s）

专注法条引用，输入包含事实摘要：

```
根据以下已知事实和问题，引用中国大陆现行法律作答：

事实：{profile_summary}
问题：{question}
```

### executor（~3-5s，仅 complex）

保持现有深度分析 prompt 不变。

## 选型

| 模型 | 大小 | 延迟 | 中文匹配 |
|------|------|------|----------|
| `BAAI/bge-large-zh-v1.5` | 326M | ~25ms | 最强 |
| `shibing624/text2vec-base-chinese` | 110M | ~15ms | 好 |
| `hfl/chinese-roberta-wwm-ext` | 110M | ~15ms | 好 |

推荐 `bge-large-zh`——语义匹配任务已验证效果好，326M 模型本地 CPU 推理 25ms 完全可接受。

## 实现路径

1. 安装 `sentence-transformers`，实现 `IntentRouter` 类
2. 实现 `FactExtractor`（轻量 LLM prompt）
3. 重构 `LegalAgent.observe()` 接入 IntentRouter
4. 加批处理逻辑：攒 N 条事实 or 间隔 > T 秒才触发分析
5. 跑性能测试对比延迟

## 与设计文档的关系

设计文档（`2026-05-27-agent-architecture-design.md`）定义的 Judge Agent 职责是"提取事实 + 判断是否需要介入"，通过 tools 调用路由。BERT 方案将判断部分从 LLM 移到 BERT embedding 匹配，实现同样的路由效果但更快。

事实提取仍保留 LLM 调用（`update_fact`），但 prompt 更轻量、聚焦单一任务。
