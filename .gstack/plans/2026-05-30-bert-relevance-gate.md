# BERT RelevanceGate 替换实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `RelevanceGate` 从 Qwen LLM 调用替换为本地 BERT 模型推理，服务启动时预加载模型。

**Architecture:** `relevance_gate.py` 内封装模型加载与推理逻辑，暴露 `load_relevance_model()` 供 `main.py` startup 调用。`RelevanceGate.is_relevant()` 保持 `async` 接口，内部用 `asyncio.to_thread` 包装同步 BERT 前向推理。模型路径硬编码为 `backend/__modles__/intent_router_bert_binary/`。

**Tech Stack:** PyTorch, transformers (BertTokenizer + BertModel), FastAPI startup/shutdown

---

### Task 1: 重构 relevance_gate.py — BERT 模型加载与推理

**Files:**
- Modify: `backend/src/agent/relevance_gate.py`
- Test: `backend/tests/test_relevance_gate.py`

**背景:** 当前 `RelevanceGate` 用 Qwen API 做二分类。改为本地 BERT 后，构造函数不再需要 `client`/`model` 参数，但需要全局模型实例。

**注意:** `RelevanceGate.__init__` 当前签名是 `(client=None, model=None)`。Orchestrator 多处用 `gate or RelevanceGate()` 创建实例。为保持向后兼容，构造函数保留可选参数但不再使用。

- [ ] **Step 1: 写测试 — 验证 BERT 推理返回 bool 且阈值正确**

```python
# backend/tests/test_relevance_gate.py
import pytest
from unittest.mock import MagicMock, patch

from agent.relevance_gate import RelevanceGate
from models.utterance import Utterance


def _utt(text: str, speaker: str) -> Utterance:
    return Utterance(id="u_x", text=text, speaker=speaker, t_start=0.0, t_end=1.0)


@pytest.mark.asyncio
async def test_bert_relevance_true():
    """模拟 should_enter 概率 0.9，超过阈值 0.5，返回 True。"""
    gate = RelevanceGate()
    with patch.object(gate, "_sync_predict", return_value=0.9):
        assert await gate.is_relevant(_utt("违法解除赔多少？", "client")) is True


@pytest.mark.asyncio
async def test_bert_relevance_false():
    """模拟 should_enter 概率 0.1，低于阈值 0.5，返回 False。"""
    gate = RelevanceGate()
    with patch.object(gate, "_sync_predict", return_value=0.1):
        assert await gate.is_relevant(_utt("律师你好", "client")) is False


@pytest.mark.asyncio
async def test_bert_relevance_threshold_boundary():
    """阈值边界：刚好 0.5 返回 True。"""
    gate = RelevanceGate()
    with patch.object(gate, "_sync_predict", return_value=0.5):
        assert await gate.is_relevant(_utt("某个边界文本", "client")) is True


@pytest.mark.asyncio
async def test_bert_relevance_exception_defaults_false():
    """BERT 推理异常时按 False 处理，和现有 Qwen 抖动行为一致。"""
    gate = RelevanceGate()
    with patch.object(gate, "_sync_predict", side_effect=RuntimeError("mock error")):
        assert await gate.is_relevant(_utt("...", "client")) is False


@pytest.mark.asyncio
async def test_gate_contract_no_severity_no_intent_type():
    """红线契约：gate 返回值仍是 bool。"""
    gate = RelevanceGate()
    with patch.object(gate, "_sync_predict", return_value=0.9):
        result = await gate.is_relevant(_utt("劳动法第87条怎么说", "client"))
    assert isinstance(result, bool)
    assert not hasattr(result, "severity")
    assert not hasattr(result, "intent_type")
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
cd backend && uv run pytest tests/test_relevance_gate.py -v
```

Expected: 4 个新测试 FAIL（`AttributeError: 'RelevanceGate' object has no attribute '_sync_predict'`），原有 4 个测试也 FAIL（`RelevanceGate` 构造不再要求 client）。

- [ ] **Step 3: 实现 BERT 版 RelevanceGate**

