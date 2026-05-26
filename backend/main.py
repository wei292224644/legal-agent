from fastapi import FastAPI, WebSocket, WebSocketDisconnect

app = FastAPI()


@app.websocket("/ws/{session_id}")
async def legal_session(ws: WebSocket, session_id: str):
    await ws.accept()

    import json

    try:
        while True:
            data = await ws.receive()

            if data["type"] == "websocket.disconnect":
                break

            if "bytes" in data:
                audio_chunk = data["bytes"]
                await ws.send_json({"type": "ack", "size": len(audio_chunk)})
                await ws.send_json({
                    "type": "transcript",
                    "text": "模拟转写结果",
                    "speaker": "未知",
                    "is_final": False,
                })

            elif "text" in data:
                msg = json.loads(data["text"])
                if msg.get("type") == "ping":
                    await ws.send_json({"type": "pong"})

    except (WebSocketDisconnect, RuntimeError):
        pass
