# 实时会谈 Agent 路由架构重构 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `IntentRouter`（既判语义又判产品策略）拆成「业务无关的二分类相关性闸门 + Agno 原生 HITL 的自决深浅 Agent + 纯机械的代码 Orchestrator」，让意图模型有干净训练目标，深浅判断收归带全上下文的 Agent。

**Architecture:** 单条 utterance 进入后并行跑 `RelevanceGate.is_relevant(utt) -> bool`（Qwen 临时实现，结构稳定可换 BERT）和 `ProfileAgent.extract`（仅 client 句，是共享状态的**唯一写口**）。Gate 放行才 spawn `HeavyAgent` child run（Agno Agent + 持久化 db）；child 调不调 `@tool(requires_confirmation=True)` 的深度工具 `deep_analysis` 决定 run 是 `completed`（浅答直推）还是 `paused`（待律师 confirm，confirm 后用 `continue_run` 续跑同一 run，不重头理解）。Orchestrator 不做语义判断，只对 `run.is_paused` / `run.status == completed` 反应；HITL 状态在内存 `pending` 映射与 Agno db 两处都要清干净。

**Tech Stack:** Python 3.12，Agno 2.6.9（`requires_confirmation` + `continue_run` + `RunRequirement`），Agno `PostgresDb`（生产推荐；并发会谈不互锁），Qwen（DashScope OpenAI 兼容端点），DeepSeek（HA child 模型），pytest-asyncio。

---

## 背景概述（给接手的工程师）

- 旧 `IntentRouter` 在一个 LLM 调用里塞了 `severity`（产品策略：ignore/simple/complex）+ `intent_type`（绑死动作枚举），改交互策略或加 skill 都要重训。重构核心：把 `severity`/`intent_type` 从模型输出里整体剥离。
- 旧 `Orchestrator` 按 `severity` 硬路由 `analyze_quick` / `analyze` 两条分支；新代码只看 `run.is_paused` 一态。
- 旧 `HeavyAgent.analyze`/`analyze_quick` 两方法、`PendingRequest` 携带 `intent_type` 字段、`confirm_analysis` 里"从零重跑 analyze"全部删除，换成单一 `agent.arun(prompt)` + `agent.acontinue_run(run_id, requirements)`。
- `ProfileAgent` 写路径**不动**（PA 已经是单写者）；只是把"被 IR gate"这层去掉——本来 PA 也没被 gate，但代码读起来让人误以为是 IR 的下游。
- 前端协议会变（`meta` 不再有 `severity`/`intent_type`/`law_domain`/`entities`，新增 `preview`），需要前端配套改动，本计划只到后端结束并在 `main.py` 处明确标注边界。

---

## 关键文件结构

| 路径 | 新建/修改/删除 | 责任 |
|---|---|---|
| `backend/src/agent/relevance_gate.py` | **新建** | 二分类闸门：单一 `is_relevant(utt) -> bool`，Qwen 临时实现，接口稳定不绑业务 |
| `backend/src/agent/intent_router.py` | **删除** | 旧 IR，被 RelevanceGate 取代 |
| `backend/src/agent/child_tools.py` | **新建** | gated `deep_analysis` + 只读 `fetch_more_transcript` 两个 tool 工厂（闭包捕获 ctx） |
| `backend/src/agent/heavy_agent.py` | **重写** | 改为 `HeavyAgent` facade：`arun(utt)` 启动 run、`acontinue_run(run_id, requirements)` 续跑；建 Agno Agent 时绑 `db` + `session_id` + `user_id` |
| `backend/src/agent/orchestrator.py` | **重写** | 去掉 severity 分支，按 `run.is_paused` / `run.status` 反应；`PendingRequest` 字段精简；新增 TTL 扫描 + `abandon_run` |
| `backend/src/agent/prompts.py` | **修改** | 替换 `build_role_aware_prompt`→`build_relevance_prompt`；新增 `build_child_user_prompt` / `get_child_system_prompt` |
| `backend/src/config.py` | **修改** | 新增 `AGNO_DB_URL` / `RUN_TIMEOUT` / `PENDING_TTL` |
| `backend/main.py` | **修改** | 创建/复用 `PostgresDb` 单例；WS `meta` 用 `preview` 替换旧字段；持久化新 `PendingRequest` |
| `backend/tests/conftest.py` | **修改** | `mock_ir_client` → `mock_relevance_gate`（返回 bool） |
| `backend/tests/test_intent_router.py` | **删除** | 旧 IR 测试 |
| `backend/tests/test_relevance_gate.py` | **新建** | gate 二分类语义稳定性测试 |
| `backend/tests/test_child_tools.py` | **新建** | gated `deep_analysis` + 只读 `fetch_more_transcript` 行为测试 |
| `backend/tests/test_heavy_agent.py` | **重写** | `arun` / `acontinue_run` 路径覆盖 |
| `backend/tests/test_orchestrator.py` | **重写** | gate-only spawn、run-state 分支、画像兜底、清理无泄漏、按需拉取转写 |

---

## Task 1: Agno 持久化 db + 配置参数

**Files:**
- Modify: `backend/src/config.py`
- Modify: `backend/main.py`
- Modify: `backend/.env.example` — 新增 `AGNO_DB_URL`
- Test: `backend/tests/test_config_dotenv.py` 已有；新增 `backend/tests/test_agno_db_singleton.py`

**前置依赖：** 本机或 CI 需可达的 PostgreSQL 实例（dev 推荐 docker：`docker run -d --name legal-pg -p 5432:5432 -e POSTGRES_USER=legal -e POSTGRES_PASSWORD=legal -e POSTGRES_DB=legal_agent postgres:16`）。后续测试用 `InMemoryDb` 注入替身，**单测不依赖真实 Postgres**；集成测试在 conftest 标记 `pytest.mark.integration` 才连真 Postgres。

- [ ] **Step 1: 写失败测试 — 验证 PostgresDb 单例 + 测试可注入替身**

新建 `backend/tests/test_agno_db_singleton.py`：

```python
"""Tests for Agno PostgresDb wiring: singleton + 测试替身注入。

设计契约:
- 同进程内 get_agno_db() 必须返回同一实例(连接池单例);
- reset_agno_db_for_tests(replacement=...) 允许注入 InMemoryDb 让单测不依赖真实 Postgres。
"""

import pytest

from agno.db.in_memory import InMemoryDb

from agent.db import get_agno_db, reset_agno_db_for_tests


@pytest.fixture(autouse=True)
def _isolate():
    reset_agno_db_for_tests(replacement=InMemoryDb())
    yield
    reset_agno_db_for_tests()


def test_get_agno_db_returns_same_instance():
    """同进程内多次调用必须返回同一个 db 实例(避免重复打开连接池)。"""
    db1 = get_agno_db()
    db2 = get_agno_db()
    assert db1 is db2


def test_reset_with_replacement_swaps_singleton():
    """测试用例可通过 reset_agno_db_for_tests(replacement=...) 注入 InMemoryDb,
    让上层代码(orchestrator/heavy_agent)在单测里完全不依赖 Postgres。"""
    custom = InMemoryDb()
    reset_agno_db_for_tests(replacement=custom)
    assert get_agno_db() is custom


def test_reset_without_replacement_forces_rebuild():
    """reset_agno_db_for_tests() 不传参时清空单例,下次 get_agno_db 会按 AGNO_DB_URL 重建。
    此用例靠 autouse fixture 把替身设为 InMemoryDb,验证清空逻辑而不连真实 Postgres。"""
    first = get_agno_db()
    reset_agno_db_for_tests(replacement=InMemoryDb())
    second = get_agno_db()
    assert first is not second
```

> **集成测试单独写**：用真实 `PostgresDb(db_url=...)` 验证 schema 创建与 approval CRUD 的测试放在 `backend/tests/integration/test_agno_postgres_io.py`，挂 `@pytest.mark.integration` + CI 起 docker postgres。本计划不展开。

- [ ] **Step 2: 跑测试确认失败**

```
cd backend && uv run pytest tests/test_agno_db_singleton.py -v
```
Expected: FAIL — `from agent.db import get_agno_db` 不存在。

- [ ] **Step 3: 实现 `agent/db.py` 单例（支持测试替身）**

新建 `backend/src/agent/db.py`：

```python
"""Agno PostgresDb 单例。

生产用 Postgres,因为 HITL run 状态 + 多会话画像写并发量超过 SQLite 单写锁能扛的量级。
测试通过 reset_agno_db_for_tests(replacement=InMemoryDb()) 注入内存替身,不依赖 Postgres。
"""

from __future__ import annotations

from typing import Optional

from agno.db.base import BaseDb
from agno.db.postgres import PostgresDb

from config import AGNO_DB_URL

_db: Optional[BaseDb] = None


def get_agno_db() -> BaseDb:
    """返回模块级 db 单例;首次调用时按 AGNO_DB_URL 建 PostgresDb。"""
    global _db
    if _db is None:
        _db = PostgresDb(db_url=AGNO_DB_URL)
    return _db


def reset_agno_db_for_tests(replacement: Optional[BaseDb] = None) -> None:
    """清空模块级单例;可选注入替身(测试常用 InMemoryDb)。

    Args:
        replacement: 若提供,直接装入单例槽位;否则下次 get_agno_db 按 AGNO_DB_URL 重建。
    """
    global _db
    if _db is not None and hasattr(_db, "db_engine"):
        try:
            _db.db_engine.dispose()
        except Exception:
            pass
    _db = replacement
```

并在 `backend/src/config.py` 末尾追加：

```python
# ═══════════════════════════════════════════════════════
# Agno HITL / Run 状态持久化
# ═══════════════════════════════════════════════════════

# Agno PostgresDb 连接串。生产推荐;dev 默认连本机 docker postgres。
AGNO_DB_URL: str = os.getenv(
    "AGNO_DB_URL",
    "postgresql+psycopg://legal:legal@localhost:5432/legal_agent",
)

# 单个 child run 的最长在飞时间(秒)。卡死时由 asyncio.wait_for 强制取消。
RUN_TIMEOUT: float = float(os.getenv("RUN_TIMEOUT", "30"))

# 挂起 run 等待律师确认的最长 TTL(秒)。超时由后台扫描 abandon。
PENDING_TTL: float = float(os.getenv("PENDING_TTL", "300"))
```

并在 `backend/.env.example` 末尾追加：

```
AGNO_DB_URL=postgresql+psycopg://legal:legal@localhost:5432/legal_agent
RUN_TIMEOUT=30
PENDING_TTL=300
```

- [ ] **Step 4: 跑测试确认通过**