```python
# backend/src/agent/relevance_gate.py
"""RelevanceGate — 二分类相关性闸门。

设计：接口只输出 bool，不出 severity、不出 intent_type。当前实现走本地 BERT，
服务启动时通过 load_relevance_model() 预加载模型。
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import torch
import torch.nn as nn
from transformers import BertModel, BertTokenizer

from models.utterance import Utterance

logger = logging.getLogger(__name__)

# 模型目录：以本文件为基准，向上三级到 backend/，再进 __modles__/
_MODEL_DIR = Path(__file__).resolve().parent.parent.parent / "__modles__" / "intent_router_bert_binary"
_MAX_LEN = 64

_bert_model: BertModel | None = None
_classifier: nn.Linear | None = None
_tokenizer: BertTokenizer | None = None
_device: torch.device | None = None


def load_relevance_model() -> None:
    """加载 BERT 模型到全局变量。失败抛异常，阻止服务启动。"""
    global _bert_model, _classifier, _tokenizer, _device

    if _bert_model is not None:
        return  # 已加载，幂等

    if not _MODEL_DIR.exists():
        raise FileNotFoundError(f"模型目录不存在: {_MODEL_DIR}")

    _device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info("[RelevanceGate] 加载 BERT 模型 from %s (device=%s)", _MODEL_DIR, _device)

    # 1. Tokenizer
    _tokenizer = BertTokenizer.from_pretrained(str(_MODEL_DIR))

    # 2. BERT encoder
    _bert_model = BertModel.from_pretrained(str(_MODEL_DIR)).to(_device)
    _bert_model.eval()

    # 3. 分类头
    cfg_path = _MODEL_DIR / "config.json"
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    num_classes = cfg.get("num_classes", 2)
    _classifier = nn.Linear(_bert_model.config.hidden_size, num_classes).to(_device)
    _classifier.load_state_dict(
        torch.load(_MODEL_DIR / "classifier.pt", map_location=_device, weights_only=True)
    )
    _classifier.eval()

    logger.info("[RelevanceGate] 模型加载完成")


class RelevanceGate:
    """单一职责：判断一句话是否需要唤醒 HeavyAgent。"""

    def __init__(self, client=None, model=None, threshold: float = 0.5):
        # client / model 参数保留以兼容现有调用（Orchestrator 中 gate or RelevanceGate()），
        # 但不再使用。
        self._threshold = threshold

    async def is_relevant(self, utt: Utterance) -> bool:
        if _bert_model is None:
            logger.warning("[RelevanceGate] 模型未加载，返回 False")
            return False
        try:
            prob = await asyncio.to_thread(self._sync_predict, utt.text)
        except Exception:
            logger.exception("[RelevanceGate] BERT 推理失败，返回 False")
            return False
        return prob >= self._threshold

    def _sync_predict(self, text: str) -> float:
        """同步推理：返回 should_enter 概率（0~1）。"""
        assert _tokenizer is not None
        assert _bert_model is not None
        assert _classifier is not None
        assert _device is not None

        encoding = _tokenizer(
            text,
            max_length=_MAX_LEN,
            padding="max_length",
            truncation=True,
            return_tensors="pt",
        )
        input_ids = encoding["input_ids"].to(_device)
        attention_mask = encoding["attention_mask"].to(_device)

        with torch.no_grad():
            outputs = _bert_model(input_ids=input_ids, attention_mask=attention_mask)
            pooled = outputs.pooler_output
            logits = _classifier(pooled)
            probs = torch.softmax(logits, dim=1)
            prob_enter = probs[0, 1].item()

        return prob_enter
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
cd backend && uv run pytest tests/test_relevance_gate.py -v
```

Expected: 全部 8 个测试 PASS（4 个原有 + 4 个新增）。原有测试涉及 `AsyncMock` 的 Qwen client，但现在 `is_relevant` 内部不调用 client 了，原有测试会触发 `_sync_predict`，但由于没有加载模型会走到 `except` 返回 False。原有测试用 `AsyncMock` 构造的 client 不会阻止 `is_relevant` 运行，但 `_sync_predict` 会因为 `_bert_model is None` 而被 `is_relevant` 的 `if _bert_model is None` 提前拦截返回 False。

