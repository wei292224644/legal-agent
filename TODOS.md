# TODOS — legal-agent

## 已完成

- [x] **T1** — 后端 FastAPI 骨架 + WebSocket `/ws/{session_id}` 端点（4 tests）
- [x] **T2** — 前端 Vite + React + Tailwind + shadcn 脚手架
- [x] **T3** — `useWebSocket` hook：连接/断开/重连/心跳/消息回调（5 tests）
- [x] **T4** — `LiveSession` 页面：转写 + AI 侧边栏 UI
- [x] **T5** — `VoiceprintRegister` 页面：声纹注册流程 UI
- [x] **T6** — Vercel React Best Practices 重构
- [x] **T7** — 音频管道：FunASR `fsmn-vad` 切句 + `cam++` 声纹比对 + `paraformer-zh` 流式转写
  - 文件：`backend/src/stt/funasr_stream.py`, `backend/src/diarization/`
- [x] **T8** — 三层 Agent：IntentRouter（千问意图分类）+ ProfileAgent（事实提取）+ HeavyAgent（Agno + DeepSeek 深度分析 + Skill）
  - 文件：`backend/src/agent/`
- [x] **T9** — 前后端打通：WebSocket 音频上行 → 转写下行 → 建议下行（suggestion.pending/ready + confirm/dismiss）
  - 文件：`backend/main.py`, `frontend/src/pages/LiveSession.tsx`, `frontend/src/hooks/useWebSocket.ts`

---

## 待实现

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

---

### P2 — Session 架构

- [x] **T16** — Session 管理核心：SessionManager + SessionState + 排他连接
  - 文件：`backend/src/session/manager.py`, `models.py`, `persistence.py`, `serializer.py`
  - 验证：`uv run pytest backend/tests/session/` ✅ 26 passed
  - 估时：human ~3h / CC ~30min

- [x] **T17** — WebSocket handler 重构：连接恢复、断开快照、TTL
  - 文件：`backend/main.py`
  - 验证：语法检查通过，WebSocket 接入 SessionManager
  - 估时：human ~2h / CC ~20min

- [x] **T18** — Agent 状态序列化：ContextStore + Orchestrator to_dict/from_dict
  - 文件：`backend/src/agent/context_store.py`, `orchestrator.py`
  - 验证：序列化往返测试 ✅
  - 估时：human ~1h / CC ~15min

- [x] **T19** — 前端重连支持：useWebSocket 携带 session_id
  - 文件：`frontend/src/hooks/useWebSocket.ts`
  - 验证：`pnpm lint` 通过
  - 估时：human ~30min / CC ~10min

- [x] **T20** — Session 模块完整测试（3 个测试文件，26 个用例）
  - 估时：human ~2h / CC ~20min

- [x] **T21** — 会谈 AI 摘要：Session 关闭时自动生成结构化摘要
  - 文件：`backend/src/session/summary.py`, `backend/main.py`
  - 验证：关闭 Session 时调用 generate_summary，失败仅记录日志
  - 估时：human ~2h / CC ~15min
  - 来源：CEO Review EXP1（已接受）

- [ ] **T22** — 会谈数据导出：导出为 Markdown/Word/PDF（推迟）
  - 文件：`backend/src/session/export.py`, 前端导出按钮
  - 验证：导出文件格式正确
  - 估时：human ~3h / CC ~20min
  - 来源：CEO Review EXP3（推迟）
