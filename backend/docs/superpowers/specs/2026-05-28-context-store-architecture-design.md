# ContextStore 架构设计

## 概述

ContextStore 是 legal-agent 单会话系统中的集中状态存储，负责管理对话历史、用户画像和版本计数。本次设计明确其存在意义、职责边界、存储结构和读写语义，为后续 ProfileAgent 和 HeavyAgent 的协作提供稳定的状态层。

**方案选择**：经用户逐条确认（见下方决策清单）。

---

## 1. 设计决策总览

| # | 议题 | 方案 | 理由 |
|---|------|------|------|
| 1 | profile 是否允许重复 key | **允许**，保留完整时间线 | 法律场景中客户会纠正说法，历史轨迹有价值 |
| 2 | profile 归属 | **留在 ContextStore** | 跨 Agent 共享的业务状态，非 PA/Orchestrator 私有 |
| 3 | 写入机制 | **保留 queue + worker**，延迟生效 | 解耦 PA 的 LLM 延迟与 Orchestrator 主路径 |
| 4 | timestamp 语义 | **utterance 说话时间 `utt.t_start`** | 反映事实发生时间，不是系统解析时间 |
| 5 | 乱序处理 | **查询层排序** | PA 返回可能乱序，存储层保持 append，查询时按 timestamp 升序 |
| 6 | `_generation` stale check | **保留**，封装为公共方法 | 防止快速对话时返回过时建议 |
| 7 | 窗口接口 | **ContextStore 统一管理** | `get_recent_window(n)`，消费方不再自己切片 |
| 8 | `ProfileEntry` 扩展 | **增加 `category: str \| None = None`** | 为未来分类预留，成本为零 |
| 9 | `_utterances` 容量 | **保留全量，不截断** | 审计需求 + 单会话内存可控 |
| 10 | `_generation` 封装 | **`get_generation()` 公共方法** | 禁止 HeavyAgent 直接访问私有属性 |
| 11 | profile 查询排序 | **`get_profile()` 和 `get_profile_keys()` 按 timestamp 排序** | 消费方看到一致的时间线 |

---

## 2. 数据模型

### ProfileEntry（扩展后）

```python
@dataclass
class ProfileEntry:
    key: str
    value: str
    timestamp: datetime          # 用 utt.t_start，不是 datetime.now()
    source_utt_id: str
    confidence: float = 1.0
    category: str | None = None  # 新增：预留分类字段
```

### ContextStore 内部状态

```python
class ContextStore:
    _utterances: list[Utterance]     # 完整对话历史，不截断
    _profile: list[ProfileEntry]     # 时间序列画像，允许重复 key
    _profile_queue: asyncio.Queue    # profile 更新队列（保留）
    _worker_task: asyncio.Task | None
    _generation: int                 # 版本计数器，stale check 用
    _lock: asyncio.Lock              # 保护 _utterances 和 _generation
    _shutdown: bool
```

---

## 3. 接口设计

### 写入接口

| 方法 | 语义 | 锁/异步 |
|------|------|---------|
| `append_utterance(utt)` | 追加发言，原子递增 generation | `async with _lock` |
| `enqueue_profile_update(utt_id, entries)` | 将 profile entries 放入队列 | `await queue.put` |
| `start_profile_worker()` | 启动异步 worker（幂等） | `async` |
| `stop_profile_worker()` | 标记关闭 + cancel worker | `async` |

### 读取接口

| 方法 | 语义 | 排序 |
|------|------|------|
| `get_full_history()` | 返回全部 utterances 浅拷贝 | 物理顺序（append 顺序） |
| `get_recent_window(n=8)` | 返回最近 n 轮 utterances | 物理顺序 |
| `get_profile()` | 返回全部 profile 浅拷贝 | **按 timestamp 升序** |
| `get_profile_keys()` | 返回 key 列表（去重） | **按 timestamp 降序后去重，保留每个 key 的最新出现** |
| `get_generation()` | 返回当前 generation 编号 | — |

### 新增/修改的方法

- 新增 `get_generation()` — 替代直接访问 `_generation`
- 修改 `get_profile()` — 返回前按 `timestamp` 排序
- 修改 `get_profile_keys()` — 先按 `timestamp` 排序，再用 `dict.fromkeys` 去重

---

## 4. 数据流

### Utterance 写入流