等等，原有 4 个测试也要能通过：
- `test_relevance_true_returns_bool_true` — stub_client("true")，但 `is_relevant` 不再用 client，会尝试 `_sync_predict`，但模型未加载 → 返回 False。这个测试会失败。

所以需要把原有测试也改成 patch `_sync_predict`。

让我修正 Step 3 的代码：原有测试已经在 Step 1 中被新测试覆盖了概念。但原有 4 个测试仍保留在文件中，需要让它们也能通过。

实际上最简单的方式：原有测试构造 `RelevanceGate(client=stub_client)`，但现在 `is_relevant` 不调用 client。原有测试期望 `is_relevant("违法解除赔多少？") == True`，但由于模型没加载，会返回 False。

方案：在测试中 monkeypatch 加载模型，或者把所有原有测试也改成 patch `_sync_predict`。

更干净的方案：在 conftest 中提供一个 fixture，在测试中自动 mock `_sync_predict`。但 plan 里要具体。

让我修改原有测试文件的内容，把所有测试统一用 patch `_sync_predict`。

实际上原有测试文件是：
```python
def _stub_client(content: str):
    client = MagicMock()
    client.chat.completions.create = AsyncMock(...)
    return client
```

这些测试现在没用了（因为不再调用 client），但文件里还有它们。我需要：

方案 A：删除原有测试，保留新测试。
方案 B：修改原有测试，也用 patch `_sync_predict`。

按照 YAGNI，原有测试测的是 Qwen 行为，现在不需要了。但删除测试需要慎重。让我修改原有测试使其兼容。

实际上，更好的做法是在 `test_relevance_gate.py` 中：
1. 删除原有依赖 `AsyncMock` 的测试
2. 保留契约测试（`test_gate_contract_no_severity_no_intent_type`）
3. 新增 BERT 相关测试

但计划要具体。让我重写整个测试文件。

```python
# backend/tests/test_relevance_gate.py
"""Tests for RelevanceGate — 二分类相关性闸门。

设计意图：输出只有 bool，不含任何产品策略字段。接入 BERT 后训练目标
不需要随产品迭代变动。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.relevance_gate import RelevanceGate
from models.utterance import Utterance


def _utt(text: str, speaker: str) -> Utterance:
    return Utterance(id="u_x", text=text, speaker=speaker, t_start=0.0, t_end=1.0)


# ── BERT 推理测试（mock _sync_predict，不依赖真实模型加载）──

@pytest.mark.asyncio
async def test_relevance_true_returns_bool_true():
    gate = RelevanceGate()
    with patch.object(gate, "_sync_predict", return_value=0.9):
        assert await gate.is_relevant(_utt("违法解除赔多少？", "client")) is True


@pytest.mark.asyncio
async def test_relevance_false_returns_bool_false():
    gate = RelevanceGate()
    with patch.object(gate, "_sync_predict", return_value=0.1):
        assert await gate.is_relevant(_utt("律师你好", "client")) is False


@pytest.mark.asyncio
async def test_relevance_threshold_boundary():
    """刚好 0.5 返回 True。"""
    gate = RelevanceGate()
    with patch.object(gate, "_sync_predict", return_value=0.5):
        assert await gate.is_relevant(_utt("某个边界文本", "client")) is True


@pytest.mark.asyncio
async def test_relevance_exception_defaults_false():
    """BERT 推理异常时按 False 处理，和现有 Qwen 抖动行为一致。"""
    gate = RelevanceGate()
    with patch.object(gate, "_sync_predict", side_effect=RuntimeError("mock error")):
        assert await gate.is_relevant(_utt("…", "client")) is False


@pytest.mark.asyncio
async def test_gate_contract_no_severity_no_intent_type():
    """红线契约：gate 的返回值类型是且仅是 bool。"""
    gate = RelevanceGate()
    with patch.object(gate, "_sync_predict", return_value=0.9):
        result = await gate.is_relevant(_utt("劳动法第87条怎么说", "client"))
    assert isinstance(result, bool)
    assert not hasattr(result, "severity")
    assert not hasattr(result, "intent_type")


# ── 模型未加载时的降级行为 ──

@pytest.mark.asyncio
async def test_model_not_loaded_returns_false():
    """模型未加载时 is_relevant 返回 False，不抛异常。"""
    gate = RelevanceGate()
    # 不 patch _sync_predict，此时 _bert_model 为 None
    assert await gate.is_relevant(_utt("任意文本", "client")) is False
```

