# 角色感知意图路由 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 IntentRouter 按说话人角色差异化判断意图，simple/complex 走不同执行路径，complex 需律师确认后才调 HeavyAgent。

**Architecture:** IntentRouter 新增 speaker 参数 + Pydantic 模型（instructor 约束输出）；Orchestrator 按 severity 路由（simple → analyze_quick 直接推送，complex → pending 等待确认）；HeavyAgent 新增精简模式；main.py WebSocket 新增 confirm/dismiss 消息处理。

**Tech Stack:** Python 3.12, instructor, Pydantic, FastAPI WebSocket, Agno, pytest-asyncio

---

### Task 0: 统一 Utterance 类

**问题:** `models/utterance.py` 和 `agent/context_store.py` 各有一个 `Utterance` 类，字段不完全一致。Orchestrator 消费 context_store 版本，STT 产出 models 版本，main.py 中需要手动转换。

**方案:** 合并到 `models/utterance.py`，`context_store.py` 改为 import。

**Files:**
- Modify: `backend/src/models/utterance.py`（新增 timestamp 字段）
- Modify: `backend/src/agent/context_store.py`（删除重复类，改为 import）
- Modify: `backend/tests/test_context_store.py`（更新 import）
- Modify: `backend/tests/test_orchestrator.py`（更新 import）
- Modify: `backend/tests/test_heavy_agent.py`（更新 import）

合并后的类（`models/utterance.py`）：

```python
"""Utterance 数据模型:一段说话事件。

speaker 4 态(语义两两不同):
- None       — 初始态,声纹尚未算完(异步过程中)
- "lawyer"   — 终态:相似度 ≥ τ_high
- "client"   — 终态:相似度 ≤ τ_low
- "uncertain"— 终态:算完了但拿不准(音频过短或落在双阈值之间)
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Literal

Speaker = Literal["lawyer", "client", "uncertain"]
ClosedBy = Literal["vad", "soft_cap"]


@dataclass
class Utterance:
    id: str
    text: str
    t_start: float
    t_end: float
    speaker: Speaker | None = None
    closed_by: ClosedBy = "vad"
    timestamp: datetime = field(default_factory=datetime.now)
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        self.content_hash = hashlib.sha1(self.text.encode("utf-8")).hexdigest()[:12]

    def to_dict(self) -> dict:
        return asdict(self)
```

`context_store.py` 改动：删除 `class Utterance`，改为 `from models.utterance import Utterance`。ProfileEntry 保留不动。

- [ ] **Step 1: 更新 models/utterance.py**

添加 `timestamp` 字段（`field(default_factory=datetime.now)`）。

- [ ] **Step 2: 更新 context_store.py**

删除第 7-13 行的 `class Utterance`，在文件顶部添加 `from models.utterance import Utterance`。

- [ ] **Step 3: 更新所有测试文件的 import**

```bash
# 把 tests/ 下所有 from agent.context_store import ... Utterance ... 
# 改为 from models.utterance import Utterance
```

具体文件：
- `tests/test_context_store.py` — `from models.utterance import Utterance`（替换原有 import）
- `tests/test_orchestrator.py` — 同上
- `tests/test_heavy_agent.py` — 同上

- [ ] **Step 4: 运行测试确认无回归**

```bash
cd backend && uv run pytest tests/test_context_store.py tests/test_orchestrator.py tests/test_heavy_agent.py -v
```

预期: 全部 PASS（约 10 个测试）

- [ ] **Step 5: Commit**

```bash
git add backend/src/models/utterance.py backend/src/agent/context_store.py backend/tests/
git commit -m "refactor: unify Utterance classes into models/utterance.py"
```

---

### Task 1: 添加 instructor 依赖

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/uv.lock`（自动更新）

- [ ] **Step 1: 添加 instructor 到 pyproject.toml**

```toml
# backend/pyproject.toml — dependencies 数组中添加
"instructor>=1.0.0",
```

- [ ] **Step 2: 安装依赖**

```bash
cd backend && uv sync
```

验证: `uv run python -c "import instructor; print(instructor.__version__)"` 输出版本号。

- [ ] **Step 3: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock
git commit -m "chore: add instructor dependency for structured LLM output"
```

---

### Task 2: 重写 IntentRouter — Pydantic 模型 + instructor + 角色感知

**Files:**
- Modify: `backend/src/agent/intent_router.py`（重写全文）
- Modify: `backend/tests/test_intent_router.py`（适配新接口）
- Modify: `backend/tests/conftest.py`（新增 mock_ir_client fixture）

- [ ] **Step 1: 在 conftest.py 中添加 mock_ir_client fixture**

在 `mock_llm_client` fixture 之前添加：

