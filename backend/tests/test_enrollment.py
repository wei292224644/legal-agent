"""Enrollment API 测试。"""
from __future__ import annotations

import io
import uuid

import numpy as np
import pytest
import soundfile as sf
from httpx import ASGITransport, AsyncClient

from main import app
from tests.streaming_fixtures import SHORT_LAWYER_WAV


@pytest.fixture
async def async_client():
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_get_session_no_enrollment(async_client):
    """新创建的 session 没有 enrollment，has_enrollment 应为 False。"""
    resp = await async_client.post("/api/sessions")
    assert resp.status_code == 200
    sid = resp.json()["session_id"]

    resp = await async_client.get(f"/api/sessions/{sid}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_enrollment"] is False
    assert data["status"] == "active"


@pytest.mark.asyncio
async def test_upload_enrollment_and_query(async_client):
    """上传声纹后，has_enrollment 应为 True。"""
    resp = await async_client.post("/api/sessions")
    sid = resp.json()["session_id"]

    with open(SHORT_LAWYER_WAV, "rb") as f:
        resp = await async_client.post(
            f"/api/sessions/{sid}/enrollment",
            files={"audio": ("test.wav", f, "audio/wav")},
        )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    resp = await async_client.get(f"/api/sessions/{sid}")
    assert resp.json()["has_enrollment"] is True


@pytest.mark.asyncio
async def test_upload_invalid_audio_returns_400(async_client):
    """上传非音频内容应返回 400。"""
    resp = await async_client.post("/api/sessions")
    sid = resp.json()["session_id"]

    resp = await async_client.post(
        f"/api/sessions/{sid}/enrollment",
        files={"audio": ("bad.txt", b"not audio", "text/plain")},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_upload_too_short_audio_returns_400(async_client):
    """上传过短音频（< 1s）应返回 400。"""
    resp = await async_client.post("/api/sessions")
    sid = resp.json()["session_id"]

    silence = np.zeros(int(16000 * 0.5), dtype=np.float32)
    buf = io.BytesIO()
    sf.write(buf, silence, 16000, format="WAV", subtype="PCM_16")
    buf.seek(0)

    resp = await async_client.post(
        f"/api/sessions/{sid}/enrollment",
        files={"audio": ("short.wav", buf, "audio/wav")},
    )
    assert resp.status_code == 400