```
cd backend && uv run pytest tests/test_agno_db_singleton.py tests/test_config_dotenv.py -v
```
Expected: 所有用例 PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/src/config.py backend/src/agent/db.py backend/tests/test_agno_db_singleton.py backend/.env.example
git commit -m "feat(agent): 接入 Agno PostgresDb 单例并支持测试替身注入"
```

---

## Task 2: RelevanceGate（替换 IntentRouter）

**Files:**
- Create: `backend/src/agent/relevance_gate.py`
- Modify: `backend/src/agent/prompts.py` — 新增 `build_relevance_prompt`
- Create: `backend/tests/test_relevance_gate.py`

- [ ] **Step 1: 写失败测试 — 验证 `is_relevant` 返回 bool 且接口稳定**

新建 `backend/tests/test_relevance_gate.py`：

```python
"""Tests for RelevanceGate — 二分类相关性闸门。

设计意图:输出只有 bool,不含任何产品策略字段。这样接入 BERT 时训练目标
不需要随产品迭代变动。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.relevance_gate import RelevanceGate
from models.utterance import Utterance


def _utt(text: str, speaker: str) -> Utterance:
    return Utterance(id="u_x", text=text, speaker=speaker, t_start=0.0, t_end=1.0)


def _stub_client(content: str):
    client = MagicMock()
    client.chat.completions.create = AsyncMock(
        return_value=MagicMock(choices=[MagicMock(message=MagicMock(content=content))])
    )
    return client


@pytest.mark.asyncio
async def test_relevance_true_returns_bool_true():
    gate = RelevanceGate(client=_stub_client("true"))
    assert await gate.is_relevant(_utt("违法解除赔多少？", "client")) is True


@pytest.mark.asyncio
async def test_relevance_false_returns_bool_false():
    gate = RelevanceGate(client=_stub_client("false"))
    assert await gate.is_relevant(_utt("律师你好", "client")) is False


@pytest.mark.asyncio
async def test_relevance_strips_punctuation_and_case():
    """Qwen 可能输出 "True." 或 "  YES " 这类噪声,gate 必须归一化。"""
    gate = RelevanceGate(client=_stub_client("True."))
    assert await gate.is_relevant(_utt("竞业限制最长多久", "client")) is True

    gate2 = RelevanceGate(client=_stub_client(" NO "))
    assert await gate2.is_relevant(_utt("好的我懂了", "client")) is False


@pytest.mark.asyncio
async def test_relevance_unparseable_defaults_false():
    """LLM 输出无法解析时按 False 处理:漏判一句的代价(画像兜底捞回)远小于
    误唤醒 HeavyAgent 的成本。"""
    gate = RelevanceGate(client=_stub_client("我不知道"))
    assert await gate.is_relevant(_utt("…", "client")) is False


@pytest.mark.asyncio
async def test_gate_contract_no_severity_no_intent_type():
    """红线契约:gate 的返回值类型是且仅是 bool。新增字段必须不通过 type check。"""
    gate = RelevanceGate(client=_stub_client("true"))
    result = await gate.is_relevant(_utt("劳动法第87条怎么说", "client"))
    assert isinstance(result, bool)
    # 不允许任何属性访问
    assert not hasattr(result, "severity")
    assert not hasattr(result, "intent_type")
```

- [ ] **Step 2: 跑测试确认失败**

```
cd backend && uv run pytest tests/test_relevance_gate.py -v
```
Expected: FAIL — `from agent.relevance_gate import RelevanceGate` 不存在。

- [ ] **Step 3: 在 `prompts.py` 顶部新增 relevance prompt**

打开 `backend/src/agent/prompts.py`，在 `build_role_aware_prompt` 函数**之前**插入：

```python
def build_relevance_prompt(speaker: str, text: str) -> str:
    """二分类相关性提示:判断这句话是否值得唤醒 HeavyAgent。

    设计契约:输出只是一个布尔。不要标签、不要 severity、不要 intent_type。
    标注者只看"法律/需求相关",产品策略变了不用重训。
    """
    return f"""你正在旁听律师与客户的劳动法律咨询。

判断当前这句话是否需要 AI 法律助手参与(法律问题、案件需求、需要法条/计算/策略)。

## 规则
- 寒暄、应答("好的""嗯""谢谢")→ false
- 律师的科普、引用法条、安慰客户、事实询问 → false(律师是专业人士,默认不打扰)
- 律师以第一人称显式求助("系统帮我…""AI 查一下…")→ true
- 客户陈述事实(月薪、工龄、入职日期等)→ false(交给画像提取,无需唤醒)
- 客户的法律提问("赔多少""能赢吗""怎么算")→ true
- 客户的转述("公司说我不胜任")→ false

只输出一个词:true 或 false。不要解释。

speaker: {speaker}
text: {text}
"""
```

注意:**保留** `build_role_aware_prompt` 不删（Task 8 才删），便于灰度迁移期间回看。

- [ ] **Step 4: 实现 `RelevanceGate`**

新建 `backend/src/agent/relevance_gate.py`：

```python
"""RelevanceGate — 二分类相关性闸门。

设计:接口只输出 bool,不出 severity、不出 intent_type。当前实现走 Qwen,
后续可无缝换为本地 BERT;调用方契约不变。
"""

from __future__ import annotations

from openai import AsyncOpenAI

from agent.llm_client import build_qwen_client
from agent.prompts import build_relevance_prompt
from config import QWEN_MODEL
from models.utterance import Utterance


class RelevanceGate:
    """单一职责:判断一句话是否需要唤醒 HeavyAgent。"""

    def __init__(self, client: AsyncOpenAI | None = None, model: str | None = None):
        self._client = client or build_qwen_client()
        if self._client is None:
            raise RuntimeError("RelevanceGate requires a valid LLM client. Set DASHSCOPE_API_KEY or pass a client.")
        self._model = model or QWEN_MODEL

    async def is_relevant(self, utt: Utterance) -> bool:
        prompt = build_relevance_prompt(speaker=utt.speaker or "uncertain", text=utt.text)
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=4,
                extra_body={"enable_thinking": False},
            )
            content = (response.choices[0].message.content or "").strip().lower().rstrip(".!,。")
        except Exception:
            # LLM 抖动按 False 处理,不唤醒 HA。画像兜底保证客户事实不丢。
            return False

        if content in ("true", "yes", "是", "需要"):
            return True
        return False
```

- [ ] **Step 5: 跑测试确认通过**

```
cd backend && uv run pytest tests/test_relevance_gate.py -v
```
Expected: 全部 PASS。

- [ ] **Step 6: 提交**

```bash
git add backend/src/agent/relevance_gate.py backend/src/agent/prompts.py backend/tests/test_relevance_gate.py
git commit -m "feat(agent): 新增 RelevanceGate 二分类闸门(将取代 IntentRouter)"
```

---

## Task 3: 子 Agent 工具（gated `deep_analysis` + 只读 `fetch_more_transcript`）

**Files:**
- Create: `backend/src/agent/child_tools.py`
- Create: `backend/tests/test_child_tools.py`

- [ ] **Step 1: 写失败测试 — gated 工具 & 只读窗口拉取**

新建 `backend/tests/test_child_tools.py`：

```python
"""Tests for child agent tools — deep_analysis (gated) + fetch_more_transcript (read-only)."""

from datetime import datetime

import pytest

from agent.child_tools import make_deep_analysis_tool, make_fetch_more_transcript_tool
from agent.context_store import ContextStore, ProfileEntry
from models.utterance import Utterance


@pytest.fixture
def populated_store():
    store = ContextStore()
    for i in range(20):
        store._utterances.append(
            Utterance(
                id=f"u_{i}",
                text=f"第{i}句",
                speaker="client" if i % 2 else "lawyer",
                t_start=float(i),
                t_end=float(i + 1),
                timestamp=datetime.now(),
            )
        )
    store._profile.append(ProfileEntry(key="月薪", value="25000", timestamp=1.0, source_utt_id="u_1"))
    return store


def test_deep_analysis_tool_requires_confirmation(populated_store):
    """deep_analysis 必须挂 requires_confirmation=True,否则 HITL 路径不会触发。"""
    tool = make_deep_analysis_tool(populated_store)
    # Agno 的 @tool 装饰后返回 Function;requires_confirmation 标志在函数对象上
    assert tool.requires_confirmation is True, "deep_analysis 必须 gated"


def test_deep_analysis_tool_args_include_preview_fields(populated_store):
    """tool 的入参 schema 必须包含 topic + rationale,作为律师卡片预览。"""
    tool = make_deep_analysis_tool(populated_store)
    params = tool.parameters or {}
    props = params.get("properties", {})
    assert "topic" in props, "topic 用于卡片标题"
    assert "rationale" in props, "rationale 用于卡片副标题"


def test_fetch_more_transcript_returns_text(populated_store):
    tool = make_fetch_more_transcript_tool(populated_store)
    result = tool.entrypoint(start_idx=0, end_idx=4)
    assert "第0句" in result
    assert "第3句" in result
    assert "第4句" not in result, "end_idx exclusive"


def test_fetch_more_transcript_is_read_only(populated_store):
    """fetch_more_transcript 调用前后 utterances/profile 必须无任何写入。"""
    before_utts = list(populated_store._utterances)
    before_profile = list(populated_store._profile)
    tool = make_fetch_more_transcript_tool(populated_store)
    tool.entrypoint(start_idx=0, end_idx=5)
    assert populated_store._utterances == before_utts
    assert populated_store._profile == before_profile


def test_fetch_more_transcript_clamps_range(populated_store):
    """越界索引必须安全 clamp,不能让 LLM 误传负数 / 巨大索引就崩。"""
    tool = make_fetch_more_transcript_tool(populated_store)
    # 越界不抛
    result = tool.entrypoint(start_idx=-5, end_idx=999)
    assert "第0句" in result
    assert "第19句" in result
```

- [ ] **Step 2: 跑测试确认失败**

```
cd backend && uv run pytest tests/test_child_tools.py -v
```
Expected: FAIL — module 不存在。

- [ ] **Step 3: 实现两个工具工厂**

新建 `backend/src/agent/child_tools.py`：

```python
"""HeavyAgent child 的两个工具:

- `deep_analysis`: gated。child 调它即触发 HITL pause,等律师确认后续跑。
  入参 (topic, rationale) 是给律师卡片的预览;实际深度分析逻辑在 confirm 后的
  continue_run 里由 LLM 自己推理(本工具不返回真实分析,只承担"暂停信号"语义)。
