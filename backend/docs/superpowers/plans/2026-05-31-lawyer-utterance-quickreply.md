# 律师 utterance 触发的快答补充 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让律师 utterance 也能触发快答，由 HeavyAgent 走 role-aware 分支输出"纠错/补全/换角度"三类补充给律师。

**Architecture:** 单 HeavyAgent + role-aware system prompt。`InsightReady` 加 `trigger_speaker` 必填字段；`Suggestion` 表加同名列（drop + recreate，不做向后兼容）。Orchestrator emit 时透传 `utt.speaker`，前端按 `triggerSpeaker` 渲染差异化样式。当事人主路 100% 不变。

**Tech Stack:** Python + FastAPI + Pydantic + SQLAlchemy + Alembic + Postgres（后端）；React + TypeScript + Vitest（前端）。

**Spec：** `backend/docs/superpowers/specs/2026-05-31-lawyer-utterance-quickreply-design.md`

---

## File Structure

**修改：**
- `backend/src/agent/events.py` — `InsightReady` 加 `trigger_speaker` 必填字段
- `backend/src/db/models.py` — `Suggestion` 表加 `trigger_speaker` 列
- `backend/src/repositories/suggestions.py` — `insert_direct` / `upsert_pending` 加参数，`list_by_session` 输出加键
- `backend/src/agent/orchestrator.py` — `_RepoWriter` protocol 同步，`_run_child` emit 时透传 `utt.speaker`
- `backend/main.py` — `_DbRepoWriter.insert_direct` / `upsert_pending` 转发新参数
- `backend/src/agent/prompts.py` — `get_child_system_prompt()` 末尾追加 lawyer 分支段
- `backend/tests/agent/test_orchestrator_emitter.py` — `FakeRepoWriter` 同步 + 加 lawyer trigger 镜像用例
- `backend/tests/repositories/test_suggestions.py` — 加 trigger_speaker 字段验证
- `backend/tests/api/test_history.py` — 加 lawyer trigger 在 history 接口的回归
- `frontend/src/types/index.ts` — `Insight` 加 `triggerSpeaker`
- `frontend/src/types/events.ts` — `InsightReady` TS 镜像加 `trigger_speaker`
- `frontend/src/context/sessionReducer.ts` — `insight.ready` 分支映射 `trigger_speaker → triggerSpeaker`
- `frontend/src/components/insights/InsightCard.tsx` — 按 `triggerSpeaker` 渲染差异化样式
- `specs/001-frontend-v3-redesign/tasks.md` — 在 v3 任务列表追加"卡片 trigger_speaker 样式区分"补丁条目

**新建：**
- `backend/alembic/versions/<hash>_add_suggestion_trigger_speaker.py` — drop + recreate suggestions 表的迁移文件
- `backend/tests/agent/test_prompts.py` — 系统 prompt lawyer 分支段断言测试
- `backend/tests/agent/test_events.py` — `InsightReady` schema 必填字段断言测试（若不存在则新建）
- `backend/tests/e2e/test_lawyer_quickreply_e2e.py` — `@pytest.mark.slow` 真模型三场景测试
- `frontend/src/components/insights/__tests__/InsightCard.test.tsx` — 按 trigger_speaker 渲染差异化的单测（若 __tests__ 目录不存在则新建）

---

## 前置检查（实施 Task 1 之前执行）

以下检查项用于排除已知的不确定因素，避免做到一半踩坑。

- [ ] **确认 Alembic 当前 head revision**

```bash
cd backend && uv run alembic current
```
记录输出的 revision id（形如 `a5f7181a7fc3`），Task 3 的 migration `down_revision` 必须填这个值，不要直接复制本 plan 里的硬编码字符串。

- [ ] **确认 `build_child_user_prompt` 当前签名是否已有 `trigger_speaker` 参数**

```bash
grep -n "def build_child_user_prompt" backend/src/agent/prompts.py -A 3
```
若返回值，继续；若缺 `trigger_speaker`，Task 8 必须先补签名修改。

- [ ] **确认前端 `MessageSquare` 与 `border-border-color` 是否存在**

```bash
cd frontend && grep -rn "MessageSquare" src/ || echo "NOT FOUND"
grep -rn "border-border-color\|border-border" src/ | head -5
```
若 `MessageSquare` 不存在，换用 `lucide-react` 中已导入的其他图标；若 border class 不存在，改用项目实际 token（如 `border-slate-200` 或 `border-border`）。

- [ ] **确认 `HeavyAgent` 构造函数与 `arun` 签名**

```bash
grep -n "class HeavyAgent" backend/src/agent/heavy_agent.py -A 5
grep -n "def arun" backend/src/agent/heavy_agent.py -A 5
```
Task 12 的 e2e 测试按实际签名调整构造与调用。

---

## Task 1: events.py 给 InsightReady 加 trigger_speaker 必填字段

**Files:**
- Modify: `backend/src/agent/events.py:21-26`
- Create or Modify: `backend/tests/agent/test_events.py`

- [ ] **Step 1: 写失败测试断言 InsightReady 缺 trigger_speaker 抛 ValidationError**

如果 `backend/tests/agent/test_events.py` 不存在则新建：

```python
"""WS 出站事件 schema 单元测试。"""
import pytest
from pydantic import ValidationError

from agent.events import InsightReady


def test_insight_ready_requires_trigger_speaker():
    with pytest.raises(ValidationError) as exc:
        InsightReady(id="i1", utt_id="u1", text="hello")
    assert "trigger_speaker" in str(exc.value)


def test_insight_ready_rejects_invalid_speaker():
    with pytest.raises(ValidationError) as exc:
        InsightReady(id="i1", utt_id="u1", text="hello", trigger_speaker="unknown")
    assert "trigger_speaker" in str(exc.value)


def test_insight_ready_accepts_lawyer_and_client():
    assert InsightReady(id="i1", utt_id="u1", text="x", trigger_speaker="lawyer").trigger_speaker == "lawyer"
    assert InsightReady(id="i1", utt_id="u1", text="x", trigger_speaker="client").trigger_speaker == "client"
```

- [ ] **Step 2: 运行测试，预期失败**

```bash
cd backend && uv run pytest tests/agent/test_events.py -v
```

预期：`test_insight_ready_requires_trigger_speaker` 失败（当前 InsightReady 无此字段，可被构造）；其他两个测试也失败。

- [ ] **Step 3: 给 InsightReady 加 trigger_speaker 必填字段**

修改 `backend/src/agent/events.py:21-26`：

```python
class InsightReady(BaseModel):
    type: Literal["insight.ready"] = "insight.ready"
    id: str
    utt_id: str
    text: str
    trigger_speaker: Literal["client", "lawyer"]
```

- [ ] **Step 4: 运行测试，预期通过**

```bash
cd backend && uv run pytest tests/agent/test_events.py -v
```

