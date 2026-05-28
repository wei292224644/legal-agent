# ProfileAgent 窗口上下文重构设计

## 概述

将 ProfileAgent 从"单句提取"改为"滑动窗口提取"。每次调用传入最近 6 轮对话 + 已知事实摘要，让 LLM 在上下文中理解指代、时间线和对话逻辑，解决当前 60%+ 事实遗漏的问题。

**方案选择**：方案 A（轻量 OpenAI client + 滑动窗口），经用户确认。

**调用频率**：高（每轮都调，修复 race condition 后不再丢失）。

---

## 1. 架构改动总览

### 改动的文件（4 个）

| 文件 | 改动 | 原因 |
|------|------|------|
| `src/agent/prompts.py` | 重写 `build_profile_prompt()` | 从"单句提取"改为"窗口+已知事实提取" |
| `src/agent/profile_agent.py` | 改 `extract()` 接口 + 解析逻辑 | 接收 history，解析同 key 合并 |
| `src/agent/context_store.py` | 修 race condition + 加 `get_profile_summary()` | 优雅关闭 + 给 prompt 提供已知事实摘要 |
| `src/agent/orchestrator.py` | 改 ProfileAgent 调用方式 | 传窗口、只在需要时调 |

### 不改的文件

- **不改 LLM client 框架**：继续用 `AsyncOpenAI`
- **不改输出格式**：继续返回 `list[ProfileEntry]`
- **不改 HeavyAgent/IntentRouter**：正交改动

### 新增常量

```python
PROFILE_WINDOW_SIZE = 6  # 最近 6 轮原始对话传入 prompt
```

为什么是 6：
- 能覆盖"追问-回答"链（律师问 3 句，客户答 3 句）
- token 可控（6 轮 ≈ 150-250 tokens）
- 测试数据显示，labor 31 轮剧本中 90% 的指代能在 6 轮内消解

---

## 2. Prompt 设计

### 新 prompt 结构

```
你是一个法律事实提取器，正在旁听律师与客户的咨询会谈。

## 最近 6 轮对话
[lawyer] 伤情怎么样，住院了吗？
[client] 右腿骨折，住院15天，医生建议休息三个月。
[lawyer] 医疗费花了多少？
[client] 目前3万多，后续还要拆钢板。
[client] 这种情况能赔多少？
[lawyer] 具体要看伤残鉴定等级…

## 已提取事实（key: 最新值）
- 伤情: 右腿骨折
- 住院天数: 15天
- 医嘱休息: 三个月
- 医疗费: 3万多

## 标准命名词表（优先使用）
事故类：事故责任、伤情、医疗费、住院天数、伤残等级、误工天数
劳动类：月薪、工龄、入职日期、合同类型、离职原因、赔偿金
通用：姓名、年龄、职业、收入、房产、车辆、存款、债务

## 提取规则
1. 只提取 [client] 陈述的事实，不提取律师的话
2. 当前 6 轮中若无新事实，输出空数组
3. key 优先从词表中选，没有合适的再自创（简洁中文）
4. value 必须是原文中的具体值，不能是疑问词
5. 同一 key 已有值时，如果新值补充/不同，也输出（追踪时间线）

只输出 JSON，不要任何解释：
{"entries": [{"key": "...", "value": "..."}]}
```

### 关键变化

| 维度 | 之前 | 之后 |
|------|------|------|
| 上下文 | 仅当前句（50 tokens） | 6 轮 + 已知事实（~300 tokens） |
| 去重依据 | 只有 key 名 | key + value，LLM 自行判断 |
| key 命名 | 自由命名 | 标准词表引导 |
| 同 key 多值 | 不支持（硬编码 confidence=0.9） | 允许输出，由 ContextStore 保留 |

---

## 3. ContextStore 修复与新增

### 修复 Race Condition

当前 `stop_profile_worker()` 直接 `cancel()`，队列里未消费的消息会丢失（probation 8 轮、traffic 10 轮 profile=0 的根因）。

```python
async def stop_profile_worker(self) -> None:
    self._shutdown = True
    if self._worker_task:
        await self._profile_queue.join()  # 等待队列清空
        self._worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._worker_task
        self._worker_task = None
```

### 新增 `get_profile_summary()`

给 prompt 提供"已知事实"摘要（key → 最新 value）：

```python
def get_profile_summary(self) -> dict[str, str]:
    """返回已知事实摘要（每个 key 取最新值）。"""
    summary = {}
    for entry in self._profile:
        summary[entry.key] = entry.value
    return summary
```

### 保留不变

- `_profile: list[ProfileEntry]` 结构不动（继续允许同 key 多值）
- `get_profile_keys()` 继续可用
- `enqueue_profile_update()` 接口不变

---

## 4. Orchestrator 调用策略 + ProfileAgent 接口

### Orchestrator 第 72-78 行改动

```python
# 之前
pa_task = asyncio.create_task(
    self._pa.extract(
        text=utt.text,
        speaker=utt.speaker,
        existing_keys=self._ctx.get_profile_keys(),
        utt_id=utt.id,
    )
)

# 之后
pa_task = asyncio.create_task(
    self._pa.extract(
        text=utt.text,
        speaker=utt.speaker,
        history=self._ctx.get_recent_window(n=PROFILE_WINDOW_SIZE),
        existing_profile=self._ctx.get_profile_summary(),
        utt_id=utt.id,
    )
)
```

### ProfileAgent.extract() 新签名

```python
async def extract(
    self,
    text: str,
    speaker: str | None,
    history: list[Utterance],           # 新增：最近 6 轮
    existing_profile: dict[str, str],   # 新增：已知事实摘要
    utt_id: str = "",
) -> list[ProfileEntry]:
```

### 保留不变

- **并行执行**：IR 和 PA 仍并发调，不串行
- **异步 worker**：提取结果仍走 `enqueue_profile_update` + `_profile_worker`
- **输出格式**：`list[ProfileEntry]` 不变
- **`_parse_response()`**：JSON 解析逻辑不变

---

## 5. 测试验证

### 成功标准

| 指标 | 当前（单句） | 目标（窗口） |
|------|-------------|-------------|
| probation 8 轮 profile 条目数 | 0（race condition） | >= 4 条 |
| traffic 10 轮 profile 条目数 | 0 | >= 5 条 |
| labor 31 轮 profile 条目数 | ~15 | >= 20 条（上下文减少遗漏） |
| 同 key 多值（如"伤情"） | 不存在 | 允许存在 |
| Key 标准化率 | ~60% | >= 85% |

### 验证方式

1. **跑现有 E2E 剧本**：`uv run python tests/e2e_multi_dialogue.py all`
2. **看 JSONL 输出**：检查 profile 提取的 key 名是否使用标准词表
3. **新增单元测试**：
   - `test_profile_window_context` — 传入窗口，验证 LLM 能看到指代消解
   - `test_profile_worker_graceful_shutdown` — 验证 race condition 修复
   - `test_profile_key_standardization` — 验证词表引导生效
