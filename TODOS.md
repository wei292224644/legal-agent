# TODOS — legal-agent

## 已完成

- [x] **T1** — 后端 FastAPI 骨架 + WebSocket `/ws/{session_id}` 端点（4 tests）
- [x] **T2** — 前端 Vite + React + Tailwind + shadcn 脚手架
- [x] **T3** — `useWebSocket` hook：连接/断开/重连/心跳/消息回调（5 tests）
- [x] **T4** — `LiveSession` 页面：转写 + AI 侧边栏 UI
- [x] **T5** — `VoiceprintRegister` 页面：声纹注册流程 UI
- [x] **T6** — Vercel React Best Practices 重构

---

## 待实现

### P1 — 核心链路（阻塞 Demo）

- [ ] **T7** — 音频管道：pyannote VAD 切句 + embedding 声纹比对 + 千问 STT 流式转写
  - 文件：`backend/audio_pipeline.py`
  - 验证：`uv run pytest -k audio_pipeline`
  - 估时：human ~2h / CC ~30min

- [ ] **T8** — Agno Agent：deepseek-v4-pro + 法律 System Prompt + 流式 JSON 输出
  - 文件：`backend/agent/agent.py`, `backend/agent/tools.py`, `backend/agent/prompt.py`
  - Tools：`statute_lookup`, `contract_template`, `risk_assess`
  - 验证：`uv run pytest -k agent`
  - 估时：human ~1h / CC ~20min

- [ ] **T9** — 前后端打通：WebSocket 音频上行 → 转写下行 → 分析下行
  - 文件：`backend/main.py`, `frontend/src/pages/LiveSession.tsx`
  - 验证：端到端手动测试
  - 估时：human ~1h / CC ~15min

### P2 — Demo 准备

- [ ] **T10** — 声纹注册后端 API：`POST /api/voiceprint/register`
  - 文件：`backend/voiceprint.py`
  - 验证：`uv run pytest -k voiceprint`
  - 估时：human ~30min / CC ~10min

- [ ] **T11** — 前端口采集 MediaRecorder 集成到 LiveSession
  - 文件：`frontend/src/hooks/useMediaRecorder.ts`
  - 验证：Chrome 手动测试
  - 估时：human ~30min / CC ~10min

- [ ] **T12** — Demo 劳动争议对话脚本
  - 文件：`demo-script.md`
  - 内容：5 分钟律师 vs 客户对话，触发劳动合同法、赔偿标准、风险提示
  - 估时：human ~30min

### P3 — 体验打磨

- [ ] **T13** — API key 管理：`.env` 文件 + `python-dotenv`
  - 估时：human ~10min

- [ ] **T14** — 前端错误状态：WebSocket 断开提示、STT/LM 超时降级
  - 估时：human ~30min / CC ~10min

- [ ] **T15** — Demo 兜底录像：录 3 分钟正常流程屏幕录像
  - 估时：human ~10min