预期：3 个测试全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add backend/src/agent/events.py backend/tests/agent/test_events.py
git commit -m "feat(events): InsightReady 加 trigger_speaker 必填字段"
```

---

## Task 2: db/models.py 给 Suggestion 表加 trigger_speaker 列

**Files:**
- Modify: `backend/src/db/models.py:71-109`

- [ ] **Step 1: 给 Suggestion 模型加 trigger_speaker 列**

修改 `backend/src/db/models.py:88-90`（在 `source` 字段后插入）：

```python
    source: Mapped[str] = mapped_column(
        String, nullable=False, default="gated"
    )  # 'direct'（实时洞察）| 'gated'（深度分析）
    trigger_speaker: Mapped[str] = mapped_column(
        String, nullable=False
    )  # 'client' | 'lawyer'，触发本条快答的 utterance 说话人
```

- [ ] **Step 2: Commit**

```bash
git add backend/src/db/models.py
git commit -m "feat(db): Suggestion 加 trigger_speaker 列"
```

---

## Task 3: Alembic 迁移 — drop + recreate suggestions 表

**Files:**
- Create: `backend/alembic/versions/<hash>_add_suggestion_trigger_speaker.py`

- [ ] **Step 1: 生成空迁移文件**

```bash
cd backend && uv run alembic revision -m "add_suggestion_trigger_speaker"
```

预期：在 `backend/alembic/versions/` 下创建一个新文件，文件名形如 `<hash>_add_suggestion_trigger_speaker.py`。

- [ ] **Step 2: 写 drop + recreate 逻辑**

打开新生成的迁移文件，替换 `upgrade()` 和 `downgrade()`：

```python
"""add_suggestion_trigger_speaker

不做向后兼容：drop + recreate suggestions 表，旧数据全部抛弃。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision = "<填入自动生成的 hash>"
down_revision = "<前置检查获取的当前 head revision>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("suggestions")
    op.create_table(
        "suggestions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", UUID(as_uuid=True),
                  sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("utt_id", sa.String,
                  sa.ForeignKey("utterances.id", ondelete="CASCADE"), nullable=False),
        sa.Column("request_id", sa.String, nullable=True),
        sa.Column("source", sa.String, nullable=False, server_default="gated"),
        sa.Column("trigger_speaker", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False, server_default="pending"),
        sa.Column("preview_topic", sa.Text, nullable=True),
        sa.Column("preview_rationale", sa.Text, nullable=True),
        sa.Column("text", sa.Text, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint("session_id", "request_id", name="uq_sug_session_req"),
    )
    op.create_index(
        "idx_suggestions_session_created", "suggestions", ["session_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("idx_suggestions_session_created", table_name="suggestions")
    op.drop_table("suggestions")
    # downgrade 不重建旧 schema——本迁移本就抛弃旧数据，无法回滚
```

把第一行的 `revision = "<填入自动生成的 hash>"` 中的占位符替换成 alembic 自动生成的 revision id（文件名前缀的那串 hex）。

- [ ] **Step 3: 在本地 dev DB 跑迁移**

```bash
cd backend && uv run alembic upgrade head
```

预期：日志显示 "Running upgrade a5f7181a7fc3 -> <hash>, add_suggestion_trigger_speaker"。

- [ ] **Step 4: 用 psql 验证 schema**

```bash
psql "$DATABASE_URL" -c "\d suggestions" | grep -E "trigger_speaker|source"
```

预期：输出包含 `trigger_speaker | character varying | not null` 与 `source | character varying | not null`。

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/*_add_suggestion_trigger_speaker.py
git commit -m "feat(db): alembic migration - drop+recreate suggestions 加 trigger_speaker"
```

---

## Task 4: SuggestionRepository — insert_direct/upsert_pending 加 trigger_speaker 参数

**Files:**
- Modify: `backend/src/repositories/suggestions.py:23-100, 112-134`
- Modify: `backend/tests/repositories/test_suggestions.py`

- [ ] **Step 1: 写失败测试覆盖 insert_direct 必须接 trigger_speaker**

在 `backend/tests/repositories/test_suggestions.py` 追加：

```python
import pytest


@pytest.mark.asyncio
async def test_insert_direct_requires_trigger_speaker(db_session):
    from repositories.suggestions import SuggestionRepository
    import uuid as _uuid
    repo = SuggestionRepository(db_session)
    sid = _uuid.uuid4()
    with pytest.raises(TypeError):
        await repo.insert_direct(sid, utt_id="u1", text="x")  # 缺 trigger_speaker


@pytest.mark.asyncio
async def test_insert_direct_stores_trigger_speaker_lawyer(db_session):
    from repositories.suggestions import SuggestionRepository
    from db.models import Suggestion
    from sqlalchemy import select
    import uuid as _uuid
    repo = SuggestionRepository(db_session)
    sid = _uuid.uuid4()
    # 测试 fixture 需要先 insert session + utterance（沿用现有 fixture 模式）
    # 假设 db_session 已经 setup 好 sid 对应的 session 和 utt
    await repo.insert_direct(sid, utt_id="u1", text="answer", trigger_speaker="lawyer")
    row = (await db_session.execute(
        select(Suggestion).where(Suggestion.session_id == sid)
    )).scalar_one()
    assert row.trigger_speaker == "lawyer"


@pytest.mark.asyncio
async def test_upsert_pending_requires_trigger_speaker(db_session):
    from repositories.suggestions import SuggestionRepository
    import uuid as _uuid
    repo = SuggestionRepository(db_session)
    sid = _uuid.uuid4()
    with pytest.raises(TypeError):
        await repo.upsert_pending(
            sid, utt_id="u1", request_id="r1",
            preview_topic="t", preview_rationale="r",
        )  # 缺 trigger_speaker
```

注意：测试运行需要现有的 `db_session` fixture 已经设置好 sessions 和 utterances 表的依赖数据（查看 `backend/tests/repositories/conftest.py` 或现有的 `test_upsert_ready_without_pending_creates_row` 用例的 setup 方式）。若现有 fixture 不能直接复用，先复用一个最近的相邻测试的 setup 思路构造 sid/utt_id。

- [ ] **Step 2: 运行测试，预期失败**

```bash
cd backend && uv run pytest tests/repositories/test_suggestions.py -v
```

预期：新加的 3 个测试失败（缺参数报 TypeError 测试因当前签名不接 trigger_speaker 不会 raise，反向失败；存储测试因字段不存在失败）。

- [ ] **Step 3: 修改 SuggestionRepository.insert_direct 加 trigger_speaker 参数**

修改 `backend/src/repositories/suggestions.py:94-101`：

```python
    async def insert_direct(
        self, session_id: uuid.UUID, *, utt_id: str, text: str, trigger_speaker: str,
    ) -> None:
        self._s.add(Suggestion(
            id=uuid.uuid4(), session_id=session_id, utt_id=utt_id,
            request_id=None, source="direct", status="ready", text=text,
            trigger_speaker=trigger_speaker,
        ))
        await self._s.commit()
```

- [ ] **Step 4: 修改 upsert_pending 加 trigger_speaker 参数**

修改 `backend/src/repositories/suggestions.py:23-43`：

```python
    async def upsert_pending(
        self,
        session_id: uuid.UUID,
        *,
        utt_id: str,
        request_id: str,
        preview_topic: str | None,
        preview_rationale: str | None,
        trigger_speaker: str,
    ) -> None:
        row = await self._find_gated(session_id, request_id)
        if row is None:
            self._s.add(Suggestion(
                id=uuid.uuid4(), session_id=session_id, utt_id=utt_id,
                request_id=request_id, source="gated", status="pending",
                preview_topic=preview_topic, preview_rationale=preview_rationale,
                trigger_speaker=trigger_speaker,
            ))
        else:
            row.status = "pending"
            row.preview_topic = preview_topic
            row.preview_rationale = preview_rationale
            # trigger_speaker 在 pending 阶段就定下，不允许在 upsert 时修改
        await self._s.commit()
```

- [ ] **Step 5: 修改 list_by_session 输出加 trigger_speaker 键**

修改 `backend/src/repositories/suggestions.py:119-133`，在返回字典里加 `"trigger_speaker": r.trigger_speaker`：

```python
        return [
            {
                "id": str(r.id),
                "utt_id": r.utt_id,
                "request_id": r.request_id,
                "source": r.source,
                "trigger_speaker": r.trigger_speaker,
                "status": r.status,
                "preview_topic": r.preview_topic,
                "preview_rationale": r.preview_rationale,
                "text": r.text,
                "error": r.error,
                "confirmed_at": r.confirmed_at.isoformat() if r.confirmed_at else None,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
```

- [ ] **Step 6: 修复现有测试中 insert_direct/upsert_pending 调用（如果有）**

```bash
cd backend && grep -rn "insert_direct\|upsert_pending" tests/ | grep -v "__pycache__"
```

检查所有匹配处。若有调用不传 `trigger_speaker` 的，按测试上下文加 `trigger_speaker="client"` 或 `"lawyer"`。例如：
- `tests/repositories/test_suggestions.py` 已有的 `test_upsert_ready_without_pending_creates_row` 等用例若调到 insert_direct/upsert_pending，加 trigger_speaker 参数
- `tests/api/test_history.py:34` 已有 `upsert_ready` 调用（不需改 upsert_ready），但若 setup 数据调到 insert_direct/upsert_pending 也需要加

- [ ] **Step 7: 运行测试，预期通过**

```bash
cd backend && uv run pytest tests/repositories/ -v
```

预期：所有 repository 测试 PASS。

- [ ] **Step 8: Commit**

```bash
git add backend/src/repositories/suggestions.py backend/tests/repositories/test_suggestions.py
# 若 Step 6 改了其他测试文件也一并 add
git commit -m "feat(repo): SuggestionRepository.insert_direct/upsert_pending 加 trigger_speaker"
```

---

## Task 5: Orchestrator _RepoWriter protocol 同步 + FakeRepoWriter 更新

**Files:**
- Modify: `backend/src/agent/orchestrator.py:39-50`
- Modify: `backend/tests/agent/test_orchestrator_emitter.py:31-50`

- [ ] **Step 1: 更新 _RepoWriter protocol 签名**

修改 `backend/src/agent/orchestrator.py:39-50`：

```python
class _RepoWriter(Protocol):
    """Orchestrator 写 DB 用的最小接口。main.py 注入一个绑定 sessionmaker
    + session_id 的实现；测试注入 FakeRepoWriter。"""
    async def insert_direct(self, *, utt_id: str, text: str, trigger_speaker: str) -> None: ...
    async def upsert_pending(self, *, utt_id: str, request_id: str,
                              preview_topic: str | None,
                              preview_rationale: str | None,
                              trigger_speaker: str) -> None: ...
    async def mark_running(self, request_id: str) -> None: ...
    async def upsert_ready(self, *, request_id: str, text: str,
                            utt_id: str | None) -> None: ...
    async def mark_dismissed(self, request_id: str) -> None: ...
    async def mark_expired(self, request_id: str) -> None: ...
```

- [ ] **Step 2: 同步 FakeRepoWriter 测试 stub**

修改 `backend/tests/agent/test_orchestrator_emitter.py:31-50` 附近的 FakeRepoWriter，把 insert_direct 和 upsert_pending 的签名加上 `trigger_speaker`：

```python
    async def insert_direct(self, *, utt_id: str, text: str, trigger_speaker: str) -> None:
        self.calls.append(("insert_direct", {
            "utt_id": utt_id, "text": text, "trigger_speaker": trigger_speaker
        }))

    async def upsert_pending(self, *, utt_id: str, request_id: str,
                              preview_topic, preview_rationale,
                              trigger_speaker: str) -> None:
        self.calls.append(("upsert_pending", {
            "utt_id": utt_id, "request_id": request_id,
            "preview_topic": preview_topic, "preview_rationale": preview_rationale,
            "trigger_speaker": trigger_speaker,
        }))
```

并扫一下 FakeRepoWriter 的其他方法签名是否仍与 protocol 对齐（upsert_ready / mark_running / mark_dismissed / mark_expired 保持不变）。

- [ ] **Step 3: 运行现有 orchestrator 测试（预期会因 Orchestrator 尚未透传 trigger_speaker 而部分失败，这是预期的——Task 7 会修）**

```bash
cd backend && uv run pytest tests/agent/test_orchestrator_emitter.py -v
```

预期：现有的 insert_direct/upsert_pending 验证测试因为 Orchestrator 还没传 trigger_speaker 参数而失败（TypeError）。**不要修复——这是 Task 7 的工作。**

- [ ] **Step 4: 不 commit，留到 Task 7 一起 commit**

（_RepoWriter protocol 与 Orchestrator emit 是一对一对应的，应当在同一个 commit 里改完，避免中间状态崩。）

---

## Task 6: main.py _DbRepoWriter 转发 trigger_speaker 参数

**Files:**
- Modify: `backend/main.py:189-201`

- [ ] **Step 1: 修改 _DbRepoWriter.insert_direct 转发 trigger_speaker**

修改 `backend/main.py:189-193`：

```python
    async def insert_direct(self, *, utt_id: str, text: str, trigger_speaker: str) -> None:
        async with self._sm() as s:
            await SuggestionRepository(s).insert_direct(
                self._sid, utt_id=utt_id, text=text, trigger_speaker=trigger_speaker,
            )
```

- [ ] **Step 2: 修改 _DbRepoWriter.upsert_pending 转发 trigger_speaker**

修改 `backend/main.py:195-201`：

```python
    async def upsert_pending(self, *, utt_id: str, request_id: str,
                              preview_topic, preview_rationale,
                              trigger_speaker: str) -> None:
        async with self._sm() as s:
            await SuggestionRepository(s).upsert_pending(
                self._sid, utt_id=utt_id, request_id=request_id,
                preview_topic=preview_topic, preview_rationale=preview_rationale,
                trigger_speaker=trigger_speaker,
            )
```

- [ ] **Step 3: 不 commit，留到 Task 7 一起 commit**

---

## Task 7: Orchestrator _run_child emit InsightReady/AnalysisProposed 透传 trigger_speaker

**Files:**
- Modify: `backend/src/agent/orchestrator.py:218-272`
- Modify: `backend/tests/agent/test_orchestrator_emitter.py`

- [ ] **Step 1: 写失败测试 — lawyer trigger 的 direct 路径**

在 `backend/tests/agent/test_orchestrator_emitter.py` 追加（仿照现有的 `test_direct_insight_emits...` 用例结构，把 utterance 的 speaker 换成 lawyer）：

```python
@pytest.mark.asyncio
async def test_lawyer_trigger_direct_insight_carries_lawyer_speaker(monkeypatch):
    """律师 utterance 触发的快答：InsightReady.trigger_speaker = lawyer，
    repo.insert_direct 收到 trigger_speaker='lawyer'，ProfileAgent 未被调用。"""
    from agent.orchestrator import Orchestrator
    from agent.context_store import ContextStore
    from agent.events import InsightReady
    from models.utterance import Utterance

    # 仿照同文件已有用例的 fixture pattern 构造 ctx / fake gate / fake HA / fake repo
    # 关键差异：utterance.speaker = "lawyer"
    # 关键断言：
    #   - emitted 事件中存在 InsightReady(trigger_speaker="lawyer")
    #   - fake_repo.calls 包含 ("insert_direct", {... "trigger_speaker": "lawyer" ...})
    #   - fake_pa.extract 调用计数 == 0
```

具体测试用例代码应当镜像同文件中现有的 `test_*direct_insight*` 测试结构。**复用现有 fixture 与 fake 类**，唯一改动是 `Utterance(speaker="lawyer", ...)`。

- [ ] **Step 2: 运行测试，预期失败**

```bash
cd backend && uv run pytest tests/agent/test_orchestrator_emitter.py::test_lawyer_trigger_direct_insight_carries_lawyer_speaker -v
```

预期：FAIL（Orchestrator 还没把 trigger_speaker 接到 emit 与 repo 上）。

- [ ] **Step 3: 修改 _run_child 的 direct 分支**

修改 `backend/src/agent/orchestrator.py:245-247` 附近（"if not run.is_paused" 分支内的 emit 调用），把 emit 改为走 typed event 路径并透传 trigger_speaker，同时让 repo 调用带 trigger_speaker：

```python
        if not run.is_paused:
            text = getattr(run, "content", None)
            insight_id = f"ins_{uuid.uuid4().hex[:8]}"
            assert utt.speaker in ("client", "lawyer"), f"unexpected speaker: {utt.speaker}"
            await self._emit_event(InsightReady(
                id=insight_id,
                utt_id=utt.id,
                text=text or "",
                trigger_speaker=utt.speaker,  # 已归一 lawyer/client
            ))
            if self._repo is not None:
                await self._repo.insert_direct(
                    utt_id=utt.id, text=text or "", trigger_speaker=utt.speaker,
                )
            return
```

⚠️ 若现有 `_run_child` 的 emit 仍走旧的 `self._emit(meta, text=...)` callback 路径（dict 风格），请改为走新的 `_emit_event(InsightReady(...))`。Spec 已经明确"新功能走 typed event"。**保留同时调用 `self._emit(meta, text=...)` 的兼容路径**仅当现有测试或 main.py 仍依赖它（Task 5 应该已经看到 protocol 是新风格）。

在文件顶部 imports 区追加（若尚未导入）：

```python
import uuid
from agent.events import InsightReady, AnalysisProposed
```

- [ ] **Step 4: 修改 _run_child 的 paused 分支同样透传 trigger_speaker**

修改 `backend/src/agent/orchestrator.py:248-272` 附近（paused 分支），让 AnalysisProposed emit 与 upsert_pending 都带 trigger_speaker：

```python
        # paused: 取首个 requirement 的预览给律师
        req = run.active_requirements[0] if run.active_requirements else None
        preview = {}
        if req is not None and req.tool_execution is not None:
            preview = dict(req.tool_execution.tool_args or {})

        request_id = f"req_{uuid.uuid4().hex[:8]}"
        assert utt.speaker in ("client", "lawyer"), f"unexpected speaker: {utt.speaker}"
        self._pending[request_id] = PendingRequest(
            request_id=request_id,
            run_id=run.run_id,
            utt_id=utt.id,
            generation=generation,
            preview=preview,
            run_output=run,
        )
        await self._emit_event(AnalysisProposed(
            request_id=request_id,
            utt_id=utt.id,
            topic=preview.get("topic", "") or "",
            rationale=preview.get("rationale", "") or "",
        ))
        if self._repo is not None:
            await self._repo.upsert_pending(
                utt_id=utt.id, request_id=request_id,
                preview_topic=preview.get("topic"),
                preview_rationale=preview.get("rationale"),
                trigger_speaker=utt.speaker,
            )
```

注意：`AnalysisProposed`（events.py:28-33）目前没有 trigger_speaker 字段——本 spec **只给 InsightReady 加** trigger_speaker，AnalysisProposed 不动（律师触发深析时弹的卡片与 client trigger 视觉一致，AC-7 决定）。所以 AnalysisProposed 的 emit 不带 trigger_speaker，但 **repo.upsert_pending 必须带**（DB 记录完整 trigger 来源）。

- [ ] **Step 5: 运行新测试，预期通过**

```bash
cd backend && uv run pytest tests/agent/test_orchestrator_emitter.py::test_lawyer_trigger_direct_insight_carries_lawyer_speaker -v
```

预期：PASS。

- [ ] **Step 6: 运行全部 orchestrator 测试，预期当事人主路所有现有用例仍 PASS**

```bash
cd backend && uv run pytest tests/agent/test_orchestrator_emitter.py -v
```

预期：现有 client trigger 测试全部 PASS（client 主路行为零变化）。如果失败，回看现有测试用例是否调到 insert_direct/upsert_pending 但没传 trigger_speaker——加 `trigger_speaker="client"` 即可。

- [ ] **Step 7: Commit（包含 Task 5、Task 6、Task 7 的所有改动）**

```bash
git add backend/src/agent/orchestrator.py backend/main.py backend/tests/agent/test_orchestrator_emitter.py
git commit -m "feat(orch): _run_child emit InsightReady/upsert_pending 透传 trigger_speaker"
```

---

## Task 8: prompts.py 给 system prompt 加 lawyer 分支段

**Files:**
- Modify: `backend/src/agent/prompts.py:118-137`
- Create: `backend/tests/agent/test_prompts.py`

- [ ] **Step 1: 写失败测试断言 system prompt 含 lawyer 分支**

新建 `backend/tests/agent/test_prompts.py`：

```python
"""Child agent system prompt 单元测试。"""
from agent.prompts import get_child_system_prompt, build_child_user_prompt


def test_child_system_prompt_contains_lawyer_branch():
    p = get_child_system_prompt()
    assert "trigger_speaker" in p
    assert "lawyer" in p
    assert "纠错" in p
    assert "补全" in p
    assert "换角度" in p
    assert "不调 deep_analysis" in p or "不调用 deep_analysis" in p


def test_child_system_prompt_keeps_existing_client_quickreply_and_deep_analysis_sections():
    """守住原有的快答 / 深析段落不被误删。"""
    p = get_child_system_prompt()
    assert "快答" in p
    assert "深析" in p
    assert "允许沉默" in p


def test_child_user_prompt_renders_trigger_speaker_in_text():
    """build_child_user_prompt 必须把 trigger_speaker 渲染进 prompt 文本，
    否则系统 prompt 里的 'trigger_speaker = lawyer' 分支判断无意义。"""
    out = build_child_user_prompt(
        trigger_text="测试句子",
        trigger_speaker="lawyer",
        profile_summary={},
        recent_window=[],
    )
    assert "speaker: lawyer" in out
    assert "测试句子" in out
```

- [ ] **Step 2: 运行测试，预期失败**

```bash
cd backend && uv run pytest tests/agent/test_prompts.py -v
```

预期：`test_child_system_prompt_contains_lawyer_branch` 失败（当前 prompt 没有 lawyer 分支）。`test_child_user_prompt_renders_trigger_speaker_in_text` 也可能失败（若当前 `build_child_user_prompt` 尚无 `trigger_speaker` 参数）。

- [ ] **Step 2: 给 `build_child_user_prompt` 加 `trigger_speaker` 参数并渲染 speaker**

先确认前置检查里 `grep build_child_user_prompt` 的结果：

- 若签名已有 `trigger_speaker`，跳过本节代码修改，只确认 prompt 模板里已渲染 `speaker: {trigger_speaker}`。
- 若签名没有，修改 `backend/src/agent/prompts.py` 中 `build_child_user_prompt` 函数：

```python
def build_child_user_prompt(
    trigger_text: str,
    trigger_speaker: str,
    profile_summary: dict,
    recent_window: list,
) -> str:
    ...
    # 在返回的 user prompt 字符串里，触发句段落中加上 speaker 信息
    ## 触发当前响应的句子
    speaker: {trigger_speaker}
    {trigger_text}
    ...
```

具体渲染位置放在 "## 触发当前响应的句子" 段下，与 system prompt 里的 `speaker = client/lawyer` 分支判断对应。

- [ ] **Step 3: 运行测试，预期部分失败**

```bash
cd backend && uv run pytest tests/agent/test_prompts.py -v
```

预期：`test_child_system_prompt_contains_lawyer_branch` 失败（当前 system prompt 没有 lawyer 分支）。`test_child_user_prompt_renders_trigger_speaker_in_text` 与 `test_child_system_prompt_keeps_existing_client_quickreply_and_deep_analysis_sections` 应当通过。

- [ ] **Step 4: 给 system prompt 追加 lawyer 分支段**

修改 `backend/src/agent/prompts.py:118-137`，在现有 `get_child_system_prompt()` 函数返回的字符串末尾追加分支段。完整新版本：

```python
def get_child_system_prompt() -> str:
    return """你是律师的实时 AI 助手,旁听律师与客户的法律咨询。受众只有律师,禁用"您"对客户说话,不替律师指导客户。