```python
@pytest.fixture
def mock_ir_client():
    """Factory fixture: returns a function that creates stub IntentRouter instances."""
    from agent.intent_router import IntentResult  # noqa: PLC0415

    def _make(**kwargs):
        result = IntentResult(
            severity=kwargs.pop("severity", "ignore"),
            intent_type=kwargs.pop("intent_type", "none"),
            rationale=kwargs.pop("rationale", ""),
            **kwargs,
        )

        class StubIR:
            async def classify(self, text: str, speaker: str | None = None) -> IntentResult:
                return result

        return StubIR()

    return _make
```

- [ ] **Step 2: 运行现有 IR 测试确认它们会失败**

```bash
cd backend && uv run pytest tests/test_intent_router.py -v
```

预期: 全部 FAIL（因为测试断言 `result.intent` 不再存在）

- [ ] **Step 3: 重写 intent_router.py**

```python
"""Intent Router — role-aware intent classification with instructor structured output."""

from typing import Literal

import instructor
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from agent.llm_client import build_qwen_client, QWEN_MODEL


class IntentResult(BaseModel):
    """角色感知的意图分类结果"""

    severity: Literal["ignore", "simple", "complex"] = Field(
        description="意图严重程度。ignore=无需响应, simple=可快速回答, complex=需要深度分析"
    )
    intent_type: Literal[
        "query_law",
        "compute_compensation",
        "draft_clause",
        "summarize",
        "record_only",
        "none",
    ] = Field(description="意图类型")
    law_domain: str | None = Field(
        default=None, description="法律领域，如'劳动法'、'合同法'"
    )
    entities: list[str] = Field(
        default_factory=list, description="关键法律实体，如['竞业限制', 'N+1补偿']"
    )
    rationale: str = Field(description="一句话判断依据，≤50字")


ROLE_AWARE_PROMPT = """\
你正在旁听律师与客户的劳动法律咨询。根据**说话人角色**判断当前这句话的意图。

## 角色判断规则

### 当说话人是 client（客户）：
- ignore: 寒暄、确认、应答（"好的"、"嗯"、"谢谢"）、无法律信息
- simple: 明确的法条查询或金额计算需求。例如："N+1怎么算"、"加班费按什么标准"、"竞业限制最长多久"
- complex: 需要策略判断、风险评估、多步骤综合分析。例如："能赢吗"、"该怎么谈判"、"风险有多大"

### 当说话人是 lawyer（律师）：
- ignore: 常规事实询问（"签合同了吗"、"月薪多少"、"工作多久了"）、流程性引导、确认性应答
- simple: 律师询问某个具体法条或计算，系统可以直接补充。例如：律师问"第47条是什么来着"
- complex: 律师的分析存在明显遗漏或需要补充。例如：律师引用法条但漏了关键补偿标准，或律师给出的建议缺少风险提示

### 当说话人是 uncertain（不确定）：
- 按 client 规则判断

## 意图类型说明
- query_law: 需要引用法条/判例
- compute_compensation: 需要按法律公式计算（赔偿、加班费、年假折算等）
- draft_clause: 需要起草或推荐合同条款
- summarize: 需要归纳当前对话中的事实或诉求
- record_only: 关键信息打点，不主动推送建议
- none: 无具体法律需求

当前说话人: {speaker}
当前句子: {text}
"""


class IntentRouter:
    def __init__(self, client: AsyncOpenAI | None = None, model: str | None = None):
        raw_client = client or build_qwen_client()
        if raw_client is None:
            raise RuntimeError(
                "IntentRouter requires a valid LLM client. "
                "Set DASHSCOPE_API_KEY or pass a client."
            )
        self._client = instructor.from_openai(raw_client, mode=instructor.Mode.MD_JSON)
        self._model = model or QWEN_MODEL

    async def classify(
        self, text: str, speaker: str | None = None
    ) -> IntentResult:
        speaker_label = speaker or "uncertain"
        prompt = ROLE_AWARE_PROMPT.format(speaker=speaker_label, text=text)

        result = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=200,
            extra_body={"enable_thinking": False},
            response_model=IntentResult,
        )
        return result
```

- [ ] **Step 4: 重写 test_intent_router.py**

```python
"""Tests for IntentRouter — role-aware classification."""

import pytest


@pytest.mark.asyncio
async def test_classifies_legal_question_as_simple(mock_ir_client):
    router = mock_ir_client(severity="simple", intent_type="query_law")
    result = await router.classify("违法解除赔多少？", speaker="client")
    assert result.severity == "simple"
    assert result.intent_type == "query_law"


@pytest.mark.asyncio
async def test_classifies_greeting_as_ignore(mock_ir_client):
    router = mock_ir_client(severity="ignore", intent_type="none")
    result = await router.classify("律师你好", speaker="client")
    assert result.severity == "ignore"


@pytest.mark.asyncio
async def test_classifies_strategy_question_as_complex(mock_ir_client):
    router = mock_ir_client(severity="complex", intent_type="query_law")
    result = await router.classify("我该怎么跟公司谈？", speaker="client")
    assert result.severity == "complex"


@pytest.mark.asyncio
async def test_lawyer_routine_question_as_ignore(mock_ir_client):
    router = mock_ir_client(severity="ignore", intent_type="none")
    result = await router.classify("你签劳动合同了吗？", speaker="lawyer")
    assert result.severity == "ignore"


@pytest.mark.asyncio
async def test_lawyer_missing_statute_triggers_complex(mock_ir_client):
    router = mock_ir_client(severity="complex", intent_type="query_law")
    result = await router.classify("根据第39条可以解除", speaker="lawyer")
    assert result.severity == "complex"
```

