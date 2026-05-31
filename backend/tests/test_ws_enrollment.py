"""WS enrollment 连接测试。"""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from main import app
from tests.streaming_fixtures import SHORT_LAWYER_WAV


def test_ws_accepts_with_enrollment():
    """有 enrollment 的 session 可以正常建立 WS 并收发消息。"""
    with TestClient(app) as client:
        resp = client.post("/api/sessions")
        sid = resp.json()["session_id"]

        with open(SHORT_LAWYER_WAV, "rb") as f:
            resp = client.post(
                f"/api/sessions/{sid}/enrollment",
                files={"audio": ("test.wav", f, "audio/wav")},
            )
        assert resp.status_code == 200

        with client.websocket_connect(f"/ws/{sid}") as ws:
            ws.send_json({"type": "ping"})
            msg = ws.receive_json()
            assert msg["type"] == "pong"


def test_ws_rejected_without_enrollment():
    """无 enrollment 的 session 连 WS 会被服务器关闭。"""
    with TestClient(app) as client:
        resp = client.post("/api/sessions")
        sid = resp.json()["session_id"]

        with client.websocket_connect(f"/ws/{sid}") as ws:
            with pytest.raises(Exception):
                ws.receive_text()
