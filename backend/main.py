import json
import sys
from pathlib import Path

import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

sys.path.insert(0, str(Path(__file__).parent / "src"))
from agent import AnalysisResult, IntentResult, LegalAgent
from agno_agents import build_analyze_fn, build_execute_fn
from audio_pipeline import AudioPipeline

app = FastAPI()

_analyze_fn = build_analyze_fn()
_execute_fn = build_execute_fn()


def pipeline_factory() -> AudioPipeline:
    return AudioPipeline()


def agent_factory(on_intent, on_analysis) -> LegalAgent:
    return LegalAgent(
        on_intent=on_intent,
        on_analysis=on_analysis,
        analyze_fn=_analyze_fn,
        execute_fn=_execute_fn,
    )


@app.websocket("/ws/{session_id}")
async def legal_session(ws: WebSocket, session_id: str):
    await ws.accept()
    pipeline = pipeline_factory()

    async def on_intent(r: IntentResult) -> None:
        await ws.send_json({
            "type": "intent",
            "intent_id": r.intent_id,
            "question": r.question,
            "context": r.context,
        })

    async def on_analysis(r: AnalysisResult) -> None:
        await ws.send_json({
            "type": "analysis",
            "category": r.category,
            "title": r.title,
            "content": r.content,
            "citation": r.citation,
            "level": r.level,
        })

    agent = agent_factory(on_intent, on_analysis)

    try:
        while True:
            data = await ws.receive()

            if data["type"] == "websocket.disconnect":
                break

            if "bytes" in data:
                audio = np.frombuffer(data["bytes"], dtype=np.int16).astype(np.float32) / 32768.0
                results = await pipeline.process_segment(audio)
                for r in results:
                    await ws.send_json({
                        "type": "transcript",
                        "text": r.text,
                        "speaker": r.speaker,
                        "is_final": True,
                    })
                    await agent.observe(r.text, r.speaker)

            elif "text" in data:
                msg = json.loads(data["text"])
                msg_type = msg.get("type")
                if msg_type == "ping":
                    await ws.send_json({"type": "pong"})
                elif msg_type == "confirm_intent":
                    await agent.confirm_intent(msg["intent_id"])
                elif msg_type == "dismiss_intent":
                    agent.dismiss_intent(msg["intent_id"])

    except (WebSocketDisconnect, RuntimeError):
        pass