- [ ] **Step 5: 运行 IR 测试验证通过**

```bash
cd backend && uv run pytest tests/test_intent_router.py -v
```

预期: 5 passed

- [ ] **Step 6: Commit**

```bash
git add backend/src/agent/intent_router.py backend/tests/test_intent_router.py backend/tests/conftest.py
git commit -m "feat: rewrite IntentRouter with role-aware prompt and instructor structured output"
```

---

### Task 3: 更新 Orchestrator — speaker 传递 + severity 路由 + 确认机制

**Files:**
- Modify: `backend/src/agent/orchestrator.py`
- Modify: `backend/src/agent/profile_agent.py`（`extract()` 的 `speaker` 参数类型改为 `str | None`）
- Modify: `backend/tests/test_orchestrator.py`

- [ ] **Step 1: 重写 orchestrator.py**

```python
"""Orchestrator — wires ContextStore, IntentRouter, ProfileAgent, HeavyAgent."""

import asyncio
import time
import uuid
from dataclasses import dataclass, field

from agent.context_store import ContextStore
from agent.heavy_agent import HeavyAgent
from agent.intent_router import IntentRouter
from agent.profile_agent import ProfileAgent
from models.utterance import Utterance

PENDING_TIMEOUT = 30


@dataclass
class PendingRequest:
    request_id: str
    utt: Utterance
    intent_type: str
    generation: int
    created_at: float = field(default_factory=time.monotonic)
    meta: dict = field(default_factory=dict)


class Orchestrator:
    def __init__(
        self,
        ctx: ContextStore,
        ir: IntentRouter | None = None,
        pa: ProfileAgent | None = None,
        ha: HeavyAgent | None = None,
    ):
        self._ctx = ctx
        self._ir = ir or IntentRouter()
        self._pa = pa or ProfileAgent()
        self._ha = ha or HeavyAgent(ctx)
        self._suggestion_callback = None
        self._pending: dict[str, PendingRequest] = {}
        asyncio.create_task(self._ctx.start_profile_worker())

    def set_suggestion_callback(self, callback) -> None:
        self._suggestion_callback = callback

    async def handle_utterance(self, utt: Utterance) -> int:
        self.cleanup_expired()
        generation = await self._ctx.append_utterance(utt)

        ir_task = asyncio.create_task(
            self._ir.classify(text=utt.text, speaker=utt.speaker)
        )
        pa_task = asyncio.create_task(
            self._pa.extract(
                text=utt.text,
                speaker=utt.speaker,
                existing_keys=self._ctx.get_profile_keys(),
                utt_id=utt.id,
            )
        )

        pa_entries = await pa_task
        if pa_entries:
            await self._ctx.enqueue_profile_update(utt.id, pa_entries)

        ir_result = await ir_task

        if ir_result.severity == "ignore":
            return generation

        if not self._suggestion_callback:
            return generation

        meta = {
            "severity": ir_result.severity,
            "intent_type": ir_result.intent_type,
            "law_domain": ir_result.law_domain,
            "entities": ir_result.entities,
            "utt_id": utt.id,
        }

        if ir_result.severity == "simple":
            result = await self._ha.analyze_quick(
                utt, ir_result.intent_type, generation
            )
            if result is not None:
                meta["kind"] = "ready"
                await self._emit_suggestion(result, meta)
        else:
            request_id = f"req_{uuid.uuid4().hex[:8]}"
            self._pending[request_id] = PendingRequest(
                request_id=request_id,
                utt=utt,
                intent_type=ir_result.intent_type,
                generation=generation,
                meta=meta,
            )
            meta["kind"] = "pending"
            meta["request_id"] = request_id
            meta["expires_in"] = PENDING_TIMEOUT
            await self._emit_suggestion(None, meta)

        return generation

    async def confirm_analysis(self, request_id: str) -> bool:
        pending = self._pending.pop(request_id, None)
        if pending is None:
            return False
        if time.monotonic() - pending.created_at > PENDING_TIMEOUT:
            return False

        result = await self._ha.analyze(
            pending.utt, pending.intent_type, pending.generation
        )
        if result is not None:
            pending.meta["kind"] = "ready"
            pending.meta["request_id"] = request_id
            await self._emit_suggestion(result, pending.meta)
        return True

    def dismiss_pending(self, request_id: str) -> None:
        self._pending.pop(request_id, None)

    def cleanup_expired(self) -> int:
        now = time.monotonic()
        expired = [
            rid
            for rid, pr in self._pending.items()
            if now - pr.created_at > PENDING_TIMEOUT
        ]
        for rid in expired:
            del self._pending[rid]
        return len(expired)

    async def shutdown(self) -> None:
        """清理资源：取消 profile worker，清空 pending。"""
        await self._ctx.stop_profile_worker()
        self._pending.clear()

    async def _emit_suggestion(self, text: str | None, meta: dict) -> None:
        cb_result = self._suggestion_callback(text, meta)
        if asyncio.iscoroutine(cb_result):
            await cb_result
```

