"""Session 集成测试：验证 WebSocket 重连与状态恢复。"""

import asyncio
from unittest.mock import AsyncMock

import numpy as np
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import main
from diarization.enrollment import Enrollment
from session.manager import SessionManager
from session.persistence import InMemoryBackend


def _stub_enrollment() -> Enrollment:
    return Enrollment(embedding=np.array([0.1, 0.2], dtype=np.float32))


@pytest.fixture
async def session_manager_fixture(monkeypatch):
    """提供一个已启动的 SessionManager（内存后端），并注入 main.py。"""
    backend = InMemoryBackend()
    sm = SessionManager(backend, snapshot_interval=9999.0, ttl=600.0)
    await sm.start()

    monkeypatch.setattr(main, "session_manager", sm)
    monkeypatch.setattr(main, "_lawyer_enrollment", _stub_enrollment())

    # mock stream_stt 避免加载真实 STT 模型
    async def _mock_stream_stt(audio_iter, *, enrollment):
        # 空 async generator:不产出任何 utterance,但有合法 __aiter__
        return
        yield  # pragma: no cover  # 让 Python 识别此函数为 async generator

    monkeypatch.setattr(main, "stream_stt", _mock_stream_stt)

    yield sm
    await sm.stop()


@pytest.mark.asyncio
class TestReconnect:
    async def test_reconnect_after_disconnect(self, session_manager_fixture):
        """断开 WebSocket 后，用相同 session_id 重连应成功恢复 session。"""
        client = TestClient(main.app)

        # 第一次连接
        with client.websocket_connect("/ws/reconnect-test-1") as ws1:
            # 等待连接建立即可
            pass

        # 断开连接后，session 应变为 disconnected 并持久化
        sm = session_manager_fixture
        state = await sm.get_state("reconnect-test-1")
        assert state is not None
        assert state.status == "disconnected"

        # 重连
        with client.websocket_connect("/ws/reconnect-test-1") as ws2:
            state = await sm.get_state("reconnect-test-1")
            assert state is not None
            assert state.status == "active"

    async def test_exclusive_connection(self, session_manager_fixture):
        """已有 active session 时，新 WebSocket 连接应被拒绝（code 1008）。"""
        client = TestClient(main.app)

        with client.websocket_connect("/ws/exclusive-test-1") as ws1:
            # session 已 active，尝试第二个连接
            with pytest.raises(WebSocketDisconnect) as exc_info:
                with client.websocket_connect("/ws/exclusive-test-1") as ws2:
                    ws2.receive_text()  # 触发连接关闭异常

            assert exc_info.value.code == 1008
            assert "already connected" in exc_info.value.reason

    async def test_reconnect_restores_agent_state(self, session_manager_fixture):
        """断开并模拟进程重启后，重连应恢复 Agent 状态（context_store + orchestrator）。"""
        from agent.context_store import ContextStore
        from agent.orchestrator import Orchestrator

        client = TestClient(main.app)

        # 第一次连接建立 session
        with client.websocket_connect("/ws/state-test-1") as ws1:
            pass

        sm = session_manager_fixture

        # 通过公共接口注入 Agent 状态（模拟一次对话后的结果）
        ctx = ContextStore()
        orch = Orchestrator(ctx)
        await sm.update_agent_state("state-test-1", ctx, orch)
        await sm.detach_ws("state-test-1")

        # 模拟进程重启：内存中的 session 被清空，但后端已持久化
        sm._sessions.pop("state-test-1", None)
        assert await sm.get_state("state-test-1") is None

        # 重连：main.py 会先 get_state（None）→ restore_session（从后端加载）
        with client.websocket_connect("/ws/state-test-1") as ws2:
            state = await sm.get_state("state-test-1")
            assert state is not None
            assert state.status == "active"
            assert state.context_store.get("generation") == 0
            assert state.orchestrator is not None

    async def test_close_session_generates_summary(self, session_manager_fixture, monkeypatch):
        """客户端发送 close 消息后，session 应关闭并保存 AI 摘要。"""
        async def _mock_summary(ctx):
            return "test summary"

        monkeypatch.setattr(main, "generate_summary", _mock_summary)

        client = TestClient(main.app)

        with client.websocket_connect("/ws/close-test-1") as ws:
            ws.send_json({"type": "close"})

        # 等待后台异步 task 生成 summary
        await asyncio.sleep(0.2)

        sm = session_manager_fixture
        state = await sm.get_state("close-test-1")
        assert state is not None
        assert state.status == "closed"
        assert state.summary == "test summary"