- `fetch_more_transcript`: 只读。child 默认窗口不够时主动调,拉更早转写切片。
"""

from __future__ import annotations

from agno.tools import tool

from agent.context_store import ContextStore


def make_deep_analysis_tool(ctx: ContextStore):
    """构造 gated 深度分析工具,闭包捕获 ctx。

    Agno 在 child 调用此 tool 时,因 requires_confirmation=True 而暂停 run。
    律师确认后,confirm() + continue_run 让 LLM 继续推理并产出实际深析文本——
    实际"深度分析"是 LLM 在后续推理里完成的,本函数体只在被真正放行后兜底返回一句话。
    """

    @tool(requires_confirmation=True)
    def deep_analysis(topic: str, rationale: str) -> str:
        """启动深度法律分析(需律师确认)。

        Args:
            topic: 这次深析要回答的核心问题,一句话,展示在律师卡片标题。
            rationale: 为什么需要深析(用全画像+全转写)。展示在卡片副标题。
        """
        return f"已就 {topic} 完成深度分析。"

    return deep_analysis


def make_fetch_more_transcript_tool(ctx: ContextStore):
    """构造只读的转写切片拉取工具。"""

    @tool
    def fetch_more_transcript(start_idx: int, end_idx: int) -> str:
        """按索引范围拉取更早/更宽的对话转写。只读,不写画像、不写上下文。

        Args:
            start_idx: 起始索引(包含),负数 clamp 到 0。
            end_idx: 结束索引(不包含),超过总长 clamp 到末尾。
        """
        history = ctx.get_full_history()
        n = len(history)
        s = max(0, start_idx)
        e = min(n, end_idx)
        if s >= e:
            return "(无)"
        lines = [f"[{u.speaker}] {u.text}" for u in history[s:e]]
        return "\n".join(lines)

    return fetch_more_transcript
```

- [ ] **Step 4: 跑测试确认通过**

```
cd backend && uv run pytest tests/test_child_tools.py -v
```
Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/src/agent/child_tools.py backend/tests/test_child_tools.py
git commit -m "feat(agent): 新增 child gated/read-only 工具(deep_analysis + fetch_more_transcript)"
```

---

## Task 4: HeavyAgent 重写 — 单一 `arun` + `acontinue_run`

**Files:**
- Modify: `backend/src/agent/heavy_agent.py`（重写）
- Modify: `backend/src/agent/prompts.py` — 替换 HA prompts
- Rewrite: `backend/tests/test_heavy_agent.py`

- [ ] **Step 1: 在 `prompts.py` 替换 HA prompts**

在 `prompts.py` 中找到 `get_system_prompt` 和 `get_quick_system_prompt`，替换为：

```python
def get_child_system_prompt() -> str:
    """HeavyAgent child 的系统提示:自决深浅 + 自决是否先问律师。"""
    return """你是一名专业的劳动仲裁法律顾问,正在旁听律师与客户的咨询。

你拥有以下工具,**自行判断要不要用**:
- `fetch_more_transcript(start_idx, end_idx)`: 当默认窗口看不到的早期内容
  对回答**确实必要**时,主动拉。窗口够用就不要拉,省 token。
- `deep_analysis(topic, rationale)`: 当问题需要全画像+多步推理才能答好
  (谈判策略、胜率评估、复杂法条交叉分析)时,调用此工具——它会**暂停你的运行**
  等律师确认。律师确认后你才会被唤醒继续推理。

对**简单查询**(法条直问、单步金额计算、模板推荐):直接 1-3 句话答完,
不要调 deep_analysis。

对**复杂问题**:先调一次 deep_analysis 暂停,topic 写清楚要分析什么,
rationale 写为什么不能浅答。律师确认后,你会被续跑继续,这时再产出
完整的(法律法规 / 计算方式 / 建议行动)三段式答案。
"""


def build_child_user_prompt(trigger_text: str, profile_summary: dict, recent_window: list) -> str:
    """构造 child 一次启动用的 user prompt:画像全量 + 最近 N 轮转写。"""
    from models.utterance import Utterance  # noqa: PLC0415

    facts = []
    for subject, kv in profile_summary.items():
        tag = f"[{subject}] " if subject else ""
        for k, v in kv.items():
            facts.append(f"- {tag}{k}: {v}")
    facts_str = "\n".join(facts) if facts else "(无)"

    history = []
    for u in recent_window:
        if isinstance(u, Utterance):
            history.append(f"[{u.speaker}] {u.text}")
    history_str = "\n".join(history) if history else "(无)"

    return f"""## 当前画像
{facts_str}

## 最近对话
{history_str}

## 触发当前响应的句子
{trigger_text}
"""
```

同时**保留** `get_system_prompt`/`get_quick_system_prompt`/`build_role_aware_prompt`（Task 8 才删，确保中间状态可跑测试）。

- [ ] **Step 2: 写失败测试 — `arun` 路径 + `acontinue_run` 路径**

完全重写 `backend/tests/test_heavy_agent.py`：

````python
"""Tests for HeavyAgent — 单一 arun + acontinue_run 路径。"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.context_store import ContextStore, ProfileEntry
from agent.heavy_agent import HeavyAgent
from models.utterance import Utterance


@pytest.fixture(autouse=True)
def _mock_env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    from agno.db.in_memory import InMemoryDb  # noqa: PLC0415
    from agent.db import reset_agno_db_for_tests  # noqa: PLC0415
    reset_agno_db_for_tests(replacement=InMemoryDb())


@pytest.fixture
def populated_store():
    store = ContextStore()
    store._utterances = [
        Utterance(id="u_0", text="律师你好", speaker="client", t_start=0.0, t_end=1.0, timestamp=datetime.now()),
        Utterance(id="u_1", text="月薪两万五", speaker="client", t_start=1.0, t_end=2.0, timestamp=datetime.now()),
    ]
    store._profile = [ProfileEntry(key="月薪", value="25000", timestamp=1.0, source_utt_id="u_1")]
    store._generation = 2
    return store


@pytest.mark.asyncio
async def test_arun_returns_run_output_with_status(populated_store):
    """arun 应返回 Agno RunOutput,带 status/is_paused/active_requirements。"""
    ha = HeavyAgent(populated_store, session_id="sess_1", user_id="user_1")

    fake_run = MagicMock()
    fake_run.is_paused = False
    fake_run.content = "N+1=工龄×月薪。"
    fake_run.run_id = "run_abc"

    with patch("agno.agent.Agent.arun", new=AsyncMock(return_value=fake_run)):
        utt = Utterance(id="u_2", text="N+1怎么算", speaker="client", t_start=2.0, t_end=3.0)
        result = await ha.arun(utt)

    assert result.is_paused is False
    assert "N+1" in result.content


@pytest.mark.asyncio
async def test_arun_passes_session_and_user_id_to_agno(populated_store):
    """session_id/user_id 必须传给 Agno Agent,否则 continue_run 时找不到 run。"""
    ha = HeavyAgent(populated_store, session_id="sess_x", user_id="user_x")

    captured = {}

    async def fake_arun(self, prompt, **kwargs):
        captured["session_id"] = self.session_id
        captured["user_id"] = self.user_id
        m = MagicMock()
        m.is_paused = False
        m.content = "ok"
        m.run_id = "r"
        return m

    with patch("agno.agent.Agent.arun", new=fake_arun):
        await ha.arun(Utterance(id="u_2", text="问", speaker="client", t_start=0.0, t_end=1.0))

    assert captured["session_id"] == "sess_x"
    assert captured["user_id"] == "user_x"


@pytest.mark.asyncio
async def test_acontinue_run_uses_continue_not_base(populated_store):
    """confirm 后必须走 Agno acontinue_run,而不是重新 arun(否则重复理解)。"""
    ha = HeavyAgent(populated_store, session_id="sess_1", user_id="user_1")

    fake_resumed = MagicMock()
    fake_resumed.is_paused = False
    fake_resumed.content = "深度分析:根据第87条…"
    fake_resumed.run_id = "run_abc"

    arun_mock = AsyncMock(side_effect=AssertionError("acontinue_run 不应再调 arun"))
    cont_mock = AsyncMock(return_value=fake_resumed)

    with patch("agno.agent.Agent.arun", new=arun_mock), patch(
        "agno.agent.Agent.acontinue_run", new=cont_mock
    ):
        result = await ha.acontinue_run(run_id="run_abc", requirements=[MagicMock()])

    assert "深度分析" in result.content
    cont_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_arun_when_child_pauses_returns_paused_run(populated_store):
    """child 调 gated deep_analysis → run.is_paused=True + active_requirements 非空。"""
    ha = HeavyAgent(populated_store, session_id="sess_1", user_id="user_1")

    req = MagicMock()
    req.tool_execution.tool_args = {"topic": "胜率评估", "rationale": "需要全画像"}
    fake_run = MagicMock()
    fake_run.is_paused = True
    fake_run.run_id = "run_abc"
    fake_run.active_requirements = [req]

    with patch("agno.agent.Agent.arun", new=AsyncMock(return_value=fake_run)):
        result = await ha.arun(Utterance(id="u_2", text="能赢吗", speaker="client", t_start=0.0, t_end=1.0))

    assert result.is_paused
    assert result.active_requirements[0].tool_execution.tool_args["topic"] == "胜率评估"
````

- [ ] **Step 3: 跑测试确认失败**

```
cd backend && uv run pytest tests/test_heavy_agent.py -v
```
Expected: FAIL — `HeavyAgent(...)` 不接受 `session_id`/`user_id`，没有 `arun`/`acontinue_run`。

- [ ] **Step 4: 重写 `heavy_agent.py`**

完全替换 `backend/src/agent/heavy_agent.py` 内容：