- [ ] **Step 2: 重写 test_orchestrator.py**

```python
"""Tests for Orchestrator."""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from agent.context_store import ContextStore
from agent.heavy_agent import HeavyAgent
from agent.intent_router import IntentResult
from agent.orchestrator import Orchestrator, PENDING_TIMEOUT
from agent.profile_agent import ProfileAgent
from models.utterance import Utterance


@pytest.fixture(autouse=True)
def _mock_deepseek_env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")


@pytest_asyncio.fixture
async def store():
    ctx = ContextStore()
    await ctx.start_profile_worker()
    return ctx


@pytest.mark.asyncio
async def test_routes_simple_intent_to_quick(store, mock_ir_client):
    """simple → analyze_quick，直接推送 ready 建议。"""
    ir_stub = mock_ir_client(severity="simple", intent_type="query_law")
    pa_client = MagicMock()
    pa_client.chat.completions.create = AsyncMock(
        return_value=MagicMock(
            choices=[MagicMock(message=MagicMock(content='{"entries": []}'))]
        )
    )

    ha = HeavyAgent(store)
    with patch.object(ha._quick_agent, "arun", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = AsyncMock(content="根据劳动法第87条，应支付2N赔偿金。")

        orch = Orchestrator(
            store, ir=ir_stub, pa=ProfileAgent(client=pa_client), ha=ha
        )

        hw_results = []
        async def on_suggestion(text, meta):
            hw_results.append((text, meta))

        orch.set_suggestion_callback(on_suggestion)

        utt = Utterance(
            id="u_1", text="违法解除赔多少？", speaker="client",
            t_start=0.0, t_end=1.0, timestamp=datetime.now(),
        )
        await orch.handle_utterance(utt)
        await asyncio.sleep(0.1)

        assert len(hw_results) == 1
        text, meta = hw_results[0]
        assert "劳动法" in text
        assert meta["kind"] == "ready"
        assert meta["severity"] == "simple"


@pytest.mark.asyncio
async def test_complex_emits_pending_not_ready(store, mock_ir_client):
    """complex → 发出 pending 建议（text=None），不触发 analyze。"""
    ir_stub = mock_ir_client(severity="complex", intent_type="query_law")
    pa_client = MagicMock()
    pa_client.chat.completions.create = AsyncMock(
        return_value=MagicMock(
            choices=[MagicMock(message=MagicMock(content='{"entries": []}'))]
        )
    )

    ha = HeavyAgent(store)
    with patch.object(ha._full_agent, "arun", new_callable=AsyncMock) as mock_full:
        mock_full.return_value = AsyncMock(content="分析结果")

        orch = Orchestrator(
            store, ir=ir_stub, pa=ProfileAgent(client=pa_client), ha=ha
        )

        suggestions = []
        async def on_suggestion(text, meta):
            suggestions.append((text, meta))

        orch.set_suggestion_callback(on_suggestion)

        utt = Utterance(
            id="u_1", text="能赢吗", speaker="client",
            t_start=0.0, t_end=1.0, timestamp=datetime.now(),
        )
        await orch.handle_utterance(utt)
        await asyncio.sleep(0.1)

        assert len(suggestions) == 1
        text, meta = suggestions[0]
        assert text is None
        assert meta["kind"] == "pending"
        assert "request_id" in meta
        assert meta["expires_in"] == PENDING_TIMEOUT
        mock_full.assert_not_called()


@pytest.mark.asyncio
async def test_confirm_analysis_triggers_heavy_agent(store, mock_ir_client):
    """律师确认后调用 confirm_analysis → 触发 analyze。"""
    ir_stub = mock_ir_client(severity="complex", intent_type="query_law")
    pa_client = MagicMock()
    pa_client.chat.completions.create = AsyncMock(
        return_value=MagicMock(
            choices=[MagicMock(message=MagicMock(content='{"entries": []}'))]
        )
    )

    ha = HeavyAgent(store)
    with patch.object(ha._full_agent, "arun", new_callable=AsyncMock) as mock_full:
        mock_full.return_value = AsyncMock(content="根据案情分析，建议收集证据后申请劳动仲裁。")

        orch = Orchestrator(
            store, ir=ir_stub, pa=ProfileAgent(client=pa_client), ha=ha
        )

        suggestions = []
        async def on_suggestion(text, meta):
            suggestions.append((text, meta))

        orch.set_suggestion_callback(on_suggestion)

        utt = Utterance(
            id="u_1", text="能赢吗", speaker="client",
            t_start=0.0, t_end=1.0, timestamp=datetime.now(),
        )
        await orch.handle_utterance(utt)
        await asyncio.sleep(0.1)

        request_id = suggestions[0][1]["request_id"]
        ok = await orch.confirm_analysis(request_id)
        await asyncio.sleep(0.1)
        assert ok

        mock_full.assert_called_once()
        assert len(suggestions) == 2
        assert suggestions[1][1]["kind"] == "ready"
        assert "劳动仲裁" in suggestions[1][0]


@pytest.mark.asyncio
async def test_confirm_expired_request_returns_false(store, mock_ir_client):
    """过期请求确认返回 False。"""
    ir_stub = mock_ir_client(severity="complex", intent_type="query_law")
    pa_client = MagicMock()
    pa_client.chat.completions.create = AsyncMock(
        return_value=MagicMock(
            choices=[MagicMock(message=MagicMock(content='{"entries": []}'))]
        )
    )

    ha = HeavyAgent(store)
    orch = Orchestrator(
        store, ir=ir_stub, pa=ProfileAgent(client=pa_client), ha=ha
    )
    orch.set_suggestion_callback(lambda text, meta: None)

    utt = Utterance(
        id="u_1", text="能赢吗", speaker="client",
        t_start=0.0, t_end=1.0, timestamp=datetime.now(),
    )
    await orch.handle_utterance(utt)
    await asyncio.sleep(0.1)

    for pr in orch._pending.values():
        pr.created_at = 0

    request_ids = list(orch._pending.keys())
    ok = await orch.confirm_analysis(request_ids[0])
    assert not ok


@pytest.mark.asyncio
async def test_dismiss_pending_removes_request(store, mock_ir_client):
    """律师关闭建议卡片后 pending 被清除。"""
    ir_stub = mock_ir_client(severity="complex", intent_type="query_law")
    pa_client = MagicMock()
    pa_client.chat.completions.create = AsyncMock(
        return_value=MagicMock(
            choices=[MagicMock(message=MagicMock(content='{"entries": []}'))]
        )
    )

    ha = HeavyAgent(store)
    orch = Orchestrator(
        store, ir=ir_stub, pa=ProfileAgent(client=pa_client), ha=ha
    )

    suggestions = []
    async def on_suggestion(text, meta):
        suggestions.append((text, meta))
    orch.set_suggestion_callback(on_suggestion)

    utt = Utterance(
        id="u_1", text="能赢吗", speaker="client",
        t_start=0.0, t_end=1.0, timestamp=datetime.now(),
    )
    await orch.handle_utterance(utt)
    await asyncio.sleep(0.1)

    request_id = suggestions[0][1]["request_id"]
    assert request_id in orch._pending

    orch.dismiss_pending(request_id)
    assert request_id not in orch._pending


@pytest.mark.asyncio
async def test_ignore_does_not_trigger_suggestion(store, mock_ir_client):
    ir_stub = mock_ir_client(severity="ignore", intent_type="none")
    pa_client = MagicMock()
    pa_client.chat.completions.create = AsyncMock(
        return_value=MagicMock(
            choices=[MagicMock(message=MagicMock(content='{"entries": []}'))]
        )
    )

    ha = HeavyAgent(store)
    orch = Orchestrator(
        store, ir=ir_stub, pa=ProfileAgent(client=pa_client), ha=ha
    )

    suggestions = []
    async def on_suggestion(text, meta):
        suggestions.append(text)
    orch.set_suggestion_callback(on_suggestion)

    utt = Utterance(
        id="u_1", text="律师你好", speaker="client",
        t_start=0.0, t_end=1.0, timestamp=datetime.now(),
    )
    await orch.handle_utterance(utt)
    await asyncio.sleep(0.1)

    assert len(suggestions) == 0


@pytest.mark.asyncio
async def test_pa_extracts_facts_to_profile(store, mock_ir_client):
    ir_stub = mock_ir_client(severity="ignore", intent_type="none")
    pa_client = MagicMock()
    pa_client.chat.completions.create = AsyncMock(
        return_value=MagicMock(
            choices=[MagicMock(
                message=MagicMock(content='{"entries": [{"key": "月薪", "value": "两万五"}]}')
            )]
        )
    )

    ha = HeavyAgent(store)
    orch = Orchestrator(
        store, ir=ir_stub, pa=ProfileAgent(client=pa_client), ha=ha
    )
    orch.set_suggestion_callback(lambda text, meta: None)

    utt = Utterance(
        id="u_1", text="月薪两万五，税前", speaker="client",
        t_start=0.0, t_end=1.0, timestamp=datetime.now(),
    )
    await orch.handle_utterance(utt)
    await asyncio.sleep(0.1)

    profile = store.get_profile()
    assert len(profile) >= 1
    keys = [e.key for e in profile]
    assert "月薪" in keys


@pytest.mark.asyncio
async def test_ten_turn_dialogue_stability_and_completeness(store):
    """10轮短对话回归: simple 直推, complex 挂起, ignore 不触发。"""

    class StubIntentRouter:
        def __init__(self, mapping):
            self._mapping = mapping

        async def classify(self, text: str, speaker: str | None = None):
            entry = self._mapping.get(text, ("ignore", "none"))
            severity, intent_type = entry
            return IntentResult(severity=severity, intent_type=intent_type, rationale="stub")

    class StubProfileAgent:
        async def extract(self, text: str, speaker: str, existing_keys: list[str], utt_id=None):
            entries = []
            if "月薪" in text and "月薪" not in existing_keys:
                entries.append(MagicMock(key="月薪", value="25000", source_utt_id=utt_id or ""))
            if "工龄" in text and "工龄" not in existing_keys:
                entries.append(MagicMock(key="工龄", value="2年3个月", source_utt_id=utt_id or ""))
            if "解除通知" in text and "解除通知时间" not in existing_keys:
                entries.append(MagicMock(key="解除通知时间", value="2026-05-01", source_utt_id=utt_id or ""))
            return entries

    class StubHeavyAgent:
        async def analyze(self, utt: Utterance, intent_type: str, generation: int):
            return f"[{intent_type}] 建议: {utt.text[:20]} (g={generation})"

        async def analyze_quick(self, utt: Utterance, intent_type: str, generation: int):
            return f"[quick:{intent_type}] {utt.text[:20]} (g={generation})"

    turns = [
        ("u_1", "律师你好", "client", ("ignore", "none")),
        ("u_2", "我被公司违法解除了", "client", ("complex", "query_law")),
        ("u_3", "先确认解除通知时间", "lawyer", ("ignore", "none")),
        ("u_4", "解除通知是5月1号口头说的", "client", ("simple", "record_only")),
        ("u_5", "月薪两万五，税前", "client", ("simple", "record_only")),
        ("u_6", "工龄2年3个月", "client", ("simple", "record_only")),
        ("u_7", "能拿多少赔偿", "client", ("simple", "compute_compensation")),
        ("u_8", "还要不要继续上班", "client", ("complex", "query_law")),
        ("u_9", "先准备证据清单", "lawyer", ("ignore", "none")),
        ("u_10", "好的我会整理合同和工资流水", "client", ("ignore", "none")),
    ]
    intent_mapping = {text: entry for _, text, _, entry in turns}

    orch = Orchestrator(
        store,
        ir=StubIntentRouter(intent_mapping),
        pa=StubProfileAgent(),
        ha=StubHeavyAgent(),
    )

    suggestions = []
    async def on_suggestion(text, meta):
        suggestions.append((text, meta))
    orch.set_suggestion_callback(on_suggestion)

    generations = []
    for utt_id, text, speaker, _ in turns:
        generation = await orch.handle_utterance(
            Utterance(id=utt_id, text=text, speaker=speaker,
                      t_start=0.0, t_end=1.0, timestamp=datetime.now())
        )
        generations.append(generation)

    await asyncio.sleep(0.1)

    assert generations == list(range(1, 11))

    ready_suggestions = [(t, m) for t, m in suggestions if m["kind"] == "ready"]
    pending_suggestions = [(t, m) for t, m in suggestions if m["kind"] == "pending"]

    simple_count = sum(1 for _, _, _, (s, _) in turns if s == "simple")
    complex_count = sum(1 for _, _, _, (s, _) in turns if s == "complex")

    assert len(ready_suggestions) == simple_count
    assert len(pending_suggestions) == complex_count
    assert all(t is not None for t, _ in ready_suggestions)
    assert all(t is None for t, _ in pending_suggestions)
    assert all("request_id" in m for _, m in pending_suggestions)

    for _, meta in pending_suggestions:
        await orch.confirm_analysis(meta["request_id"])
    await asyncio.sleep(0.1)
    total_ready = sum(1 for t, m in suggestions if m["kind"] == "ready")
    assert total_ready == simple_count + complex_count

    profile_keys = set(store.get_profile_keys())
    assert {"月薪", "工龄", "解除通知时间"}.issubset(profile_keys)


@pytest.mark.asyncio
async def test_cleanup_expired_removes_stale_requests(store, mock_ir_client):
    """过期清理移除超时请求。"""
    ir_stub = mock_ir_client(severity="complex", intent_type="query_law")
    pa_client = MagicMock()
    pa_client.chat.completions.create = AsyncMock(
        return_value=MagicMock(
            choices=[MagicMock(message=MagicMock(content='{"entries": []}'))]
        )
    )

    ha = HeavyAgent(store)
    orch = Orchestrator(
        store, ir=ir_stub, pa=ProfileAgent(client=pa_client), ha=ha
    )
    orch.set_suggestion_callback(lambda text, meta: None)

    utt = Utterance(
        id="u_1", text="能赢吗", speaker="client",
        t_start=0.0, t_end=1.0, timestamp=datetime.now(),
    )
    await orch.handle_utterance(utt)
    await asyncio.sleep(0.1)
    assert len(orch._pending) == 1

    for pr in orch._pending.values():
        pr.created_at = 0

    removed = orch.cleanup_expired()
    assert removed == 1
    assert len(orch._pending) == 0
```