好，现在原有测试的概念都被覆盖了（true/false/boundary/exception/contract），且全部通过。

- [ ] **Step 5: 重写测试文件为完整版本**

把 `backend/tests/test_relevance_gate.py` 完整替换为：

```python
"""Tests for RelevanceGate — 二分类相关性闸门。

设计意图：输出只有 bool，不含任何产品策略字段。接入 BERT 后训练目标
不需要随产品迭代变动。
"""

from unittest.mock import patch

import pytest

from agent.relevance_gate import RelevanceGate
from models.utterance import Utterance


def _utt(text: str, speaker: str) -> Utterance:
    return Utterance(id="u_x", text=text, speaker=speaker, t_start=0.0, t_end=1.0)


# ── BERT 推理测试（mock _sync_predict，不依赖真实模型加载）──

@pytest.mark.asyncio
async def test_relevance_true_returns_bool_true():
    gate = RelevanceGate()
    with patch.object(gate, "_sync_predict", return_value=0.9):
        assert await gate.is_relevant(_utt("违法解除赔多少？", "client")) is True


@pytest.mark.asyncio
async def test_relevance_false_returns_bool_false():
    gate = RelevanceGate()
    with patch.object(gate, "_sync_predict", return_value=0.1):
        assert await gate.is_relevant(_utt("律师你好", "client")) is False


@pytest.mark.asyncio
async def test_relevance_threshold_boundary():
    """刚好 0.5 返回 True。"""
    gate = RelevanceGate()
    with patch.object(gate, "_sync_predict", return_value=0.5):
        assert await gate.is_relevant(_utt("某个边界文本", "client")) is True


@pytest.mark.asyncio
async def test_relevance_exception_defaults_false():
    """BERT 推理异常时按 False 处理，和现有 Qwen 抖动行为一致。"""
    gate = RelevanceGate()
    with patch.object(gate, "_sync_predict", side_effect=RuntimeError("mock error")):
        assert await gate.is_relevant(_utt("…", "client")) is False


@pytest.mark.asyncio
async def test_gate_contract_no_severity_no_intent_type():
    """红线契约：gate 的返回值类型是且仅是 bool。"""
    gate = RelevanceGate()
    with patch.object(gate, "_sync_predict", return_value=0.9):
        result = await gate.is_relevant(_utt("劳动法第87条怎么说", "client"))
    assert isinstance(result, bool)
    assert not hasattr(result, "severity")
    assert not hasattr(result, "intent_type")


# ── 模型未加载时的降级行为 ──

@pytest.mark.asyncio
async def test_model_not_loaded_returns_false():
    """模型未加载时 is_relevant 返回 False，不抛异常。"""
    gate = RelevanceGate()
    assert await gate.is_relevant(_utt("任意文本", "client")) is False
```

- [ ] **Step 6: 运行全部测试，确认通过**

```bash
cd backend && uv run pytest tests/test_relevance_gate.py -v
```

Expected: 6 个测试全部 PASS。

- [ ] **Step 7: Commit**

```bash
git add backend/src/agent/relevance_gate.py backend/tests/test_relevance_gate.py
git commit -m "feat(relevance_gate): 替换 Qwen LLM 为本地 BERT 模型推理"
```

---

### Task 2: main.py startup 集成模型预加载

**Files:**
- Modify: `backend/main.py`