```python
"""HeavyAgent — Agno child agent 的薄 facade。

只暴露两件事:
- `arun(utt)`: 启动一次 run,返回 Agno RunOutput(含 is_paused/active_requirements)。
- `acontinue_run(run_id, requirements)`: 续跑同一 run,不重头理解。

"是否深析" 完全由 child 自己决定(调不调 gated `deep_analysis` 工具)。
HeavyAgent 不再有 analyze/analyze_quick 两条分支。
"""

from __future__ import annotations

from agno.agent import Agent
from agno.models.deepseek import DeepSeek

from agent.child_tools import make_deep_analysis_tool, make_fetch_more_transcript_tool
from agent.context_store import ContextStore
from agent.db import get_agno_db
from agent.llm_client import build_deepseek_client
from agent.prompts import build_child_user_prompt, get_child_system_prompt
from config import DEEPSEEK_MODEL
from models.utterance import Utterance

PROFILE_WINDOW_SIZE_FOR_CHILD = 10


def _build_model() -> DeepSeek:
    client = build_deepseek_client()
    if client is None:
        raise RuntimeError("HeavyAgent requires a valid LLM client. Set DEEPSEEK_API_KEY or pass a model.")
    return DeepSeek(id=DEEPSEEK_MODEL, api_key=client.api_key, base_url=str(client.base_url))


class HeavyAgent:
    """child agent facade。Agent 实例在构造期建一次,跨 arun/acontinue_run 复用——
    ctx 是引用语义,child_tools 的闭包不需要"刷新"。"""

    def __init__(
        self,
        ctx: ContextStore,
        session_id: str,
        user_id: str,
        model=None,
    ):
        self._ctx = ctx
        self._session_id = session_id
        self._user_id = user_id
        self._model = model or _build_model()
        self._db = get_agno_db()
        self._agent = Agent(
            model=self._model,
            instructions=get_child_system_prompt(),
            tools=[
                make_deep_analysis_tool(self._ctx),
                make_fetch_more_transcript_tool(self._ctx),
            ],
            db=self._db,
            session_id=self._session_id,
            user_id=self._user_id,
        )

    async def arun(self, trigger_utt: Utterance):
        """启动一次 run。返回 Agno RunOutput(含 is_paused/active_requirements/run_id)。"""
        prompt = build_child_user_prompt(
            trigger_text=trigger_utt.text,
            profile_summary=self._ctx.get_profile_summary(),
            recent_window=self._ctx.get_recent_window(PROFILE_WINDOW_SIZE_FOR_CHILD),
        )
        return await self._agent.arun(prompt)

    async def acontinue_run(self, run_id: str, requirements):
        """续跑同一个 paused run。requirements 由调用方在 confirm 前用 .confirm() 标记好。"""
        return await self._agent.acontinue_run(run_id=run_id, requirements=requirements)
```

- [ ] **Step 5: 顺带修 `ProfileAgent.extract` 的 type hint**

`ContextStore.get_profile_summary()` 返回 `dict[str, dict[str, str]]`（按 subject 分组），
但当前 `profile_agent.py` 把 `existing_profile` 标成 `dict[str, str]`——type hint 撒谎，
运行 OK 但读代码的人会被误导。`build_child_user_prompt` 假设嵌套结构，必须与之统一。

打开 `backend/src/agent/profile_agent.py:32-58`，把签名与 docstring 改为：

```python
async def extract(
    self,
    text: str,
    speaker: str | None,
    history: list,
    existing_profile: dict[str, dict[str, str]],
    utt_id: str = "",
) -> list[ProfileEntry]:
    """从窗口上下文中提取事实条目。

    Args:
        text: 当前发言原文。
        speaker: 说话人角色（lawyer/client/uncertain），None 时按 unknown 处理。
        history: 最近 n 轮对话窗口（list[Utterance]）。
        existing_profile: 已知事实摘要，按 subject 分组（subject → key → 最新 value）。
        utt_id: 关联的 utterance ID，用于溯源。

    Returns:
        新提取的 ProfileEntry 列表（已过滤疑问词和无效值）。
    """
```

`prompts.py:build_profile_prompt` 已经按嵌套结构遍历，无需改动。

- [ ] **Step 6: 跑测试确认通过**

```
cd backend && uv run pytest tests/test_heavy_agent.py tests/test_child_tools.py tests/test_relevance_gate.py -v
```
Expected: 全部 PASS。

- [ ] **Step 7: 提交**

```bash
git add backend/src/agent/heavy_agent.py backend/src/agent/prompts.py backend/src/agent/profile_agent.py backend/tests/test_heavy_agent.py
git commit -m "refactor(agent): HeavyAgent 改为 arun/acontinue_run 单路径,并对齐 ProfileAgent type hint"
```

---

## Task 5: Orchestrator 重写 — gate-only spawn + run-state 分支

**Files:**
- Modify: `backend/src/agent/orchestrator.py`（重写）
- Rewrite: `backend/tests/test_orchestrator.py`
- Modify: `backend/tests/conftest.py` — 替换 `mock_ir_client`

- [ ] **Step 1: 替换 conftest fixture**

修改 `backend/tests/conftest.py`，把 `mock_ir_client` 整段（约 89-108 行）替换为 `mock_relevance_gate`：

```python
@pytest.fixture
def mock_relevance_gate():
    """Factory fixture: 返回一个 RelevanceGate stub,可指定固定的 is_relevant 结果。"""

    def _make(is_relevant: bool = True):
        class StubGate:
            async def is_relevant(self, utt) -> bool:
                return is_relevant

        return StubGate()

    return _make
```

并把同一文件里**导入旧 `IntentResult`** 的行删掉（若有）。

- [ ] **Step 2: 写失败测试 — Orchestrator 新分支**

完全替换 `backend/tests/test_orchestrator.py` 内容（保留前面 imports 风格）。先写一组覆盖核心分支的测试：

```python
"""Tests for Orchestrator — gate-only spawn + run-state 反应。"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from agent.context_store import ContextStore
from agent.orchestrator import Orchestrator
from models.utterance import Utterance


@pytest.fixture(autouse=True)
def _mock_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    from agno.db.in_memory import InMemoryDb  # noqa: PLC0415
    from agent.db import reset_agno_db_for_tests  # noqa: PLC0415
    reset_agno_db_for_tests(replacement=InMemoryDb())


@pytest_asyncio.fixture
async def store():
    ctx = ContextStore()
    await ctx.start_profile_worker()
    return ctx


def _completed_run(content: str, run_id: str = "run_1"):
    r = MagicMock()
    r.is_paused = False
    r.content = content
    r.run_id = run_id
    return r


def _paused_run(topic: str, rationale: str, run_id: str = "run_1"):
    req = MagicMock()
    req.tool_execution.tool_args = {"topic": topic, "rationale": rationale}
    r = MagicMock()
    r.is_paused = True
    r.run_id = run_id
    r.active_requirements = [req]
    return r


@pytest.mark.asyncio
async def test_gate_false_does_not_spawn_child(store, mock_relevance_gate):
    """relevance=false → 不 spawn,但 PA 仍跑(画像兜底)。"""
    gate = mock_relevance_gate(is_relevant=False)
    pa = MagicMock()
    pa.extract = AsyncMock(return_value=[])
    ha = MagicMock()
    ha.arun = AsyncMock(side_effect=AssertionError("relevance=false 不应 spawn"))

    orch = Orchestrator(store, gate=gate, pa=pa, ha=ha)
    orch.set_suggestion_callback(lambda t, m: None)

    utt = Utterance(id="u_1", text="好的", speaker="client", t_start=0.0, t_end=1.0)
    await orch.handle_utterance(utt)
    await asyncio.sleep(0.1)

    pa.extract.assert_awaited_once()
    ha.arun.assert_not_awaited()


@pytest.mark.asyncio
async def test_gate_true_completed_run_emits_ready(store, mock_relevance_gate):
    """relevance=true + child completed(未踩 gated)→ 直接推 ready。"""
    gate = mock_relevance_gate(is_relevant=True)
    pa = MagicMock()
    pa.extract = AsyncMock(return_value=[])
    ha = MagicMock()
    ha.arun = AsyncMock(return_value=_completed_run("法条第47条…"))

    orch = Orchestrator(store, gate=gate, pa=pa, ha=ha)
    suggestions = []
    orch.set_suggestion_callback(lambda t, m: suggestions.append((t, m)))

    await orch.handle_utterance(Utterance(id="u_1", text="N+1怎么算", speaker="client", t_start=0.0, t_end=1.0))
    await asyncio.sleep(0.1)

    assert len(suggestions) == 1
    text, meta = suggestions[0]
    assert "第47条" in text
    assert meta["kind"] == "ready"


@pytest.mark.asyncio
async def test_gate_true_paused_run_emits_pending_with_preview(store, mock_relevance_gate):
    """child 踩 gated → emit pending,meta.preview 来自 tool_args。"""
    gate = mock_relevance_gate(is_relevant=True)
    pa = MagicMock()
    pa.extract = AsyncMock(return_value=[])
    ha = MagicMock()
    ha.arun = AsyncMock(return_value=_paused_run("胜率评估", "需要全画像与多步推理"))

    orch = Orchestrator(store, gate=gate, pa=pa, ha=ha)
    suggestions = []
    orch.set_suggestion_callback(lambda t, m: suggestions.append((t, m)))

    await orch.handle_utterance(Utterance(id="u_1", text="能赢吗", speaker="client", t_start=0.0, t_end=1.0))
    await asyncio.sleep(0.1)

    assert len(suggestions) == 1
    text, meta = suggestions[0]
    assert text is None
    assert meta["kind"] == "pending"
    assert "request_id" in meta
    assert meta["preview"]["topic"] == "胜率评估"
    assert meta["preview"]["rationale"] == "需要全画像与多步推理"


@pytest.mark.asyncio
async def test_stale_completed_run_is_dropped(store, mock_relevance_gate):
    """child 在飞期间又有新 utterance 进来 → 该次完成的回答 stale,不推送。"""
    gate = mock_relevance_gate(is_relevant=True)
    pa = MagicMock()
    pa.extract = AsyncMock(return_value=[])
    ha = MagicMock()

    finished = asyncio.Event()

    async def slow_arun(utt):
        await finished.wait()
        return _completed_run("迟到的答案")

    ha.arun = slow_arun

    orch = Orchestrator(store, gate=gate, pa=pa, ha=ha)
    suggestions = []
    orch.set_suggestion_callback(lambda t, m: suggestions.append((t, m)))

    # 第一句触发慢 child;还没完成就来第二句让 generation 走远
    await orch.handle_utterance(Utterance(id="u_1", text="问题A", speaker="client", t_start=0.0, t_end=1.0))
    await asyncio.sleep(0.05)
    await orch.handle_utterance(Utterance(id="u_2", text="问题B", speaker="client", t_start=1.0, t_end=2.0))
    finished.set()
    await asyncio.sleep(0.1)

    # 旧 child 完成时 generation 已不匹配,不应出现在结果里
    ready = [(t, m) for t, m in suggestions if m["kind"] == "ready"]
    assert "迟到的答案" not in [t for t, _ in ready]


@pytest.mark.asyncio
async def test_profile_fallback_when_gate_false(store, mock_relevance_gate):
    """gate=false 不 gate PA:含关键事实的 client 句仍进画像。"""
    gate = mock_relevance_gate(is_relevant=False)
    pa = MagicMock()

    from agent.context_store import ProfileEntry  # noqa: PLC0415
    pa.extract = AsyncMock(return_value=[ProfileEntry(key="入职日期", value="2019-03", timestamp=0.0, source_utt_id="u_1")])

    ha = MagicMock()
    orch = Orchestrator(store, gate=gate, pa=pa, ha=ha)
    orch.set_suggestion_callback(lambda t, m: None)

    await orch.handle_utterance(Utterance(id="u_1", text="我2019年3月入职的", speaker="client", t_start=0.0, t_end=1.0))
    await asyncio.sleep(0.1)

    profile = store.get_profile()
    assert any(e.key == "入职日期" for e in profile)


@pytest.mark.asyncio
async def test_lawyer_skips_pa_but_still_runs_gate(store, mock_relevance_gate):
    """律师发言:不调 PA,但仍过 gate(律师可能显式求助)。"""
    gate_calls = []

    class SpyGate:
        async def is_relevant(self, utt):
            gate_calls.append(utt.speaker)
            return False

    pa = MagicMock()
    pa.extract = AsyncMock(return_value=[])
    ha = MagicMock()

    orch = Orchestrator(store, gate=SpyGate(), pa=pa, ha=ha)
    orch.set_suggestion_callback(lambda t, m: None)

    await orch.handle_utterance(Utterance(id="u_1", text="您工作多久了？", speaker="lawyer", t_start=0.0, t_end=1.0))
    await asyncio.sleep(0.05)

    assert gate_calls == ["lawyer"]
    pa.extract.assert_not_called()


@pytest.mark.asyncio
async def test_uncertain_speaker_treated_as_client(store, mock_relevance_gate):
    """声纹 uncertain 归一为 client,与旧契约保持一致。"""
    gate = mock_relevance_gate(is_relevant=False)
    pa = MagicMock()
    pa.extract = AsyncMock(return_value=[])
    ha = MagicMock()

    orch = Orchestrator(store, gate=gate, pa=pa, ha=ha)
    orch.set_suggestion_callback(lambda t, m: None)

    await orch.handle_utterance(Utterance(id="u_1", text="两年三个月", speaker="uncertain", t_start=0.0, t_end=1.0))
    await asyncio.sleep(0.05)

    assert pa.extract.call_args.kwargs["speaker"] == "client"
    assert store.get_full_history()[-1].speaker == "client"


@pytest.mark.asyncio
async def test_bus_consumer_survives_handler_exception(store):
    """gate 抛异常不应杀死 bus consumer。"""
    from agent.bus import UtteranceBus  # noqa: PLC0415

    class FlakyGate:
        def __init__(self):
            self.calls = 0

        async def is_relevant(self, utt):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("LLM timeout")
            return True

    class StubPA:
        async def extract(self, **kwargs):
            return []

    class StubHA:
        async def arun(self, utt):
            return _completed_run(f"答: {utt.text}")

    bus = UtteranceBus()
    orch = Orchestrator(store, gate=FlakyGate(), pa=StubPA(), ha=StubHA())
    orch.attach_bus(bus)

    suggestions = []
    orch.set_suggestion_callback(lambda t, m: suggestions.append((t, m)))
    await orch.start()

    await bus.put(Utterance(id="u_1", text="第一句", speaker="client", t_start=0.0, t_end=1.0))
    await bus.put(Utterance(id="u_2", text="第二句", speaker="client", t_start=1.0, t_end=2.0))
    await asyncio.sleep(0.3)
    await orch.shutdown()

    ready = [m for _, m in suggestions if m["kind"] == "ready"]
    assert len(ready) == 1, "第二句应正常处理"
    assert ready[0]["utt_id"] == "u_2"
```