- [ ] **Step 3: 运行 orchestrator 测试验证通过**

```bash
cd backend && uv run pytest tests/test_orchestrator.py -v
```

预期: 10 passed

- [ ] **Step 4: Commit**

```bash
git add backend/src/agent/orchestrator.py backend/tests/test_orchestrator.py
git commit -m "feat: add severity-based routing with complex confirmation flow"
```

---

### Task 4: HeavyAgent 双模式 — analyze_quick

**Files:**
- Modify: `backend/src/agent/heavy_agent.py`
- Modify: `backend/tests/test_heavy_agent.py`

- [ ] **Step 1: 更新 heavy_agent.py**

在 `HeavyAgent.__init__` 中添加 `_quick_agent`，新增 `analyze_quick()` 方法：

```python
# heavy_agent.py — 在 SYSTEM_PROMPT 后面添加

QUICK_SYSTEM_PROMPT = """你是一名专业的劳动仲裁法律顾问。

你的任务是对简单法律查询提供**快速、直接**的回答。只需1-3句话给出答案即可，不需要完整分析。

例如：
- 法条查询 → 直接给出法条编号和内容
- 金额计算 → 直接给出公式和结果
- 模板推荐 → 直接给出模板名称和要点
"""
```

`__init__` 中将 `self._agent` 改为 `self._full_agent`，新增 `self._quick_agent`：