**背景:** `main.py` 的 `_startup()` 已负责初始化 session_manager。需要在其中加入 `load_relevance_model()` 调用，使服务启动时即加载 BERT 模型到内存/显存。加载失败抛异常，FastAPI 会阻止服务启动。

- [ ] **Step 1: 修改 main.py _startup 加入模型加载**

在 `backend/main.py` 的 `from agent.orchestrator import Orchestrator` 同级位置添加导入：

```python
from agent.relevance_gate import load_relevance_model
```

在 `_startup()` 函数开头添加调用（在 session_manager 初始化之前即可）：

```python
@app.on_event("startup")
async def _startup() -> None:
    # 预加载 BERT 模型。硬依赖：失败即阻止服务启动。
    load_relevance_model()

    global session_manager
    SESSION_DB.parent.mkdir(parents=True, exist_ok=True)
    backend = SQLiteBackend(SESSION_DB)
    session_manager = SessionManager(backend, snapshot_interval=60.0, ttl=600.0)
    await session_manager.start()
```

- [ ] **Step 2: 验证启动时模型加载成功**

手动启动服务，观察日志输出：

```bash
cd backend && uv run uvicorn main:app --reload
```

Expected log 输出：
```
[RelevanceGate] 加载 BERT 模型 from .../__modles__/intent_router_bert_binary (device=cpu)
[RelevanceGate] 模型加载完成
```

（如果设备有 GPU，device=cuda）

- [ ] **Step 3: 验证启动失败行为（可选，测试环境模拟）**

临时把 `__modles__/intent_router_bert_binary` 目录改名，启动服务确认报错：

```bash
mv backend/__modles__/intent_router_bert_binary backend/__modles__/intent_router_bert_binary.bak
cd backend && uv run uvicorn main:app --reload
# Expected: FileNotFoundError，服务无法启动
mv backend/__modles__/intent_router_bert_binary.bak backend/__modles__/intent_router_bert_binary
```

- [ ] **Step 4: Commit**

```bash
git add backend/main.py
git commit -m "feat(main): startup 时预加载 BERT RelevanceGate 模型"
```

---

### Task 3: 端到端验证

**Files:**
- 无需修改文件，仅运行现有测试

- [ ] **Step 1: 运行 relevance_gate 单元测试**

```bash
cd backend && uv run pytest tests/test_relevance_gate.py -v
```

Expected: 6 个测试全部 PASS。

- [ ] **Step 2: 运行 orchestrator 相关测试**

```bash
cd backend && uv run pytest tests/test_orchestrator.py -v
```

Expected: 全部 PASS（Orchestrator 用 `gate or RelevanceGate()` 构造，接口契约未变）。

- [ ] **Step 3: 运行完整测试套件（排除慢速测试）**

```bash
cd backend && uv run pytest -m "not slow" -q
```

Expected: 无新增失败。如果原有测试依赖 Qwen API 调用（如 e2e 测试），这些测试本来就需要环境变量，不受影响。

- [ ] **Step 4: Commit（如有测试 fix）**

如果 Task 3 中发现并修复了问题，单独 commit。

---

## Self-Review

**Spec coverage:**
- [x] 服务启动时预加载模型 → Task 2 Step 1
- [x] 模型加载失败阻止服务启动 → Task 2 Step 3 + `load_relevance_model()` 抛异常设计
- [x] `is_relevant()` 返回 bool 契约不变 → Task 1 测试覆盖
- [x] 异步接口保持 → Task 1 `asyncio.to_thread` 包装
- [x] 模型路径硬编码 → Task 1 `_MODEL_DIR`
- [x] 运行时推理异常降级为 False → Task 1 `try/except` + 测试覆盖

**Placeholder scan:** 无 TBD、TODO、"implement later"。

**Type consistency:**
- `load_relevance_model()` 无返回值，抛异常
- `RelevanceGate.__init__` 保留 `(client=None, model=None, threshold=0.5)` 兼容签名
- `is_relevant(self, utt: Utterance) -> bool` 未变
- `_sync_predict(self, text: str) -> float` 返回 should_enter 概率

**无 gaps。**