# 两种工作方式

**快答** —— 你的主要工作。律师在听客户说话的同时,你给他能立刻用上的东西:可能是一句法条提点、一个该追问的事实、一个被忽略的风险、一段速算,或任何你判断此刻对律师有用的洞察。哪怕只是半句话,只要有用就说出来。简短、果断。

**深析**(调 `deep_analysis(topic, rationale)`)—— 律师需要停下来读的结构化产物。会切换工作模式、暂停等律师确认。

判断准绳:律师此刻需要的是「接住即用」还是「停下来读」?你在听对话流,自己判断。

# 允许沉默
你要说的话律师此刻并不需要,就不要说。但记住,一个有用的快答远比沉默更有价值。

# 工具
- `fetch_more_transcript(start, end)`:默认窗口看不到的早期内容确有必要时拉取。
- `deep_analysis(topic, rationale)`:切到深析模式。topic 直白,rationale 让律师能判断此刻是否要切。

# 风格
对律师直接说话,专业紧凑;引法条带编号;计算展示公式;不绕弯子。

# 触发分流
看 user 消息里 `## 触发当前响应的句子` 段下 `speaker:` 字段的值：

- speaker = client（当事人说话触发）：按上述「快答 / 深析」两种工作方式行事。
- speaker = lawyer（律师自己说话触发）：切换为「对律师本人的补充」模式。
  - 只做三类输出：
    1. **纠错**：律师引的法条编号、数字、事实硬错时立即指出「刚说的 XX 应为 YY」
    2. **补全**：律师转向下个话题但有关键事实没问到/没强调时提示「还可以追问 X / 注意 Y」
    3. **换角度**：律师给当事人建议时提示「也可考虑 Z 路径」
  - **不调 deep_analysis**（律师自己刚说的话不适合让他停下来读结构化分析）
  - 口径：对律师直说，「你刚才说的...」「建议补一句...」；不评论律师沟通技巧、不点评用词
  - 没有要补充的就沉默（沉默原则同样适用）
