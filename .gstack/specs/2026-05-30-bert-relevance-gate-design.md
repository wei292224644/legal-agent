# BERT RelevanceGate 替换设计

## 背景

当前 `RelevanceGate` 使用 Qwen LLM（API 调用）做二分类判断，每条 utterance 都发一次网络请求，存在延迟和依赖外部服务的问题。训练好的本地 BERT 模型（`intent_router_bert_binary`，~400MB）已就绪，需要接入替换 LLM 调用。

## 目标

- 服务启动时将 BERT 模型加载到内存/显存
- `RelevanceGate.is_relevant()` 改为本地 BERT 推理
- 模型加载失败为**硬依赖**：阻止服务启动
- 调用方契约不变：返回值仍是 `bool`

## 方案

### 1. 模型加载

`relevance_gate.py` 内部封装加载逻辑，暴露 `load_relevance_model()` 函数。

```python
def load_relevance_model() -> None:
    """加载 BERT 模型到全局变量。失败抛异常。"""
    global _bert_model, _bert_tokenizer, _device
    ...
```

`main.py` 的 `_startup()` 中显式调用：

```python
from agent.relevance_gate import load_relevance_model

@app.on_event("startup")
async def _startup() -> None:
    load_relevance_model()  # 失败即抛异常，阻止启动
    ...
```

### 2. 模型路径

```
backend/__modles__/intent_router_bert_binary/
├── model.safetensors   # BERT 主体 (~400MB)
├── config.json         # BERT 配置
├── tokenizer.json      # Tokenizer
├── tokenizer_config.json
├── classifier.pt       # 分类头权重
└── config.json         # 分类头配置 (num_classes=2)
```

路径计算：以 `relevance_gate.py` 为基准，`Path(__file__).resolve().parent.parent.parent / "__modles__" / "intent_router_bert_binary"`。

### 3. RelevanceGate 实现

```python
class RelevanceGate:
    def __init__(self, threshold: float = 0.5):
        self.threshold = threshold

    async def is_relevant(self, utt: Utterance) -> bool:
        # BERT 推理是 CPU/GPU 密集型，用 to_thread 避免阻塞事件循环
        prob = await asyncio.to_thread(self._sync_predict, utt.text)
        return prob >= self.threshold

    def _sync_predict(self, text: str) -> float:
        # Tokenize -> forward -> softmax -> 返回 should_enter 概率
        ...
```

### 4. 错误处理

| 场景 | 行为 |
|---|---|
| 模型文件不存在 | `load_relevance_model()` 抛 `FileNotFoundError`，`_startup()` 失败 |
| 模型加载内存不足 | 抛 `RuntimeError`，`_startup()` 失败 |
| 运行时推理异常 | `is_relevant()` 内部 catch，返回 `False`（和现有 Qwen 抖动行为一致） |

### 5. 测试兼容性

`test_relevance_gate.py` 现有测试契约不变：
- 返回值仍是 `bool`
- 测试通过 mock `_sync_predict` 或 monkeypatch 全局模型即可

## 边界情况

- **显存 vs 内存**：有 CUDA 时自动上 GPU，无则 CPU。400MB 模型 CPU 推理延迟约 10-50ms，可接受。
- **并发安全**：`nn.Module` 的 `forward()` 在 eval 模式下是线程安全的（无参数更新），`to_thread` 并发调用安全。
- **tokenizer.json vs vocab.txt**：当前导出的是 `tokenizer.json`，`BertTokenizer.from_pretrained` 自动识别。