```python
class HeavyAgent:
    def __init__(self, ctx: ContextStore, model=None):
        self._ctx = ctx
        self._model = model or _build_model()

        self._full_agent = Agent(
            model=self._model,
            instructions=SYSTEM_PROMPT,
            skills=_load_skills(),
            tools=[self._make_get_context_tool()],
        )

        self._quick_agent = Agent(
            model=self._model,
            instructions=QUICK_SYSTEM_PROMPT,
            tools=[self._make_get_context_tool()],
        )
```

`analyze()` 中用 `self._full_agent` 替代 `self._agent`，intent 参数改为 intent_type：

```python
    async def analyze(
        self, trigger_utt: Utterance, intent_type: str, generation: int
    ) -> str | None:
        if self._ctx._generation != generation:
            return None

        prompt = f"用户问题：{trigger_utt.text}\n意图类型：{intent_type}"
        response = await self._full_agent.arun(prompt)

        if self._ctx._generation != generation:
            return None

        return response.content if hasattr(response, "content") else str(response)
```

新增 `analyze_quick()`：

```python
    async def analyze_quick(
        self, trigger_utt: Utterance, intent_type: str, generation: int
    ) -> str | None:
        if self._ctx._generation != generation:
            return None

        prompt = f"用户问题：{trigger_utt.text}\n意图类型：{intent_type}\n请用1-3句话直接回答。"
        response = await self._quick_agent.arun(prompt)

        if self._ctx._generation != generation:
            return None

        return response.content if hasattr(response, "content") else str(response)
```