- [ ] **Step 3: 跑测试确认失败**

```
cd backend && uv run pytest tests/test_orchestrator.py -v
```
Expected: 全部 FAIL — `Orchestrator(..., gate=...)` 参数名不对、`meta["preview"]` 不存在等。

- [ ] **Step 4: 重写 `orchestrator.py`**

完全替换 `backend/src/agent/orchestrator.py`：

```python
"""Orchestrator — 纯机械管道:零语义判断,只对 RelevanceGate 与 child run 状态反应。

控制流:
1. 每条 utterance → append context(单写者), 并行触发 gate + PA(仅 client 句)
2. PA 结果异步入画像写口(单写者)
3. gate=true → spawn child run(并发); gate=false → 仅记录,不响应
4. child run 完成:
   - 未 paused → 直推 ready(stale generation 时丢弃)
   - paused(踩了 gated deep_analysis)→ emit pending,等律师 confirm
5. confirm → continue_run 续跑同一 run;dismiss/超时 → abandon
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from agno.run.base import RunStatus

from agent.context_store import ContextStore
from agent.heavy_agent import HeavyAgent
from agent.profile_agent import ProfileAgent
from agent.relevance_gate import RelevanceGate
from config import RUN_TIMEOUT
from models.utterance import Utterance

logger = logging.getLogger(__name__)

PROFILE_WINDOW_SIZE = 6


@dataclass
class PendingRequest:
    """挂起的 child run。

    `run_output` 是 Agno RunOutput 引用,confirm/reject 时直接调它的
    `.requirements[i].confirm()/.reject()`(纯内存操作,Agno db 状态由
    `agent.acontinue_run(...)` 自己 upsert)。**不序列化**——RunOutput 含
    模型/工具/消息等大量运行期对象,跨进程恢复也无 Agno API 支持。
    """

    request_id: str
    run_id: str
    utt_id: str
    generation: int
    preview: dict
    # wall-clock 秒。TTL 比较用 time.time() 统一基线,跨进程也有意义。
    created_at: float = field(default_factory=time.time)
    # 仅内存。to_dict / from_dict 不带这个字段。
    run_output: Any = None

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "run_id": self.run_id,
            "utt_id": self.utt_id,
            "generation": self.generation,
            "preview": self.preview,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PendingRequest":
        # run_output 永远为 None(不可序列化),恢复出来的 pending 没有可
        # confirm 的 requirements,只能等 TTL sweep 自然过期或主动 dismiss。
        # Orchestrator.from_dict 会决定要不要把它带回来,见下方注释。
        return cls(
            request_id=d["request_id"],
            run_id=d["run_id"],
            utt_id=d["utt_id"],
            generation=d["generation"],
            preview=d.get("preview", {}),
            created_at=d.get("created_at", time.time()),
            run_output=None,
        )


class Orchestrator:
    def __init__(
        self,
        ctx: ContextStore,
        gate: RelevanceGate | None = None,
        pa: ProfileAgent | None = None,
        ha: HeavyAgent | None = None,
        session_id: str = "default",
        user_id: str = "default",
    ):
        self._ctx = ctx
        self._gate = gate or RelevanceGate()
        self._pa = pa or ProfileAgent()
        self._ha = ha or HeavyAgent(ctx, session_id=session_id, user_id=user_id)
        self._suggestion_callback = None
        self._pending: dict[str, PendingRequest] = {}
        self._inflight: set[asyncio.Task] = set()  # 在飞 child task,防 GC + 收集异常
        self._bus = None
        self._bus_task = None
        self._ttl_task = None

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def attach_bus(self, bus) -> None:
        self._bus = bus

    def set_suggestion_callback(self, callback) -> None:
        self._suggestion_callback = callback

    async def start(self) -> None:
        await self._ctx.start_profile_worker()
        if self._bus is not None and self._bus_task is None:
            self._bus_task = asyncio.create_task(self._consume_bus())
        if self._ttl_task is None:
            self._ttl_task = asyncio.create_task(self._sweep_pending_ttl())

    async def shutdown(self) -> None:
        await self._ctx.stop_profile_worker()
        for task in (self._bus_task, self._ttl_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        # 等所有在飞 child task 结束(它们已经走 logger,不会抛到这里)
        if self._inflight:
            await asyncio.gather(*self._inflight, return_exceptions=True)
        self._inflight.clear()
        self._pending.clear()

    # ------------------------------------------------------------------
    # main path
    # ------------------------------------------------------------------

    async def handle_utterance(self, utt: Utterance) -> int:
        # speaker 归一:None 是 bug 信号,uncertain 是合法的"非律师"标签
        if utt.speaker is None:
            logger.warning("utterance %s speaker=None,声纹链路可能未接通(已降级为 client)", utt.id)
        if utt.speaker not in ("lawyer", "client"):
            utt.speaker = "client"

        generation = await self._ctx.append_utterance(utt)

        # gate 与 PA 并行,gate 不阻塞 PA(画像兜底)
        gate_task = asyncio.create_task(self._safe_gate(utt))
        pa_task = None
        if utt.speaker != "lawyer":
            pa_task = asyncio.create_task(
                self._pa.extract(
                    text=utt.text,
                    speaker=utt.speaker,
                    history=self._ctx.get_recent_window(n=PROFILE_WINDOW_SIZE),
                    existing_profile=self._ctx.get_profile_summary(),
                    utt_id=utt.id,
                )
            )

        if pa_task is not None:
            try:
                entries = await pa_task
                if entries:
                    for entry in entries:
                        entry.timestamp = utt.t_start
                    await self._ctx.enqueue_profile_update(utt.id, entries)
            except Exception as e:
                # 画像兜底失败要大声说,不能静默:CLAUDE.md 第 12 条
                logger.warning("ProfileAgent.extract failed for utt %s: %s", utt.id, e)

        should_spawn = await gate_task
        if should_spawn:
            self._spawn_inflight(self._run_child(utt, generation), label=f"child:{utt.id}")

        return generation

    def _spawn_inflight(self, coro, *, label: str) -> None:
        """统一的 fire-and-forget 入口:保存引用防 GC + 异常入 log。"""
        task = asyncio.create_task(coro, name=label)
        self._inflight.add(task)

        def _done(t: asyncio.Task) -> None:
            self._inflight.discard(t)
            if t.cancelled():
                return
            exc = t.exception()
            if exc is not None:
                logger.exception("inflight task %s crashed", label, exc_info=exc)

        task.add_done_callback(_done)

    async def _safe_gate(self, utt: Utterance) -> bool:
        try:
            return await self._gate.is_relevant(utt)
        except Exception as e:
            # gate 抖动按 False 处理(画像兜底捞回事实),但必须留下抖动证据
            logger.warning("RelevanceGate failed for utt %s: %s", utt.id, e)
            return False

    async def _run_child(self, utt: Utterance, generation: int) -> None:
        try:
            run = await asyncio.wait_for(self._ha.arun(utt), timeout=RUN_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning("child run timeout (>%ss) for utt %s", RUN_TIMEOUT, utt.id)
            return
        except Exception:
            logger.exception("child run failed for utt %s", utt.id)
            return

        # 两个分支都要查 generation:paused 也可能因新 utterance 而 stale,
        # 此时弹 pending 卡片只会污染新对话。
        if self._ctx.get_generation() != generation:
            return

        if not run.is_paused:
            await self._emit({"kind": "ready", "utt_id": utt.id}, text=getattr(run, "content", None))
            return

        # paused: 取首个 requirement 的预览给律师
        req = run.active_requirements[0] if run.active_requirements else None
        preview = {}
        if req is not None and req.tool_execution is not None:
            preview = dict(req.tool_execution.tool_args or {})

        request_id = f"req_{uuid.uuid4().hex[:8]}"
        self._pending[request_id] = PendingRequest(
            request_id=request_id,
            run_id=run.run_id,
            utt_id=utt.id,
            generation=generation,
            preview=preview,
            run_output=run,  # 保留引用,confirm/reject 时用
        )
        await self._emit(
            {
                "kind": "pending",
                "utt_id": utt.id,
                "request_id": request_id,
                "preview": preview,
            },
            text=None,
        )

    # ------------------------------------------------------------------
    # confirm / dismiss / cleanup
    # ------------------------------------------------------------------

    async def confirm_analysis(self, request_id: str) -> bool:
        pending = self._pending.pop(request_id, None)
        if pending is None:
            return False
        if pending.run_output is None:
            # 从 db 恢复出来的 pending 没有 RunOutput 引用 → 无法 confirm,
            # 直接 abandon。前端应当避免对恢复后的 pending 发 confirm。
            await self._abandon_run(pending)
            return False

        if self._ctx.get_generation() != pending.generation:
            await self._abandon_run(pending)
            return False

        # 在内存里 confirm 所有 active_requirement,再调 acontinue_run。
        # Agno 文档约定:requirements 直接从 run_output.requirements 传入。
        for req in pending.run_output.active_requirements or []:
            try:
                req.confirm()
            except Exception:
                logger.warning("requirement.confirm() failed", exc_info=True)

        try:
            run = await asyncio.wait_for(
                self._ha.acontinue_run(
                    run_id=pending.run_id,
                    requirements=pending.run_output.requirements,
                ),
                timeout=RUN_TIMEOUT,
            )
        except Exception:
            logger.exception("continue_run failed for run_id=%s", pending.run_id)
            await self._abandon_run(pending)
            return False

        text = getattr(run, "content", None)
        await self._emit({"kind": "ready", "utt_id": pending.utt_id, "request_id": request_id}, text=text)
        return True

    async def dismiss_pending(self, request_id: str) -> None:
        pending = self._pending.pop(request_id, None)
        if pending is None:
            return
        await self._abandon_run(pending)

    async def _abandon_run(self, pending: PendingRequest) -> None:
        """放弃挂起 run:reject 内存中的 requirements + 把 Agno db 的 run 状态标 CANCELLED。

        注意:Agno SqliteDb/PostgresDb 没有 get_run/delete_run 这类 API。
        真实可用 API 是 update_approval_run_status(run_id, RunStatus.*) 与
        delete_approval(approval_id)。这里只动 run_status,approvals 行让
        Agno 内部 GC,避免我们替它管 approval_id 生命周期。
        """
        # 1) 内存中 reject(若有 run_output)
        if pending.run_output is not None:
            for req in pending.run_output.active_requirements or []:
                try:
                    req.reject("abandoned")
                except Exception:
                    pass
        # 2) db 中把 run 标 CANCELLED,避免 paused 状态永久滞留
        db = self._ha._db
        try:
            if hasattr(db, "update_approval_run_status"):
                db.update_approval_run_status(run_id=pending.run_id, run_status=RunStatus.cancelled)
        except Exception:
            logger.warning(
                "update_approval_run_status failed for run_id=%s", pending.run_id, exc_info=True
            )

    async def _sweep_pending_ttl(self) -> None:
        """后台扫描:挂起 run 超过 PENDING_TTL 自动 abandon。
        每轮循环重读 config.PENDING_TTL,让 monkeypatch 在测试里生效。"""
        while True:
            try:
                import config as _cfg  # noqa: PLC0415
                ttl = _cfg.PENDING_TTL
                await asyncio.sleep(max(0.05, min(ttl / 4, 30)))
            except asyncio.CancelledError:
                break
            now = time.time()
            stale = [rid for rid, p in self._pending.items() if now - p.created_at > ttl]
            for rid in stale:
                pending = self._pending.pop(rid, None)
                if pending:
                    await self._abandon_run(pending)

    # ------------------------------------------------------------------
    # plumbing
    # ------------------------------------------------------------------

    async def _consume_bus(self) -> None:
        while True:
            try:
                utt = await self._bus.get()
                await self.handle_utterance(utt)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("handle_utterance failed")

    async def _emit(self, meta: dict, text: str | None) -> None:
        if self._suggestion_callback is None:
            return
        result = self._suggestion_callback(text, meta)
        if asyncio.iscoroutine(result):
            await result

    # ------------------------------------------------------------------
    # serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "pending": [p.to_dict() for p in self._pending.values()],
            "ctx": self._ctx.to_dict(),
        }

    @classmethod
    def from_dict(
        cls,
        d: dict,
        ctx: ContextStore | None = None,
        session_id: str = "default",
        user_id: str = "default",
        gate: RelevanceGate | None = None,
        pa: ProfileAgent | None = None,
        ha: HeavyAgent | None = None,
    ):
        """从快照恢复 Orchestrator。

        **不恢复 pending**:RunOutput 含不可序列化的运行期对象(模型/工具
        实例/消息流引用),跨进程恢复后无法 confirm。如果旧进程崩溃时有
        挂起 run,Agno db 里的 paused 状态由其内部 GC 与本类的 TTL sweep
        共同清理。前端 UX 上,会话恢复后律师只能在新对话里重新触发。
        """
        if ctx is None:
            ctx = ContextStore.from_dict(d["ctx"])
        inst = cls.__new__(cls)
        inst._ctx = ctx
        inst._gate = gate or RelevanceGate()
        inst._pa = pa or ProfileAgent()
        inst._ha = ha or HeavyAgent(ctx, session_id=session_id, user_id=user_id)
        inst._suggestion_callback = None
        inst._pending = {}  # 故意丢弃 d.get("pending", []),见 docstring
        inst._bus = None
        inst._bus_task = None
        inst._ttl_task = None
        return inst
```

