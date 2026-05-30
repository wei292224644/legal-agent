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
