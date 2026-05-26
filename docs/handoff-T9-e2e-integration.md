# Handoff: legal-agent — T9 端到端集成

**日期:** 2026-05-26 | **分支:** main | **前置任务:** T7+T8

## 任务目标

打通前后端完整链路：**浏览器录音 → WebSocket → 音频管道 → STT 转写 → Agent 分析 → WebSocket → 前端渲染**。

## 当前状态

| 组件 | 状态 | 说明 |
|------|------|------|
| T7 音频管道 | 🔴 未实现 | pyannote VAD + 声纹 + 千问 STT |
| T8 Agno Agent | 🔴 未实现 | deepseek-v4-pro + tools |
| 后端 WebSocket | 🟢 已实现 | `/ws/{session_id}` 连接/心跳/ack/模拟转写 |
| 前端 WebSocket hook | 🟢 已实现 | 连接/重连/消息回调，5 tests |
| 前端 LiveSession | 🟢 已实现 | 转写展示 + AI 侧边栏，memo 优化 |
| 前端 VoiceprintRegister | 🟢 已实现 | 声纹注册 UI |

## 集成目标

### 数据流（完整链路）

```
浏览器                              后端                              外部服务
─────────────────      ──────────────────────      ──────────────────
MediaRecorder           WebSocket /ws/{id}
  │ audio_chunk          │
  ├──────────────────────▶│
  │                       ├─ audio_pipeline.py
  │                       │  VAD → 声纹 → STT ──▶ 千问 STT API
  │                       │                          
  │  transcript           │◀── {"speaker":"律师", "text":"..."}
  │◀──────────────────────│                          
  │                       ├─ agent/agent.py ──▶ deepseek-v4-pro
  │                       │
  │  analysis             │◀── {"category":"statute", ...}
  │◀──────────────────────│
  │                       │
  │  status               │◀── {"status":"listening"}
  │◀──────────────────────│
```

### 后端 main.py 集成点

```python
# 伪代码 —— 将 T7+T8 产出接入现有 WebSocket handler

from audio_pipeline import process_audio_chunk  # T7
from agent.agent import analyze_transcript      # T8

@app.websocket("/ws/{session_id}")
async def legal_session(ws: WebSocket, session_id: str):
    await ws.accept()
    while True:
        data = await ws.receive()
        if "bytes" in data:
            # T7: 音频 → 转写
            transcript = await process_audio_chunk(data["bytes"])
            await ws.send_json({
                "type": "transcript",
                "text": transcript.text,
                "speaker": transcript.speaker,
                "is_final": True,
            })
            # T8: 转写 → 分析
            if transcript.is_final:
                async for analysis_chunk in analyze_transcript(transcript):
                    await ws.send_json(analysis_chunk)
```

### 前端 LiveSession 集成点

```typescript
// useWebSocket 已就绪，只需接入 MediaRecorder 和 analysis 回调

const { isConnected, sendAudioChunk } = useWebSocket(
  `ws://localhost:8000/ws/${sessionId}`,
  {
    onTranscript: (data) => { /* 追加到 transcript state */ },
    onAnalysis: (data) => { /* 追加到 analyses state，卡片自动弹出 */ },
  }
)

// MediaRecorder → sendAudioChunk
mediaRecorder.ondataavailable = (e) => sendAudioChunk(new Uint8Array(e.data))
```

## 验证清单

| # | 验证项 | 方式 |
|---|--------|------|
| 1 | 录音 → WebSocket → 后端收到音频块 | 后端日志 |
| 2 | 音频块 → STT 转写 → WebSocket 返回 transcript | 前端转写区域出现文字 |
| 3 | transcript → Agent 分析 → WebSocket 返回 analysis | 侧边栏卡片弹出 |
| 4 | 声纹自动区分律师/客户角色 | 转写标签正确 |
| 5 | 端到端延迟 < 2s | 秒表测量"说话→卡片出现" |
| 6 | WebSocket 断线 → 重连 → 状态恢复 | 手动断网测试 |
| 7 | 完整 5 分钟 Demo 脚本跑通 | 劳动争议对话全流程 |

## 文件变更范围

```
backend/main.py              — 替换模拟转写，接入 T7+T8 真实管道
frontend/src/
  pages/LiveSession.tsx      — 接入 MediaRecorder，连接 sendAudioChunk
  hooks/useMediaRecorder.ts  — [新增] 录音 hook（T11，可与 T9 合并实现）
```

## 估时

human ~1h / CC ~15min

## 前置依赖

- T7 `backend/audio_pipeline.py` 已完成
- T8 `backend/agent/agent.py` 已完成
- 千问 STT API key、DeepSeek API key 已配置在 `backend/.env`

## 建议 Skills

1. `/tdd` — 端到端测试 + 集成实现
2. 参考 `docs/design.md` 完整架构
3. 参考 `docs/handoff-T7-audio-pipeline.md` 音频管道接口
4. 参考 `docs/handoff-T8-agno-agent.md` Agent 接口