- [ ] **Step 5: 跑测试确认通过**

```
cd backend && uv run pytest tests/test_orchestrator.py tests/test_heavy_agent.py tests/test_child_tools.py tests/test_relevance_gate.py -v
```
Expected: 全部 PASS。

- [ ] **Step 6: 提交**

```bash
git add backend/src/agent/orchestrator.py backend/tests/test_orchestrator.py backend/tests/conftest.py
git commit -m "refactor(agent): Orchestrator 改为 gate-only spawn + run-state 分支"
```

---

## Task 6: HITL 清理路径 — confirm / dismiss / abandon / timeout 无泄漏

**Files:**
- Modify: `backend/src/agent/orchestrator.py`（补全 confirm/dismiss 实现细节）
- Create: `backend/tests/test_hitl_cleanup.py`

- [ ] **Step 1: 写失败测试 — 四条清理路径**

新建 `backend/tests/test_hitl_cleanup.py`：

```python
"""HITL 清理无泄漏:confirm / dismiss / 超时 / stale generation 四条路径
都必须把 pending 映射清空,并通过 Agno 真实 API 把 paused run 标 CANCELLED。

红线契约:不允许调用 db.get_run / db.delete_run(它们在 Agno 2.6.x 不存在)。"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from agno.run.base import RunStatus

from agent.context_store import ContextStore
from agent.orchestrator import Orchestrator
from models.utterance import Utterance


@pytest.fixture(autouse=True)
def _mock_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("PENDING_TTL", "0.2")
    # _sweep_pending_ttl 每轮重读 config.PENDING_TTL,在这里也直接改一下
    # 模块级常量,确保已经 import 过的代码也能拿到新值
    import config as _cfg  # noqa: PLC0415
    _cfg.PENDING_TTL = 0.2

    from agno.db.in_memory import InMemoryDb  # noqa: PLC0415
    from agent.db import reset_agno_db_for_tests  # noqa: PLC0415
    reset_agno_db_for_tests(replacement=InMemoryDb())


@pytest_asyncio.fixture
async def store():
    ctx = ContextStore()
    await ctx.start_profile_worker()
    return ctx


def _make_paused_ha(topic="x", rationale="y", run_id="run_1"):
    """构造一个会进入 paused 的 HA stub。db spy 只 mock 真实 API。"""
    req = MagicMock()
    req.tool_execution.tool_args = {"topic": topic, "rationale": rationale}
    req.confirm = MagicMock()
    req.reject = MagicMock()
    run = MagicMock()
    run.is_paused = True
    run.run_id = run_id
    run.active_requirements = [req]
    run.requirements = [req]  # continue_run 传入用

    resumed = MagicMock(is_paused=False, content="深度分析完成", run_id=run_id)
    ha = MagicMock()
    ha.arun = AsyncMock(return_value=run)
    ha.acontinue_run = AsyncMock(return_value=resumed)
    # 严格 spec:只允许真实 API 名;访问 get_run / delete_run 会 AttributeError
    db = MagicMock(spec=["update_approval_run_status"])
    db.update_approval_run_status = MagicMock()
    ha._db = db
    return ha, req, db


class _StubGate:
    async def is_relevant(self, utt):
        return True


class _StubPA:
    async def extract(self, **kwargs):
        return []


async def _spawn_pending(orch):
    suggestions = []
    orch.set_suggestion_callback(lambda t, m: suggestions.append((t, m)))
    await orch.handle_utterance(Utterance(id="u_1", text="能赢吗", speaker="client", t_start=0.0, t_end=1.0))
    await asyncio.sleep(0.1)
    return [m for _, m in suggestions if m["kind"] == "pending"][0]["request_id"]


@pytest.mark.asyncio
async def test_confirm_path_continues_run_without_db_lookup(store):
    """confirm 成功路径:req.confirm 被调 + acontinue_run 用 run_output.requirements 续跑。
    db.update_approval_run_status 不应被触发(成功路径不需要标 CANCELLED)。"""
    ha, req, db = _make_paused_ha()
    orch = Orchestrator(store, gate=_StubGate(), pa=_StubPA(), ha=ha)

    rid = await _spawn_pending(orch)
    assert rid in orch._pending

    ok = await orch.confirm_analysis(rid)
    assert ok
    assert rid not in orch._pending
    req.confirm.assert_called_once()
    ha.acontinue_run.assert_awaited_once()
    kwargs = ha.acontinue_run.await_args.kwargs
    assert kwargs["run_id"] == "run_1"
    assert kwargs["requirements"] == [req], "必须传 run_output.requirements,不许从 db 重拉"
    db.update_approval_run_status.assert_not_called()


@pytest.mark.asyncio
async def test_dismiss_rejects_and_cancels_db_status(store):
    """dismiss:reject 内存 requirement + db.update_approval_run_status(CANCELLED)。"""
    ha, req, db = _make_paused_ha()
    orch = Orchestrator(store, gate=_StubGate(), pa=_StubPA(), ha=ha)

    rid = await _spawn_pending(orch)
    await orch.dismiss_pending(rid)

    assert rid not in orch._pending
    req.reject.assert_called_once()
    db.update_approval_run_status.assert_called_once_with(
        run_id="run_1", run_status=RunStatus.cancelled
    )
    ha.acontinue_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_confirm_abandons_run(store):
    """律师在新对话进行后才确认旧 pending → abandon,不调 continue_run,db 标 CANCELLED。"""
    ha, req, db = _make_paused_ha()
    orch = Orchestrator(store, gate=_StubGate(), pa=_StubPA(), ha=ha)

    rid = await _spawn_pending(orch)
    await store.append_utterance(Utterance(id="u_2", text="别的话", speaker="client", t_start=2.0, t_end=3.0))
    await store.append_utterance(Utterance(id="u_3", text="还有", speaker="client", t_start=3.0, t_end=4.0))

    ok = await orch.confirm_analysis(rid)
    assert ok is False
    assert rid not in orch._pending
    ha.acontinue_run.assert_not_awaited()
    db.update_approval_run_status.assert_called_once_with(
        run_id="run_1", run_status=RunStatus.cancelled
    )


@pytest.mark.asyncio
async def test_ttl_sweep_abandons_stale_pending(store):
    """挂起超过 PENDING_TTL(wall clock)后,后台扫描自动 abandon。"""
    ha, req, db = _make_paused_ha()
    orch = Orchestrator(store, gate=_StubGate(), pa=_StubPA(), ha=ha)
    await orch.start()

    rid = await _spawn_pending(orch)
    assert rid in orch._pending

    await asyncio.sleep(0.5)

    assert rid not in orch._pending, "TTL 扫描应清掉 stale pending"
    db.update_approval_run_status.assert_called_once_with(
        run_id="run_1", run_status=RunStatus.cancelled
    )
    await orch.shutdown()


@pytest.mark.asyncio
async def test_restored_pending_is_dropped_to_avoid_stale_runoutput(store):
    """from_dict 必须丢弃序列化的 pending —— RunOutput 不可序列化,
    若硬恢复,confirm 路径会因 run_output=None 而无 requirement 可 confirm。"""
    ha, _, _ = _make_paused_ha()
    orch = Orchestrator(store, gate=_StubGate(), pa=_StubPA(), ha=ha)
    rid = await _spawn_pending(orch)
    snapshot = orch.to_dict()
    assert any(p["request_id"] == rid for p in snapshot["pending"]), "snapshot 仍记录 pending(供审计)"

    restored = Orchestrator.from_dict(
        snapshot, ctx=store, gate=_StubGate(), pa=_StubPA(), ha=ha
    )
    assert restored._pending == {}, "恢复后必须为空,避免对失效 RunOutput 调 confirm"
```

