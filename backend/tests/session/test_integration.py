"""Session 集成测试：验证 WebSocket 接管与状态恢复。"""

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
class TestSocketTakeover:
    async def _create_session(self, client: TestClient, session_id: str | None = None) -> str:
        """通过 REST API 创建 session。"""
        resp = client.post("/api/sessions")
        assert resp.status_code == 200
        sid = resp.json()["session_id"]
        return sid

    async def test_reconnect_after_disconnect(self, session_manager_fixture):
        """断开 WebSocket 后，用相同 session_id 重连应成功恢复 session。"""
        client = TestClient(main.app)
        sid = await self._create_session(client)

        # 第一次连接
        with client.websocket_connect(f"/ws/{sid}") as ws1:
            pass

        # 断开连接后，session 应变为 disconnected 并持久化
        sm = session_manager_fixture
        state = await sm.get_state(sid)
        assert state is not None
        assert state.status == "disconnected"

        # 重连
        with client.websocket_connect(f"/ws/{sid}") as ws2:
            state = await sm.get_state(sid)
            assert state is not None
            assert state.status == "active"

    async def test_new_socket_replaces_old(self, session_manager_fixture):
        """已有 active session 时，新 WebSocket 应接管旧连接（old ws 收到 4000）。"""
        client = TestClient(main.app)
        sid = await self._create_session(client)

        with client.websocket_connect(f"/ws/{sid}") as ws1:
            # 第二个连接把第一个顶掉
            with pytest.raises(WebSocketDisconnect) as exc_info:
                with client.websocket_connect(f"/ws/{sid}") as ws2:
                    ws2.receive_text()  # 触发连接关闭异常

            assert exc_info.value.code == 4000
            assert "新连接" in exc_info.value.reason or "接管" in exc_info.value.reason

    async def test_reconnect_restores_agent_state(self, session_manager_fixture):
        """断开并模拟进程重启后，重连应恢复 Agent 状态（context_store + orchestrator）。"""
        from agent.context_store import ContextStore
        from agent.orchestrator import Orchestrator

        client = TestClient(main.app)
        sid = await self._create_session(client)

        # 第一次连接
        with client.websocket_connect(f"/ws/{sid}") as ws1:
            pass

        sm = session_manager_fixture

        # 通过公共接口注入 Agent 状态（模拟一次对话后的结果）
        ctx = ContextStore()
        orch = Orchestrator(ctx)
        await sm.update_agent_state(sid, ctx, orch)
        await sm.detach_ws(sid)

        # 模拟进程重启：内存中的 session 被清空，但后端已持久化
        sm._sessions.pop(sid, None)
        assert await sm.get_state(sid) is None

        # 重连：main.py 会先 get_state（None）→ restore_session（从后端加载）
        with client.websocket_connect(f"/ws/{sid}") as ws2:
            state = await sm.get_state(sid)
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
        sid = await self._create_session(client)

        with client.websocket_connect(f"/ws/{sid}") as ws:
            ws.send_json({"type": "close"})

        # 等待后台异步 task 生成 summary
        await asyncio.sleep(0.2)

        sm = session_manager_fixture
        state = await sm.get_state(sid)
        assert state is not None
        assert state.status == "closed"
        assert state.summary == "test summary"

    async def test_session_not_found(self, session_manager_fixture):
        """不存在的 session_id 连接应返回 4002。"""
        client = TestClient(main.app)

        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/ws/non-existent-id") as ws:
                ws.receive_text()

        assert exc_info.value.code == 4002

    async def test_session_closed(self, session_manager_fixture):
        """已关闭的 session 再次连接应返回 4001。"""
        client = TestClient(main.app)
        sid = await self._create_session(client)

        with client.websocket_connect(f"/ws/{sid}") as ws:
            ws.send_json({"type": "close"})

        # 等 close 处理完
        await asyncio.sleep(0.2)

        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(f"/ws/{sid}") as ws:
                ws.receive_text()

        assert exc_info.value.code == 4001
