"""SessionManager 核心逻辑测试。"""

import asyncio

import numpy as np
import pytest

from agent.context_store import ContextStore
from agent.orchestrator import Orchestrator
from diarization.enrollment import Enrollment
from models.utterance import Utterance
from session.manager import SessionManager
from session.persistence import InMemoryBackend


def _dummy_enrollment() -> Enrollment:
    return Enrollment(embedding=np.array([0.1, 0.2], dtype=np.float32))


@pytest.fixture
async def manager():
    be = InMemoryBackend()
    sm = SessionManager(be, snapshot_interval=9999.0, ttl=1.0)
    await sm.start()
    yield sm
    await sm.stop()


@pytest.mark.asyncio
class TestCreateAndAttach:
    async def test_create_session(self, manager):
        sid = await manager.create_session(_dummy_enrollment())
        assert sid
        state = await manager.get_state(sid)
        assert state is not None
        assert state.status == "active"

    async def test_attach_ws(self, manager):
        sid = await manager.create_session(_dummy_enrollment())
        ok = await manager.attach_ws(sid, object())
        assert ok is True
        state = await manager.get_state(sid)
        assert state.status == "active"

    async def test_attach_ws_exclusive(self, manager):
        sid = await manager.create_session(_dummy_enrollment())
        ok1 = await manager.attach_ws(sid, object())
        assert ok1 is True
        ok2 = await manager.attach_ws(sid, object())
        assert ok2 is False

    async def test_attach_missing_session(self, manager):
        ok = await manager.attach_ws("nope", object())
        assert ok is False


@pytest.mark.asyncio
class TestDetachAndRestore:
    async def test_detach_triggers_snapshot(self, manager):
        sid = await manager.create_session(_dummy_enrollment())
        ws = object()
        await manager.attach_ws(sid, ws)
        await manager.detach_ws(sid)
        state = await manager.get_state(sid)
        assert state.status == "disconnected"
        # 快照已写入后端
        assert manager._backend.load(sid) is not None

    async def test_restore_session(self, manager):
        sid = await manager.create_session(_dummy_enrollment())
        ws = object()
        await manager.attach_ws(sid, ws)
        await manager.detach_ws(sid)
        # 从内存中删除，模拟进程重启
        manager._sessions.pop(sid, None)
        restored = await manager.restore_session(sid)
        assert restored is not None
        assert restored.status == "disconnected"

    async def test_restore_missing(self, manager):
        restored = await manager.restore_session("nope")
        assert restored is None


@pytest.mark.asyncio
class TestAgentStateSync:
    async def test_update_agent_state(self, manager):
        sid = await manager.create_session(_dummy_enrollment())
        ctx = ContextStore()
        utt = Utterance(id="u1", text="hello", t_start=0.0, t_end=1.0, speaker="client")
        await ctx.append_utterance(utt)
        orch = Orchestrator(ctx)
        await manager.update_agent_state(sid, ctx, orch)
        state = await manager.get_state(sid)
        assert state.context_store["generation"] == 1


@pytest.mark.asyncio
class TestCleanup:
    async def test_cleanup_expired(self, manager):
        sid = await manager.create_session(_dummy_enrollment())
        ws = object()
        await manager.attach_ws(sid, ws)
        await manager.detach_ws(sid)
        # 快进时间超过 TTL
        import time
        for s in manager._sessions.values():
            s.last_active_at = time.monotonic() - 2.0
        await manager.cleanup_expired()
        assert await manager.get_state(sid) is None
