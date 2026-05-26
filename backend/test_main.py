import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_websocket_connect():
    """WebSocket 连接建立成功"""
    with client.websocket_connect("/ws/test-session-123") as ws:
        assert ws  # 连接成功


def test_websocket_audio_chunk_echo():
    """发送音频块，后端确认收到"""
    with client.websocket_connect("/ws/test-session-456") as ws:
        ws.send_bytes(b"\x00\x01\x02\x03")  # 模拟音频数据
        response = ws.receive_json()
        assert response["type"] == "ack"
        assert response["size"] == 4


def test_websocket_transcript():
    """发送音频块后收到模拟转写结果"""
    with client.websocket_connect("/ws/test-session-789") as ws:
        ws.send_bytes(b"fake audio chunk")
        # 先收到 ack
        ws.receive_json()
        # 然后收到 transcript
        response = ws.receive_json()
        assert response["type"] == "transcript"
        assert "text" in response
        assert "speaker" in response


def test_websocket_ping_pong():
    """心跳 ping/pong"""
    with client.websocket_connect("/ws/test-session-ping") as ws:
        ws.send_json({"type": "ping"})
        response = ws.receive_json()
        assert response["type"] == "pong"