```
STT → Utterance
  → Orchestrator.handle_utterance()
    → ctx.append_utterance(utt)  [加锁，generation++]
    → 并行：IR.classify() + PA.extract()
    → PA 返回 entries
      → Orchestrator 覆盖 entry.timestamp = utt.t_start
      → ctx.enqueue_profile_update(utt.id, entries)
        → _profile_queue.put()
          → _profile_worker 消费
            → _profile.append(entry)  [单线程，无需锁]
```

### Profile 读取流

```
HeavyAgent._make_get_context_tool()
  → ctx.get_profile()            [按 timestamp 排序]
    → get_user_context tool 输出 "=== 用户画像 ==="
  → ctx.get_recent_window(10)    [统一窗口接口]
    → get_user_context tool 输出 "=== 对话历史 ==="
```

---

## 5. 关键实现细节

### 5.1 Timestamp 覆盖逻辑

Orchestrator 在收到 PA 返回的 entries 后，必须把每个 entry 的 `timestamp` 覆盖为当前 `utt.t_start`，再 enqueue：

```python
for entry in pa_entries:
    entry.timestamp = utt.t_start
await self._ctx.enqueue_profile_update(utt.id, pa_entries)
```

### 5.2 Worker 写入顺序

Worker 是单线程 FIFO 消费，但 PA 返回可能乱序，导致 `_profile` 物理 append 顺序不等于时间顺序。**查询层排序是唯一的顺序保证来源。**

### 5.3 `get_profile_keys()` 去重语义

```python
def get_profile_keys(self) -> list[str]:
    sorted_profile = sorted(self._profile, key=lambda e: e.timestamp, reverse=True)
    return list(dict.fromkeys(e.key for e in sorted_profile))
```

按 `timestamp` 降序排列后去重，`dict.fromkeys` 保留每个 key 的**最新出现**。这个列表不代表"当前有效值"，只代表"出现过哪些 key"。

### 5.4 `_lock` 范围

`_lock` 只保护 `_utterances` 和 `_generation`（`append_utterance` 内）。`_profile` 的写入由单线程 worker 完成，无需锁。

---

## 6. 错误处理

| 场景 | 策略 |
|------|------|
| `_profile_worker` 消费单条失败 | 继续消费下一条（已有 `try/except`） |
| `stop_profile_worker` 时队列未清空 | 当前直接 cancel，可能丢失。用户接受此风险（延迟是小问题） |
| PA 返回乱序 | 查询层排序兜底，不影响业务 |
| `_utterances` 无限增长 | 单会话内存可控，不截断 |

---

## 7. 测试验证

### 单元测试

| 测试 | 验证点 |
|------|--------|
| `test_get_profile_sorted` | `get_profile()` 按 timestamp 升序返回 |
| `test_get_profile_keys_sorted` | `get_profile_keys()` 去重前按 timestamp 排序 |
| `test_get_generation` | `_generation` 封装为公共方法 |
| `test_get_recent_window` | 窗口大小 n 正确，返回最近 n 轮 |
| `test_profile_entry_category` | `ProfileEntry` 支持 `category=None` |
| `test_append_utterance_generation` | `append_utterance` 原子递增 generation |

### 集成测试

| 测试 | 验证点 |
|------|--------|
| `test_profile_timestamp_from_utt` | PA entries 的 timestamp 等于 `utt.t_start` |
| `test_heavy_agent_uses_window` | HeavyAgent 调用 `get_recent_window(10)` 而非切片 |

---

## 8. 不改的部分

- **queue + worker 保留**：不改为同步写入
- **PA 不在本次范围**：key 标准化、单句提取无上下文等 P0/P1 缺陷不处理
- **`_utterances` 不截断**：无上限，直到会话结束
- **stale check 保留**：`_generation` 机制不变，只加封装

---

## 9. 改动文件清单

| 文件 | 改动 |
|------|------|
| `src/agent/context_store.py` | 新增 `get_generation()`、改 `get_profile()` 排序、改 `get_profile_keys()` 排序、增加 `category` 字段 |
| `src/agent/heavy_agent.py` | `self._ctx._generation` → `get_generation()`、`get_full_history()[-10:]` → `get_recent_window(10)` |
| `src/agent/orchestrator.py` | PA entries timestamp 覆盖为 `utt.t_start` |