"""
```

- [ ] **Step 5: 运行测试，预期全部通过**

```bash
cd backend && uv run pytest tests/agent/test_prompts.py -v
```

预期：3 个测试全部 PASS。

- [ ] **Step 6: Commit**

```bash
git add backend/src/agent/prompts.py backend/tests/agent/test_prompts.py
git commit -m "feat(prompts): child system prompt 加 lawyer trigger 分支段"
```

---

## Task 9: 集成测试 — lawyer trigger 镜像用例

**Files:**
- Modify: `backend/tests/agent/test_orchestrator_emitter.py`

- [ ] **Step 1: 写 lawyer trigger 的 paused 路径测试**

在 `backend/tests/agent/test_orchestrator_emitter.py` 追加（守护 spec 4.1 决定：违反软约束不特殊处理）：

```python
@pytest.mark.asyncio
async def test_lawyer_trigger_paused_still_goes_through_normal_flow(monkeypatch):
    """守护 spec 4.1：lawyer trigger 触发 paused 不被特殊拦截，正常 emit
    AnalysisProposed、进 _pending、confirm 流程能走完。"""
    # 仿照同文件已有 paused 用例（搜 "paused" 关键字找参考），把 utt.speaker 改 "lawyer"
    # 关键断言：
    #   - emitted 事件中存在 AnalysisProposed(utt_id == lawyer_utt.id)
    #   - orch._pending 包含本次的 request_id
    #   - fake_repo.calls 包含 ("upsert_pending", {... "trigger_speaker": "lawyer" ...})
```

具体代码镜像现有的 paused 测试，关键差异只有 `utterance.speaker = "lawyer"`。

- [ ] **Step 2: 写 lawyer utterance 跳过 ProfileAgent 测试**

继续追加：

```python
@pytest.mark.asyncio
async def test_lawyer_utterance_skips_profile_agent(monkeypatch):
    """守护 orchestrator.py:161：lawyer utterance 不被 ProfileAgent 提取。"""
    # 仿照同文件已有 PA 调用验证用例
    # 关键差异：utterance.speaker = "lawyer"
    # 关键断言：fake_pa.extract 调用次数 == 0
    #         （即使 gate=true 触发 HA child run，PA 仍未被调）
```

- [ ] **Step 3: 运行新增测试，预期 PASS**

```bash
cd backend && uv run pytest tests/agent/test_orchestrator_emitter.py -k "lawyer" -v
```

预期：3 个 lawyer 相关测试（Task 7 已加 1 个 + 本 Task 加 2 个）全部 PASS。

- [ ] **Step 4: Commit**

```bash
git add backend/tests/agent/test_orchestrator_emitter.py
git commit -m "test(orch): 集成测试覆盖 lawyer trigger 镜像路径"
```

---

## Task 10: 前端 — types 同步 + InsightCard 差异化样式

**Files:**
- Modify: `frontend/src/types/events.ts:15-20`
- Modify: `frontend/src/types/index.ts:1-6`
- Modify: `frontend/src/context/sessionReducer.ts:19-27`
- Modify: `frontend/src/components/insights/InsightCard.tsx`
- Create: `frontend/src/components/insights/__tests__/InsightCard.test.tsx`

- [ ] **Step 1: 更新 events.ts 镜像后端 schema**

修改 `frontend/src/types/events.ts:15-20`：

```typescript
export type InsightReady = {
  type: 'insight.ready'
  id: string
  utt_id: string
  text: string
  trigger_speaker: 'client' | 'lawyer'
}
```

- [ ] **Step 2: 更新 Insight 领域模型加 triggerSpeaker**

修改 `frontend/src/types/index.ts:1-6`：

```typescript
export type Insight = {
  id: string
  uttId: string
  text: string
  triggerSpeaker: 'client' | 'lawyer'
  createdAt: string
}
```

- [ ] **Step 3: 运行 tsc 找断点**

```bash
cd frontend && pnpm tsc --noEmit
```

预期：sessionReducer.ts:20-25 报错（Insight 构造少 triggerSpeaker 字段）；可能 InsightCard.tsx 不报（因为它只读 text，但下一步要让它读 triggerSpeaker）。记录所有报错位置。

- [ ] **Step 4: 修复 sessionReducer.ts 的 insight.ready 映射**

修改 `frontend/src/context/sessionReducer.ts:19-27`：

```typescript
    case 'insight.ready': {
      const insight: Insight = {
        id: evt.id,
        uttId: evt.utt_id,
        text: evt.text,
        triggerSpeaker: evt.trigger_speaker,
        createdAt: new Date().toISOString(),
      }
      return { ...state, insights: [insight, ...state.insights] }
    }
```

- [ ] **Step 5: 确认前端依赖存在（若前置检查未通过则先修复）**

根据前置检查结果：
- 若 `MessageSquare` 不存在于 `lucide-react` 已导入列表中，改为项目中已使用的其他图标（如 `AlertCircle`、`Info` 等），或执行 `pnpm add lucide-react`（但通常已安装）。
- 若 `border-border-color` 不是项目有效 Tailwind class，改为实际使用的 border token（如 `border-border`、`border-slate-200`、`border-gray-200` 等）。

只改占位值，不改逻辑。

- [ ] **Step 6: 修改 InsightCard.tsx 按 triggerSpeaker 渲染差异化样式**

修改 `frontend/src/components/insights/InsightCard.tsx`：

```typescript
import { Sparkles, MessageSquare } from 'lucide-react'
import type { Insight } from '@/types'

export type InsightCardProps = { insight: Insight }

export default function InsightCard({ insight }: InsightCardProps) {
  const isLawyer = insight.triggerSpeaker === 'lawyer'
  const accentClass = isLawyer ? 'text-amber-400' : 'text-accent'
  const borderClass = isLawyer
    ? 'py-4 border-t border-l-2 border-l-amber-400 border-border-color first:border-t-0 pl-3'
    : 'py-4 border-t border-border-color first:border-t-0'
  const Icon = isLawyer ? MessageSquare : Sparkles
  const label = isLawyer ? '律师补充' : '实时洞察'

  return (
    <div className={borderClass} data-trigger-speaker={insight.triggerSpeaker}>
      <div className="flex items-center gap-2 mb-2">
        <Icon className={`w-3 h-3 ${accentClass}`} />
        <span className={`text-xs font-medium ${accentClass}`}>{label}</span>
      </div>
      <p className="text-sm text-ink-secondary leading-relaxed whitespace-pre-wrap">
        {insight.text}
      </p>
    </div>
  )
}
```

注：颜色（`text-amber-400`、`border-l-amber-400`）作为占位，**最终颜色应由 v3 设计稿审核确定**。spec AC-3 只要求"非技术用户一眼能辨"，落地时可调具体色值/图标。`data-trigger-speaker` 属性方便测试与 e2e 选择器定位。

- [ ] **Step 7: 写 InsightCard 单测**

新建 `frontend/src/components/insights/__tests__/InsightCard.test.tsx`：

```typescript
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import InsightCard from '../InsightCard'

describe('InsightCard', () => {
  it('renders 律师补充 label when triggerSpeaker is lawyer', () => {
    render(<InsightCard insight={{
      id: 'i1', uttId: 'u1', text: 'hello',
      triggerSpeaker: 'lawyer', createdAt: '2026-05-31T00:00:00Z',
    }} />)
    expect(screen.getByText('律师补充')).toBeInTheDocument()
  })

  it('renders 实时洞察 label when triggerSpeaker is client', () => {
    render(<InsightCard insight={{
      id: 'i1', uttId: 'u1', text: 'hello',
      triggerSpeaker: 'client', createdAt: '2026-05-31T00:00:00Z',
    }} />)
    expect(screen.getByText('实时洞察')).toBeInTheDocument()
  })

  it('sets data-trigger-speaker attribute for visual differentiation', () => {
    const { container } = render(<InsightCard insight={{
      id: 'i1', uttId: 'u1', text: 'hello',
      triggerSpeaker: 'lawyer', createdAt: '2026-05-31T00:00:00Z',
    }} />)
    expect(container.querySelector('[data-trigger-speaker="lawyer"]')).toBeTruthy()
  })
})
```

- [ ] **Step 8: 跑前端 tsc + 单元测试**

```bash
cd frontend && pnpm tsc --noEmit && pnpm test -- InsightCard
```

预期：tsc 通过；3 个单测全部 PASS。

- [ ] **Step 9: 浏览器手测（启动后端 + 前端 + 模拟 lawyer trigger 事件）**

```bash
# 终端 1
cd backend && uv run uvicorn main:app --reload

# 终端 2
cd frontend && pnpm dev
```

打开浏览器进入会谈页面，制造一句律师话引发快答（最简单方式：在 sessionReducer 调试模式下手动 dispatch 一个 `insight.ready` 事件 with `trigger_speaker: 'lawyer'`，或在会谈中说一句律师话）。验证：律师补充卡片视觉上明显与当事人触发的实时洞察不同。

- [ ] **Step 10: Commit**

```bash
git add frontend/src/types/events.ts frontend/src/types/index.ts \
        frontend/src/context/sessionReducer.ts \
        frontend/src/components/insights/InsightCard.tsx \
        frontend/src/components/insights/__tests__/InsightCard.test.tsx
git commit -m "feat(frontend): InsightCard 按 triggerSpeaker 渲染差异化样式"
```

---

## Task 11: /history 接口验证

**Files:**
- Modify: `backend/tests/api/test_history.py`

- [ ] **Step 1: 写测试断言 history 接口返回包含 trigger_speaker**

在 `backend/tests/api/test_history.py` 追加：

```python
@pytest.mark.asyncio
async def test_history_returns_trigger_speaker_for_lawyer_insight(client, db_session):
    """会话恢复时，lawyer trigger 的 direct insight 也在 history 列表里，
    带正确的 trigger_speaker 字段。"""
    from repositories.suggestions import SuggestionRepository
    # 仿照同文件 setup pattern 构造 session + utterance
    # 插入 lawyer trigger 的 direct insight：
    #   await SuggestionRepository(db_session).insert_direct(
    #       sid, utt_id="u-lawyer-1", text="律师补充内容", trigger_speaker="lawyer",
    #   )
    # 调 /history 接口（沿用同文件已有 client 的调法）
    # 断言 response 列表里能找到 trigger_speaker="lawyer" 的那条
```

- [ ] **Step 2: 运行测试，预期 PASS（因为 Task 4 Step 5 已经让 list_by_session 输出 trigger_speaker）**

```bash
cd backend && uv run pytest tests/api/test_history.py -v
```

预期：新增测试 PASS；现有测试也 PASS。

- [ ] **Step 3: Commit**

```bash
git add backend/tests/api/test_history.py
git commit -m "test(api): /history 接口返回 trigger_speaker 字段回归"
```

---

## Task 12: E2E 测试 — 真模型三场景（@pytest.mark.slow）

**Files:**
- Create: `backend/tests/e2e/test_lawyer_quickreply_e2e.py`

- [ ] **Step 1: 按前置侦察结果调整 e2e 测试中的构造与调用**

根据前置检查里 `grep HeavyAgent` / `grep "def arun"` 的结果，调整下面测试代码中的：
- `HeavyAgent(...)` 构造参数（如是否需 `session_id`、`user_id`、或其他参数）
- `await ha.arun(...)` 调用参数（如是否需 `trigger`、或其他参数）
- `ContextStore()` 构造参数（如是否需 `session_id` 或其他初始化参数）
- `ctx.get_utterance(...)` 调用方式（如不存在，改用 `ctx.get_recent_window(10)[-1]` 或其他等价写法）

**不要直接复制本 plan 里的示例代码，而是以实际签名为准做最小改动。**

- [ ] **Step 2: 新建 e2e 测试文件**

新建 `backend/tests/e2e/test_lawyer_quickreply_e2e.py`：

```python
"""律师 utterance 触发快答的 e2e 测试。需要真实 DeepSeek API key。
判定标准：关键词集合存在性 + 长度阈值 + 称呼检查（不做字符串等值）。