- [ ] **Step 2: 跑测试确认失败 / 暴露漏洞**

```
cd backend && uv run pytest tests/test_hitl_cleanup.py -v
```
Expected: 至少 `test_ttl_sweep_abandons_stale_pending` 或 `test_restored_pending_is_dropped_to_avoid_stale_runoutput` 会 FAIL（取决于 Task 5 的初版实现细节）。

- [ ] **Step 3: 在 `orchestrator.py` 中补强 cleanup 路径**

核对 Task 5 中已经写好的实现是否满足下列契约（应该已经满足，本步骤是审计 + 必要时补漏）：

1. `_abandon_run` **不再**调 `db.get_run / db.delete_run`（这两个 API 在 Agno 2.6.x 上**不存在**）。真实可用 API：`db.update_approval_run_status(run_id, RunStatus.cancelled)`。
2. `_abandon_run` 接收 `PendingRequest` 而非 `run_id`——这样能拿到内存里的 `pending.run_output` 调 `.requirements[i].reject()`。
3. `confirm_analysis` 用 `pending.run_output.requirements` 传给 `acontinue_run`，**不从 db 重拉**。
4. `_sweep_pending_ttl` 每轮重读 `config.PENDING_TTL`（让 monkeypatch 在测试里生效）；时间比较用 `time.time()` 与 `pending.created_at`，**不用 monotonic**。
5. `Orchestrator.from_dict` 把 `_pending` 置空，**不**从快照里恢复（RunOutput 不可序列化）。

参考实现片段（与 Task 5 一致）：

```python
async def _sweep_pending_ttl(self) -> None:
    while True:
        try:
            import config as _cfg  # noqa: PLC0415
            ttl = _cfg.PENDING_TTL
            await asyncio.sleep(max(0.05, min(ttl / 4, 30)))
        except asyncio.CancelledError:
            break
        now = time.time()
        stale = [rid for rid, p in self._pending.items() if now - p.created_at > ttl]
        for rid in stale:
            pending = self._pending.pop(rid, None)
            if pending:
                await self._abandon_run(pending)
```

- [ ] **Step 4: 跑测试确认通过**

```
cd backend && uv run pytest tests/test_hitl_cleanup.py tests/test_orchestrator.py -v
```
Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/src/agent/orchestrator.py backend/tests/test_hitl_cleanup.py
git commit -m "feat(agent): HITL 清理四条路径无泄漏(confirm/dismiss/stale/TTL)"
```

---

## Task 7: `main.py` 接线 + WS 协议字段切换

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/src/session/manager.py`（如需要传 session_id/user_id；只读即可）

> **WS 协议是 breaking change** —— `meta` 不再有 `severity / intent_type / law_domain / entities`，
> 改成 `preview: {topic, rationale}`。前端 `useWebSocket.ts` 必须配套改。**上线顺序约束**：
>
> 1. 前端 PR **先 merge 但不发布**，本地用旧后端跑通向下兼容（前端对缺失字段宽容处理）。
> 2. 后端 PR merge + 部署。
> 3. 前端发布。
>
> 若必须避免短暂"前新后旧"窗口的破坏面，可在 `on_suggestion` 临时同时输出新旧字段
> （旧字段填 `None`），等前端发布后下一次后端 PR 再把旧字段彻底删掉。本计划默认走
> 1-2-3 直切方案（不引入临时双写）。如选双写方案，在 Step 2 的 `on_suggestion` 里同时
> 塞 `severity=None, intent_type=None, law_domain=None, entities=[]`，并在 Task 8 推迟字段
> 移除。

- [ ] **Step 1: 读 main.py 确认要改的位置**

```
cd backend && grep -n "severity\|intent_type\|law_domain\|entities\|IntentRouter\|Orchestrator(ctx)\|Orchestrator.from_dict" main.py
```
Expected: 列出 `meta` 字典 + Orchestrator 构造 + restore 路径共 5-8 处。

- [ ] **Step 2: 修改 `on_suggestion` 回调,删除旧字段、加 preview**

打开 `backend/main.py`，找到 `on_suggestion` 函数体（约 102-131 行），整段替换为：

```python
    async def on_suggestion(text, meta):
        try:
            if meta.get("kind") == "pending":
                await ws.send_json({
                    "type": "suggestion.pending",
                    "text": None,
                    "meta": {
                        "utt_id": meta["utt_id"],
                        "request_id": meta["request_id"],
                        "preview": meta.get("preview", {}),
                    },
                })
            else:
                await ws.send_json({
                    "type": "suggestion.ready",
                    "text": text,
                    "meta": {
                        "utt_id": meta["utt_id"],
                        **({"request_id": meta["request_id"]} if "request_id" in meta else {}),
                    },
                })
        except (WebSocketDisconnect, RuntimeError):
            # WS 已断开,不应崩溃也不必告警(常规连接关闭)
            pass
        except Exception as exc:
            logger.warning("Suggestion callback failed: %s", exc)
```

- [ ] **Step 3: 把 Orchestrator 构造改为接收 session_id/user_id**

找到 `Orchestrator(ctx)` 与 `Orchestrator.from_dict(state.orchestrator, ctx=ctx)`（约 94-97 行），替换为：

```python
    if state.context_store and state.orchestrator:
        ctx = ContextStore.from_dict(state.context_store)
        orch = Orchestrator.from_dict(
            state.orchestrator, ctx=ctx, session_id=session_id, user_id="lawyer-default"
        )
    else:
        ctx = ContextStore()
        orch = Orchestrator(ctx, session_id=session_id, user_id="lawyer-default")
```

- [ ] **Step 4: 把 `dismiss_pending` 调用改为 await(它现在是 async)**

找到约 197 行：

```python
elif msg_type == "dismiss":
    request_id = msg.get("request_id")
    if request_id:
        orch.dismiss_pending(request_id)
```

改为：

```python
elif msg_type == "dismiss":
    request_id = msg.get("request_id")
    if request_id:
        await orch.dismiss_pending(request_id)
```

- [ ] **Step 5: 跑现有 e2e/集成测试,确认管道仍能起**

```
cd backend && uv run pytest tests/test_orchestrator.py tests/test_hitl_cleanup.py tests/session/ -v
```
Expected: 全部 PASS。

- [ ] **Step 6: 提交 + 在 commit 信息中标注前端协议变更**

```bash
git add backend/main.py
git commit -m "refactor(api): WS 协议 meta 改用 preview;移除 severity/intent_type/law_domain/entities(需前端配套)"
```

---

## Task 8: 清理 — 删除旧 IntentRouter / 旧 IntentResult / 旧 prompts / 旧分支

**Files:**
- Delete: `backend/src/agent/intent_router.py`
- Delete: `backend/tests/test_intent_router.py`
- Modify: `backend/src/agent/prompts.py` — 移除 `build_role_aware_prompt` / `get_system_prompt` / `get_quick_system_prompt`
- Modify: `backend/src/agent/__init__.py`（若 re-export 了 `IntentRouter` / `IntentResult`）

- [ ] **Step 1: 全局扫描确认无引用残留**