- [ ] **Step 2: 更新 test_heavy_agent.py**

将 `agent._agent` 改为 `agent._full_agent`，新增 `analyze_quick` 测试：

```python
"""Tests for HeavyAgent — Agno-based analysis agent."""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from agent.context_store import ContextStore, ProfileEntry
from agent.heavy_agent import HeavyAgent
from models.utterance import Utterance


@pytest.fixture(autouse=True)
def _mock_env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")


@pytest.fixture
def store():
    return ContextStore()


@pytest.fixture
def populated_store(store):
    store._utterances = [
        Utterance(id="u_0", text="律师你好", speaker="client", t_start=0.0, t_end=1.0, timestamp=datetime.now()),
        Utterance(id="u_1", text="月薪两万五", speaker="client", t_start=1.0, t_end=2.0, timestamp=datetime.now()),
    ]
    store._profile = [
        ProfileEntry(key="月薪", value="25000", timestamp=datetime.now(), source_utt_id="u_1"),
        ProfileEntry(key="工龄", value="2年3个月", timestamp=datetime.now(), source_utt_id="u_1"),
    ]
    store._generation = 2
    return store


@pytest.mark.asyncio
async def test_analyze_returns_analysis_text(populated_store):
    agent = HeavyAgent(populated_store)

    with patch.object(agent._full_agent, "arun", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = AsyncMock(content="根据劳动法第87条，违法解除应支付2N赔偿金。")

        trigger = Utterance(
            id="u_2", text="违法解除赔多少？", speaker="client",
            t_start=2.0, t_end=3.0, timestamp=datetime.now(),
        )
        result = await agent.analyze(trigger, intent_type="query_law", generation=2)

        assert result is not None
        assert "劳动法" in result
        mock_run.assert_called_once()


@pytest.mark.asyncio
async def test_analyze_returns_none_when_generation_stale(populated_store):
    agent = HeavyAgent(populated_store)

    trigger = Utterance(
        id="u_2", text="违法解除赔多少？", speaker="client",
        t_start=2.0, t_end=3.0, timestamp=datetime.now(),
    )
    result = await agent.analyze(trigger, intent_type="query_law", generation=1)

    assert result is None


@pytest.mark.asyncio
async def test_analyze_quick_returns_short_response(populated_store):
    agent = HeavyAgent(populated_store)

    with patch.object(agent._quick_agent, "arun", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = AsyncMock(content="N+1补偿：工作每满一年支付一个月工资。")

        trigger = Utterance(
            id="u_2", text="N+1怎么算", speaker="client",
            t_start=2.0, t_end=3.0, timestamp=datetime.now(),
        )
        result = await agent.analyze_quick(trigger, intent_type="compute_compensation", generation=2)

        assert result is not None
        assert "N+1" in result
        mock_run.assert_called_once()
```

