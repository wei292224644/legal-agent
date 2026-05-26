# Handoff: legal-agent — T7 音频管道

**日期:** 2026-05-26
**分支:** main
**仓库:** git@github.com:wei292224644/legal-agent.git

## 项目概况

法律会谈实时 AI 辅助系统。律师与客户会谈时，浏览器采集音频 → 后端实时转写 + 声纹区分角色 → AI 侧边栏弹出法规/合同/风险卡片。

## 当前进度

已完成 T1-T6，待实现 T7-T15。见 `TODOS.md`。

## 本次任务：T7 音频管道

实现 `backend/audio_pipeline.py`：**pyannote VAD 切句 → pyannote embedding 声纹比对 → 千问 STT 流式转写**。

### 技术决策（已确认）

| 组件 | 选择 | 理由 |
|------|------|------|
| VAD | pyannote/voice-activity-detection | 与声纹统一依赖，~5ms |
| 声纹 | pyannote/embedding → 余弦相似度 | >0.85 → 律师，<0.50 → 客户 |
| STT | 千问 STT API（流式） | 中文 + 法律术语准确率高 |
| 音频格式 | MediaRecorder webm/opus → ffmpeg → 16kHz PCM WAV | 浏览器 → 千问兼容格式 |
| Agent 框架 | Agno（含 session 管理 + SqliteDb） | 已安装，直接使用 |
| Agent LLM | deepseek-v4-pro | 流式 JSON 输出 |

### 声纹比对策略

```
VAD 检测到说话人切换 → 取前 1.5s 音频做声纹比对 → 确定角色
同一说话人继续说 → 不复核对，沿用标签
律师声纹预注册：朗读 15s → embedding → 存 .npy 文件
Demo 中声纹可预置，现场直接加载
```

### 并行管道

```
音频到达 → VAD(5ms) ─┬→ 千问STT(500ms) ─────────→ 文字先出
                    └→ 声纹比对(100ms) ─→ 角色标签贴上
```

### 端到端延迟预算

音频采集(100ms) → VAD(5ms) → 声纹(100ms，仅切换时) → STT(500ms) → Agent(500ms) → 渲染(100ms) = **<1.5s**

### 文件结构

```
backend/
  main.py              — FastAPI + WebSocket（已实现，4 tests）
  audio_pipeline.py    — [T7] VAD → 声纹 → STT
  voiceprint.py        — [T10] 声纹注册 API
  agent/
    agent.py           — [T8] Agno Agent
    tools.py           — [T8] @tool: statute_lookup, contract_template, risk_assess
    prompt.py          — [T8] System Prompt

frontend/
  src/
    hooks/
      useWebSocket.ts  — WebSocket hook（已实现，5 tests）
      useMediaRecorder.ts — [T11] 录音 hook
    pages/
      LiveSession.tsx  — 会谈页（已实现）
      VoiceprintRegister.tsx — 声纹注册页（已实现）
```

### 相关文档

- 设计文档：`docs/design.md`
- TODO 列表：`TODOS.md`
- CLAUDE.md：项目指引（含 gstack skill routing）
- 测试计划：`~/.gstack/projects/legal-agent/wwj-main-eng-review-test-plan-20260526-231016.md`

### 后端启动

```bash
cd backend && uv run uvicorn main:app --reload --port 8000
```

### 前端启动

```bash
cd frontend && pnpm dev
```

### 运行测试

```bash
cd backend && uv run pytest -v
cd frontend && pnpm vitest run && pnpm lint && pnpm tsc --noEmit
```

## 建议的 Skills

下一个 session 应按顺序调用：

1. `/tdd` — 以 TDD 方式实现 T7 音频管道
2. 后端先写测试：VAD 检测、声纹比对、STT 转写
3. 然后 T8 Agno Agent，最后 T9 前后端打通