运行：cd backend && uv run pytest -m slow tests/e2e/test_lawyer_quickreply_e2e.py -v
"""
from __future__ import annotations

import pytest

from agent.context_store import ContextStore
from agent.heavy_agent import HeavyAgent
from models.utterance import Utterance


def _addresses_lawyer(text: str) -> bool:
    """判定输出是否在对律师说话（含'你刚才'类的称呼）。"""
    return any(p in text for p in ("你刚才", "你方才", "建议你", "建议补", "你说的"))


@pytest.mark.slow
@pytest.mark.asyncio
async def test_e2e_lawyer_factual_error_triggers_correction():
    """场景 1 - 纠错：律师引错法条编号，模型应指出。"""
    ctx = ContextStore()  # 真实实例，按现有 conftest 注入参数
    # 喂入一句律师的错法条引用作为 trigger
    await ctx.append_utterance(Utterance(
        id="u1", text="根据《劳动合同法》第 86 条，加班费按 1.5 倍",
        speaker="lawyer", t_start=0.0, t_end=2.0, closed_by="vad",
    ))
    ha = HeavyAgent(ctx, session_id="e2e-1", user_id="e2e")
    trigger = await ctx.get_utterance("u1")
    run = await ha.arun(trigger)

    content = (getattr(run, "content", "") or "").strip()
    assert content, "模型不该完全沉默——错法条应该被指出"
    # 至少含「纠错」语义之一
    assert any(kw in content for kw in ("应为", "正确应是", "有误", "不准确", "建议核实")), \
        f"未检出纠错语义: {content!r}"
    assert _addresses_lawyer(content), f"未对律师称呼: {content!r}"


@pytest.mark.slow
@pytest.mark.asyncio
async def test_e2e_lawyer_skips_emotion_triggers_补全():
    """场景 2 - 补全：律师跳过当事人情绪直接问事实，模型应提示先共情。"""
    ctx = ContextStore()
    await ctx.append_utterance(Utterance(
        id="c1", text="我老公被警察带走了，我快崩溃了",
        speaker="client", t_start=0.0, t_end=2.0, closed_by="vad",
    ))
    await ctx.append_utterance(Utterance(
        id="l1", text="他被带去哪个派出所",
        speaker="lawyer", t_start=2.0, t_end=3.5, closed_by="vad",
    ))
    ha = HeavyAgent(ctx, session_id="e2e-2", user_id="e2e")
    trigger = await ctx.get_utterance("l1")
    run = await ha.arun(trigger)

    content = (getattr(run, "content", "") or "").strip()
    assert content, "模型不该完全沉默——明显的情绪未回应"
    assert any(kw in content for kw in ("情绪", "共情", "安抚", "先回应", "心理")), \
        f"未检出情绪/共情语义: {content!r}"
    assert _addresses_lawyer(content), f"未对律师称呼: {content!r}"


@pytest.mark.slow
@pytest.mark.asyncio
async def test_e2e_lawyer_single_path_advice_triggers_换角度():
    """场景 3 - 换角度：律师给当事人单一路径建议，模型应提示另解。"""
    ctx = ContextStore()
    await ctx.append_utterance(Utterance(
        id="c1", text="公司拖欠工资三个月了",
        speaker="client", t_start=0.0, t_end=2.0, closed_by="vad",
    ))
    await ctx.append_utterance(Utterance(
        id="l1", text="你可以申请劳动仲裁",
        speaker="lawyer", t_start=2.0, t_end=3.5, closed_by="vad",
    ))
    ha = HeavyAgent(ctx, session_id="e2e-3", user_id="e2e")
    trigger = await ctx.get_utterance("l1")
    run = await ha.arun(trigger)

    content = (getattr(run, "content", "") or "").strip()
    assert content, "模型不该完全沉默——单一路径建议可补充其他角度"
    assert any(kw in content for kw in ("也可", "另外", "或者", "还可以", "也建议", "考虑")), \
        f"未检出换角度语义: {content!r}"
    assert _addresses_lawyer(content), f"未对律师称呼: {content!r}"
```

⚠️ 上面 `ContextStore()` 的构造参数可能与项目实际不同，按 `backend/tests/agent/conftest.py` 中已有的 fixture 模式调整。`ctx.get_utterance(...)` 若不存在，使用 `ctx.get_recent_window(10)[-1]` 之类的等价方法。**实施时先看一眼 conftest 与 ContextStore 的现有用法，调整为最简最直接的真实接线**。

- [ ] **Step 3: 运行 e2e 测试**

```bash
cd backend && uv run pytest -m slow tests/e2e/test_lawyer_quickreply_e2e.py -v
```

预期：3 个测试 PASS（需要本地配置好 `DEEPSEEK_API_KEY`，且模型输出符合关键词期望——容许 1 次重试，因为是真模型）。

若某个用例的关键词集合判定过严，可在 spec 不变的前提下放宽关键词集合（如把"应为"补充进"建议复核"等同义词）。**不要为了通过把关键词去掉到只剩 1 个**，至少 2 个候选词才算有效守护。

- [ ] **Step 4: Commit**

```bash
git add backend/tests/e2e/test_lawyer_quickreply_e2e.py
git commit -m "test(e2e): 律师触发快答的真模型三场景测试"
```

---

## Task 13: 在 v3 tasks.md 追加补丁项 + 验收清单签收

**Files:**
- Modify: `specs/001-frontend-v3-redesign/tasks.md`

- [ ] **Step 1: 在 v3 tasks.md 追加 InsightCard 差异化样式条目**

打开 `specs/001-frontend-v3-redesign/tasks.md`，在合适位置追加（沿用文件现有任务编号格式）：

```markdown
- [x] InsightCard 按 trigger_speaker 渲染差异化样式（spec: backend/docs/superpowers/specs/2026-05-31-lawyer-utterance-quickreply-design.md，实施: backend/docs/superpowers/plans/2026-05-31-lawyer-utterance-quickreply.md Task 10）
```

打勾标记 `[x]` 因为本 plan 实施时这条同步完成。

- [ ] **Step 2: 跑全套测试套验证零回归**

```bash
cd backend && uv run pytest -v
cd ../frontend && pnpm test
```

预期：所有测试 PASS（含 client 主路所有现有测试）。

- [ ] **Step 3: 手测 AC 全过**

按 spec AC-1 ~ AC-7 逐条手测：

- **AC-1**：浏览器中律师说出"根据《劳动合同法》第 86 条，加班费按 1.5 倍"，5 秒内见纠错卡
- **AC-2**：当事人说"我老公被警察带走了，我快崩溃了"+ 律师立即问"哪个派出所"，5 秒内见情绪提示卡
- **AC-3**：当事人触发卡 vs 律师触发卡视觉一眼可辨
- **AC-4**：跑完 AC-1 / AC-2 后查 `psql -c "SELECT count(*) FROM profile_entries WHERE source_utt_id IN (SELECT id FROM utterances WHERE speaker='lawyer')"`，结果应为 0
- **AC-5**：断网重连后调 `/history`，返回包含本会话 lawyer trigger 卡（带 `trigger_speaker: 'lawyer'`）
- **AC-6**：跑完 AC-1 ~ AC-5 后 client 主路测试全绿（已在 Step 2 验证）
- **AC-7**：构造律师 trigger 使 HeavyAgent 调 `deep_analysis`（若实测难复现，跳过此手测，依赖 Task 9 集成测试守护）

- [ ] **Step 4: Commit + push**

```bash
git add specs/001-frontend-v3-redesign/tasks.md
git commit -m "docs(v3): 追加 InsightCard trigger_speaker 样式区分补丁条目"
git push -u origin HEAD
```

---

## Self-Review Notes（实施前阅读）

1. **Task 5 / 6 / 7 同 commit**：protocol 与 Orchestrator emit 同一 commit，避免中间状态崩。Task 5、6 的 "Commit" 步骤都说"留到 Task 7 一起 commit"。
2. **Task 4 Step 6 的 grep 必做**：现有测试中所有调 `insert_direct` / `upsert_pending` 的地方必须同步加 `trigger_speaker` 参数，漏一处就会 TypeError。
3. **Task 7 Step 3 的 emit 路径选择**：spec 明确"新功能走 typed event"。读 `orchestrator.py:218-272` 当前实际代码后，按现状选择是覆盖旧的 dict callback 路径，还是双路径并存。**保留 dict 路径仅当**测试或 main.py 显式依赖（grep `_emit\b` 看一眼）。
4. **Task 10 Step 5 的颜色值**：`text-amber-400` / `border-l-amber-400` 是占位，最终由 v3 设计稿审核——但 `data-trigger-speaker` 属性必须保留（测试与 e2e 选择器依赖）。
5. **Task 12 e2e 测试容错**：真模型有非确定性，关键词集合宽松一些；若反复抖动，标记 `@pytest.mark.flaky(reruns=2)` 而非降低断言强度。
6. **不做的事**：
   - 不动 `AnalysisProposed` schema（保持与 client trigger 视觉一致，AC-7 决定）
   - 不动 `upsert_ready` 签名（深析续跑结果时 trigger_speaker 在 pending 已定）
   - 不动 ProfileAgent（lawyer 不入画像硬约束保留）
   - 不动 `RelevanceGate`（沿用 0.5 阈值，TD-1 接受）
