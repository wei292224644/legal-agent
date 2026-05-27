import queue
import threading

import numpy as np
import pytest
from fastapi.testclient import TestClient

import main
from agent import AnalysisResult, IntentResult, LegalAgent
from audio_pipeline import AudioPipeline, TranscriptResult


def fake_pipeline(*sentences: tuple[str, str]):
    """Return an AudioPipeline whose model_fn yields the given (text, speaker) pairs."""
    roles = {i: role for i, (_, role) in enumerate(sentences)}
    call_idx = [-1]

    def model_fn(_audio):
        return [
            {"text": text, "start": i * 1000, "end": (i + 1) * 1000}
            for i, (text, _) in enumerate(sentences)
        ]

    def embedding_fn(_seg):
        call_idx[0] += 1
        # return a fixed vector; role is pre-seeded in cache below
        return np.zeros(3)

    pipeline = AudioPipeline(model_fn=model_fn, embedding_fn=embedding_fn if sentences else None)
    # Pre-seed the cache so roles resolve deterministically without real embeddings
    for i, (_, role) in enumerate(sentences):
        pipeline._embedding_cache[f"{i * 1000}-{(i + 1) * 1000}"] = role
    return pipeline


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "pipeline_factory", lambda: fake_pipeline())
    return TestClient(main.app)


# ── Connection ────────────────────────────────────────────────────────────────

def test_websocket_connect(client):
    with client.websocket_connect("/ws/test-session") as ws:
        assert ws


# ── Audio → transcript ────────────────────────────────────────────────────────

def test_pcm_bytes_produce_transcript_message(monkeypatch):
    monkeypatch.setattr(
        main, "pipeline_factory",
        lambda: fake_pipeline(("您好", "客户")),
    )
    with TestClient(main.app).websocket_connect("/ws/s1") as ws:
        ws.send_bytes(b"\x00" * 3200)
        msg = ws.receive_json()
        assert msg["type"] == "transcript"


def test_transcript_contains_text_and_speaker(monkeypatch):
    monkeypatch.setattr(
        main, "pipeline_factory",
        lambda: fake_pipeline(("根据劳动法第82条", "律师")),
    )
    with TestClient(main.app).websocket_connect("/ws/s2") as ws:
        ws.send_bytes(b"\x00" * 3200)
        msg = ws.receive_json()
        assert msg["text"] == "根据劳动法第82条"
        assert msg["speaker"] == "律师"
        assert msg["is_final"] is True


def test_silence_sends_no_transcript(monkeypatch):
    monkeypatch.setattr(
        main, "pipeline_factory",
        lambda: fake_pipeline(),  # empty → no sentences
    )
    received = queue.Queue()

    def run():
        with TestClient(main.app).websocket_connect("/ws/s3") as ws:
            ws.send_bytes(b"\x00" * 3200)
            ws.send_json({"type": "ping"})
            received.put(ws.receive_json())

    t = threading.Thread(target=run)
    t.start()
    t.join(timeout=3)
    msg = received.get_nowait()
    assert msg["type"] == "pong"  # pong arrived first, no transcript before it


# ── Ping / pong ───────────────────────────────────────────────────────────────

def test_websocket_ping_pong(client):
    with client.websocket_connect("/ws/ping-session") as ws:
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "pong"


# ── Agent integration ─────────────────────────────────────────────────────────

def fake_agent_factory(analyze_results=None, execute_results=None):
    async def fake_analyze(_profile, _ctx):
        return ("", analyze_results or [])

    async def fake_execute(_intent, _ctx):
        return execute_results or []

    def factory(on_intent, on_analysis):
        return LegalAgent(
            on_intent=on_intent,
            on_analysis=on_analysis,
            analyze_fn=fake_analyze,
            execute_fn=fake_execute,
        )
    return factory


def test_client_speech_produces_analysis_message(monkeypatch):
    analysis = AnalysisResult(category="statute", title="劳动合同法", content="...")
    monkeypatch.setattr(main, "pipeline_factory", lambda: fake_pipeline(("我没有签合同", "客户")))
    monkeypatch.setattr(main, "agent_factory", fake_agent_factory(analyze_results=[analysis]))

    with TestClient(main.app).websocket_connect("/ws/sa") as ws:
        ws.send_bytes(b"\x00" * 3200)
        msg1 = ws.receive_json()
        assert msg1["type"] == "transcript"
        msg2 = ws.receive_json()
        assert msg2["type"] == "analysis"
        assert msg2["category"] == "statute"


def test_confirm_intent_does_not_crash_server(monkeypatch):
    monkeypatch.setattr(main, "pipeline_factory", lambda: fake_pipeline())
    monkeypatch.setattr(main, "agent_factory", fake_agent_factory())

    with TestClient(main.app).websocket_connect("/ws/sc") as ws:
        ws.send_json({"type": "confirm_intent", "intent_id": "nonexistent"})
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "pong"


def test_dismiss_intent_does_not_crash_server(monkeypatch):
    monkeypatch.setattr(main, "pipeline_factory", lambda: fake_pipeline())
    monkeypatch.setattr(main, "agent_factory", fake_agent_factory())

    with TestClient(main.app).websocket_connect("/ws/sd") as ws:
        ws.send_json({"type": "dismiss_intent", "intent_id": "nonexistent"})
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "pong"