```
cd backend && grep -rn -E "\b(IntentRouter|IntentResult|build_role_aware_prompt|get_quick_system_prompt|analyze_quick)\b|HeavyAgent\.analyze\b|\.analyze\(" src/ tests/ main.py 2>/dev/null | grep -v ".pyc" | grep -v __pycache__
```
Expected: 仅出现在 `intent_router.py` / `test_intent_router.py` / `prompts.py` 中的待删处。如果出现在其他位置，必须先在那处用新接口替换再继续。

> 注：`\b` 与 `\.analyze\(` 避免命中 `audio.analyze(...)` / `pkg.analyzer(...)` 等无关方法。
> 如果命中里仍然有疑似误报，可进一步加 `--include="*.py"` 收紧。

- [ ] **Step 2: 删除旧文件**

```bash
rm backend/src/agent/intent_router.py backend/tests/test_intent_router.py
```

- [ ] **Step 3: 从 `prompts.py` 删除三个旧函数**

打开 `backend/src/agent/prompts.py`，删除：
- `build_role_aware_prompt(speaker, text)` 整个函数体
- `get_system_prompt()` 整个函数体
- `get_quick_system_prompt()` 整个函数体

保留：`build_relevance_prompt`、`build_profile_prompt`、`build_child_user_prompt`、`get_child_system_prompt`。

- [ ] **Step 4: 跑全套测试**

```
cd backend && uv run pytest -v
```
Expected: 全部 PASS。任何 import 错误说明 Step 1 的扫描漏了；回去补。

- [ ] **Step 5: 跑 ruff / 类型检查**

```
cd backend && uv run ruff check src/ tests/ main.py
```
Expected: 无错误。

- [ ] **Step 6: 提交**

```bash
git add -A backend/src/agent/ backend/tests/ backend/main.py
git commit -m "chore(agent): 移除旧 IntentRouter / IntentResult / severity 分支(被 RelevanceGate 取代)"
```

---

## Task 9: `fetch_more_transcript` 行为契约测试

**Files:**
- Modify: `backend/tests/test_orchestrator.py` — 追加一组用例
- 无源码改动

> 红线：测试必须真的调用 `fetch_more_transcript` 工具拿到的转写内容做拼接断言。
> 仅断言 mock 自己写死的字符串(`"早期"`/`"第87条"`)是无效测试,业务逻辑变了不会挂 ——
> 违反 CLAUDE.md 第 9 条。

- [ ] **Step 1: 写测试 — child 真实调用 fetch_more_transcript 拉到的内容能被透传**

在 `backend/tests/test_orchestrator.py` 末尾追加：

```python
from agent.child_tools import make_fetch_more_transcript_tool  # noqa: E402


@pytest.mark.asyncio
async def test_child_fetched_transcript_reaches_user(store, mock_relevance_gate):
    """契约:child 调 fetch_more_transcript(start, end) 拿到的实际文本,
    必须能进入 child 最终产出的 content,并被 Orchestrator 透传给 callback。

    实现方式:stub HA.arun 不写死返回内容,而是**真的调用** fetch_more_transcript
    工具(同一个 ctx),把工具返回字符串拼进 RunOutput.content 里。这样:
    - 改 fetch_more_transcript 的实现(比如改了 clamping 规则或格式)→ 测试会挂
    - 改 store 的 get_full_history 索引语义 → 测试会挂
    - 给历史多塞几句无关内容 → 测试仍能通过(只要 fetched 字符串包含目标索引)
    """
    gate = mock_relevance_gate(is_relevant=True)
    pa = MagicMock()
    pa.extract = AsyncMock(return_value=[])

    # 用唯一可辨识的句子填充历史,后续断言要找它
    sentinel = "客户在 2019 年 3 月入职"
    await store.append_utterance(
        Utterance(id="u_0", text=sentinel, speaker="client", t_start=0.0, t_end=1.0)
    )
    for i in range(1, 15):
        await store.append_utterance(
            Utterance(id=f"u_{i}", text=f"中段{i}", speaker="client", t_start=float(i), t_end=float(i + 1))
        )

    # stub HA:真的调工具,把工具返回拼进 content
    fetch_tool = make_fetch_more_transcript_tool(store)

    class RealFetchHA:
        _db = MagicMock(spec=["update_approval_run_status"])

        async def arun(self, utt):
            fetched = fetch_tool.entrypoint(start_idx=0, end_idx=1)
            return _completed_run(f"基于早期发言「{fetched}」给出建议")

    orch = Orchestrator(store, gate=gate, pa=pa, ha=RealFetchHA())
    suggestions = []
    orch.set_suggestion_callback(lambda t, m: suggestions.append((t, m)))

    await orch.handle_utterance(
        Utterance(id="u_q", text="结合一开始那次入职回答", speaker="client", t_start=20.0, t_end=21.0)
    )
    await asyncio.sleep(0.1)

    ready = [(t, m) for t, m in suggestions if m["kind"] == "ready"]
    assert len(ready) == 1, "child completed → 必须 emit ready"
    answer = ready[0][0]
    # 真正的契约:fetch_more_transcript 拉到的 sentinel 必须出现在最终回答里。
    # 改了 fetch 的格式 / 索引语义 / clamping → 这里会挂。
    assert sentinel in answer, f"sentinel '{sentinel}' 没有透传到回答: {answer!r}"
```

- [ ] **Step 2: 跑测试确认通过**

```
cd backend && uv run pytest tests/test_orchestrator.py::test_child_fetched_transcript_reaches_user -v
```
Expected: PASS。

- [ ] **Step 3: 提交**

```bash
git add backend/tests/test_orchestrator.py
git commit -m "test(agent): 追加按需拉取转写的端到端契约测试"
```

---

## Task 10: 文档收尾 + 设计 spec 状态更新

**Files:**
- Modify: `backend/docs/superpowers/specs/2026-05-29-agent-routing-redesign-design.md` — 顶部 Status 从 "设计已收敛,待评审 → 实现计划" 改为 "已实现(YYYY-MM-DD)"

- [ ] **Step 1: 更新 spec 顶部状态行**

打开 `backend/docs/superpowers/specs/2026-05-29-agent-routing-redesign-design.md`，第 4 行：

```markdown
**Status:** 已实现(2026-05-29)
```

- [ ] **Step 2: 在 spec 文档末尾追加「实现备注」一节**

末尾追加：

```markdown
---

## 13. 实现备注(2026-05-29)

- BERT 后继：当前 `RelevanceGate` 临时用 Qwen 实现。接口契约 `is_relevant(utt) -> bool`
  稳定不变；接 BERT 时替换 `relevance_gate.py` 内部即可，其它代码 0 改动。
- 前端协议：`suggestion.pending.meta` 不再含 `severity` / `intent_type` / `law_domain` /
  `entities`，新增 `preview: {topic, rationale}`。前端卡片渲染需配套调整。
- PA 暂未迁到 Agno `MemoryManager`；当前继续走 `ContextStore._profile` 结构化列表，
  因为前端画像面板仍依赖 `subject / key / value`。迁移留待前端面板重做时再评估。
- 生产用 `PostgresDb`,通过 `AGNO_DB_URL` 注入。dev/CI 通过 `reset_agno_db_for_tests(replacement=InMemoryDb())`
  注入内存替身,单元测试不依赖真实 Postgres;集成测试在 `tests/integration/` 下单独标记
  `@pytest.mark.integration` 起 docker postgres。
- 如未来要支持高可用,可直接换托管 Postgres(Neon/Supabase),`db_url` 切换即可,
  `get_agno_db()` 实现 0 改动。
```

- [ ] **Step 3: 提交**

```bash
git add backend/docs/superpowers/specs/2026-05-29-agent-routing-redesign-design.md
git commit -m "docs(spec): 标记 agent 路由重构 spec 为已实现"
```

---

## 实施后自查清单

落地完成后请逐项核对（每项都应能在测试输出里找到证据）：

- [ ] `RelevanceGate.is_relevant` 输出类型恒为 `bool`，无任何业务字段(`test_gate_contract_no_severity_no_intent_type`)
- [ ] gate=false 时 PA 仍跑、画像仍写(`test_profile_fallback_when_gate_false`)
- [ ] child completed → 直推 ready；child paused → 出 pending 且 `meta.preview` 含 topic/rationale(`test_gate_true_*_emits_*`)
- [ ] confirm 走 `acontinue_run`，不重新 `arun`(`test_acontinue_run_uses_continue_not_base`)
- [ ] confirm 走 `acontinue_run(run_id, requirements=run_output.requirements)`，不从 db 重拉(`test_confirm_path_continues_run_without_db_lookup`)
- [ ] dismiss / stale / TTL 三条路径之后，`orch._pending` 清空且 `db.update_approval_run_status(run_id, RunStatus.cancelled)` 被调用——**不存在的** `get_run / delete_run` 调用会因 `MagicMock(spec=[...])` 直接 AttributeError(`test_hitl_cleanup.py` 全套)
- [ ] `Orchestrator.from_dict` 不恢复 pending(`test_restored_pending_is_dropped_to_avoid_stale_runoutput`)
- [ ] `PendingRequest.created_at` 用 `time.time()`，跨进程 TTL 仍有意义
- [ ] `_run_child` 在 paused 分支也校验 `generation`，旧 utt 的 pending 不会污染新对话(`test_stale_completed_run_is_dropped` 同款语义,paused 版本)
- [ ] 在飞 child task 由 `self._inflight: set` 持有,异常进 `logger.exception`,不留 "Task exception was never retrieved" 飘日志
- [ ] PA / gate 异常用 `logger.warning` 留证据,不再静默 `pass`(grep `src/agent/orchestrator.py` 无 `except .*: pass`)
- [ ] `HeavyAgent` 的 Agno `Agent` 实例在 `__init__` 建一次,跨 arun/acontinue_run 复用(grep 无 `self._build_agent()` 调用)
- [ ] `ProfileAgent.extract` 的 `existing_profile` type hint 已对齐为 `dict[str, dict[str, str]]`
- [ ] WS 协议迁移按 `前端先 merge → 后端发布 → 前端发布` 顺序执行(Task 7 顶部 note)
- [ ] gate / child arun 抛异常不杀 bus consumer(`test_bus_consumer_survives_handler_exception`)
- [ ] Task 9 测试断言落在 `fetch_more_transcript` 实际拉到的 sentinel 上,不是 mock 自身写死的字符串(`test_child_fetched_transcript_reaches_user`)
- [ ] 全局 grep 无 `IntentRouter` / `IntentResult` / `severity` / `intent_type` 残留(Task 8 Step 1)
- [ ] Agno `PostgresDb` 单例可注入测试替身(`test_reset_with_replacement_swaps_singleton`)
- [ ] `ruff check` 0 错误