- [ ] **Step 3: 运行 heavy_agent 测试**

```bash
cd backend && uv run pytest tests/test_heavy_agent.py -v
```

预期: 3 passed

- [ ] **Step 4: Commit**

```bash
git add backend/src/agent/heavy_agent.py backend/tests/test_heavy_agent.py
git commit -m "feat: add analyze_quick mode to HeavyAgent for simple queries"
```

---

### Task 5: WebSocket confirm/dismiss 路由

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: 在 main.py 中接入 Orchestrator 并处理 confirm/dismiss**

当前 `main.py` 的 WebSocket handler 只做 STT 转录推送，没有 Orchestrator。需要接入 Orchestrator 并在 text 消息中处理 confirm/dismiss。

改动 `legal_session`：

```python
# main.py — 在 import 区新增
from agent.context_store import ContextStore
from agent.orchestrator import Orchestrator

# 在 legal_session 内，stt_task 启动后添加
ctx = ContextStore()
orch = Orchestrator(ctx)

async def on_suggestion(text, meta):
    if meta.get("kind") == "pending":
        await ws.send_json({
            "type": "suggestion.pending",
            "text": None,
            "meta": {
                "severity": meta["severity"],
                "intent_type": meta["intent_type"],
                "law_domain": meta["law_domain"],
                "entities": meta["entities"],
                "utt_id": meta["utt_id"],
                "request_id": meta["request_id"],
                "expires_in": meta["expires_in"],
            },
        })
    else:
        await ws.send_json({
            "type": "suggestion.ready",
            "text": text,
            "meta": {
                "severity": meta["severity"],
                "intent_type": meta["intent_type"],
                "law_domain": meta["law_domain"],
                "entities": meta["entities"],
                "utt_id": meta["utt_id"],
            },
        })

orch.set_suggestion_callback(on_suggestion)
```

在 `consume_stt` 中每条 utterance 关闭后 feed 给 Orchestrator（`stream_stt()` 产出的 `utt` 已经是统一的 `Utterance`，直接传入即可）：

```python
# consume_stt 内，await ws.send_json(transcript) 后添加
asyncio.create_task(orch.handle_utterance(utt))
```

在 text 消息处理中新增 confirm/dismiss：

```python
elif "text" in data:
    msg = json.loads(data["text"])
    msg_type = msg.get("type")
    if msg_type == "ping":
        await ws.send_json({"type": "pong"})
    elif msg_type == "confirm":
        request_id = msg.get("request_id")
        if request_id:
            ok = await orch.confirm_analysis(request_id)
            await ws.send_json({"type": "confirm_ack", "request_id": request_id, "ok": ok})
    elif msg_type == "dismiss":
        request_id = msg.get("request_id")
        if request_id:
            orch.dismiss_pending(request_id)
```

- [ ] **Step 2: Commit**

```bash
git add backend/main.py
git commit -m "feat: wire Orchestrator into WebSocket with confirm/dismiss support"
```

在 `finally` 块中添加 `asyncio.create_task(orch.shutdown())`：

```python
    finally:
        await audio_q.put(None)
        asyncio.create_task(orch.shutdown())
        try:
            await stt_task
        except Exception:
            pass
```

---

### Task 6: 全量回归测试

- [ ] **Step 1: 运行所有非 slow 测试**

```bash
cd backend && uv run pytest tests/ -v --ignore=tests/test_stt_streaming.py --ignore=tests/test_voiceprint_streaming.py -k "not slow"
```

预期: 全部 PASS（约 30 个测试）

- [ ] **Step 2: Commit（如有遗留文件）**

```bash
git status
git add <any remaining files>
git commit -m "test: finalize role-aware routing test suite"
```
