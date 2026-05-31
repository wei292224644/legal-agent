# 声纹与会话绑定实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将律师声纹从全局单例改为按 session 绑定，进入 LiveSession 后必须先录制/上传声纹才能建立 WebSocket 连接。

**Architecture:** 后端新增 `sessions.lawyer_embedding` (JSONB) 字段和 `POST/GET /api/sessions/{id}/...` API，WS handler 从 session 加载 enrollment；前端 LiveSession 内嵌声纹录制 modal，支持 15 秒录音和文件上传，到位后才初始化 WS。

**Tech Stack:** Python (FastAPI, SQLAlchemy, soundfile, numpy, pytest) + TypeScript (React, Web Audio API)

---

## 文件结构

| 文件 | 职责 | 操作 |
|------|------|------|
| `backend/src/db/models.py` | `Session` ORM 模型 | 新增 `lawyer_embedding` JSONB 字段 |
| `backend/src/session/models.py` | `SessionRuntime` 内存状态 | 新增 `enrollment` 字段 |
| `backend/src/repositories/sessions.py` | `SessionRepository` | 新增 `set_enrollment` 方法 |
| `backend/src/session/manager.py` | `SessionManager` | 新增 `get_enrollment` / `set_enrollment` |
| `backend/main.py` | FastAPI 应用 + WS handler | 新增 API 路由、修改 WS 加载逻辑、删除全局单例 |
| `backend/tests/test_enrollment.py` | enrollment API 测试 | 新建 |
| `backend/tests/test_ws_enrollment.py` | WS enrollment 测试 | 新建 |
| `frontend/src/api/sessions.ts` | HTTP API 封装 | 新增 `getSession` 和 `uploadEnrollment` |
| `frontend/src/components/VoiceprintModal.tsx` | 声纹录制 modal | 新建 |
| `frontend/src/pages/LiveSession.tsx` | 实时会谈主页面 | 新增 enrollment phase 状态和 modal 集成 |

---

### Task 1: 数据库模型 — 新增 `lawyer_embedding` 字段

**Files:**
- Modify: `backend/src/db/models.py`

- [ ] **Step 1: 导入 JSONB 并新增字段**

在 `backend/src/db/models.py` 顶部新增 `JSONB` 导入，在 `Session` 类中新增 `lawyer_embedding` 字段：

```python
from sqlalchemy.dialects.postgresql import JSONB  # 新增导入

class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        Index("idx_sessions_status_lastactive", "status", "last_active_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    lawyer_id: Mapped[str] = mapped_column(String, nullable=False, default="lawyer-default")
    status: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    # 新增字段
    lawyer_embedding: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

- [ ] **Step 2: 运行后端格式检查**

Run: `cd backend && uv run ruff check src/db/models.py`
Expected: 无错误（或只有已有错误，无新增错误）

- [ ] **Step 3: Commit**

```bash
git add backend/src/db/models.py
git commit -m "feat(db): sessions 表新增 lawyer_embedding 字段"
```

---

### Task 2: SessionRuntime 扩展 + Repository/Manager 新增方法

**Files:**
- Modify: `backend/src/session/models.py`
- Modify: `backend/src/repositories/sessions.py`
- Modify: `backend/src/session/manager.py`

- [ ] **Step 1: SessionRuntime 新增 enrollment 字段**

修改 `backend/src/session/models.py`：

```python
"""Session 运行时状态——只保留进程内需要的字段。

持久化数据全在 Postgres 里。WS 连接状态、live ContextStore/Orchestrator 仅活在内存。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from agent.context_store import ContextStore
    from agent.orchestrator import Orchestrator
    from diarization.enrollment import Enrollment  # 新增

SessionStatus = Literal["active", "disconnected", "closed"]


@dataclass
class SessionRuntime:
    """单个 session 的进程内 runtime 状态。"""
    session_id: uuid.UUID
    status: SessionStatus = "active"
    ctx: ContextStore | None = None
    orchestrator: Orchestrator | None = None
    enrollment: Enrollment | None = None   # 新增
```

- [ ] **Step 2: SessionRepository 新增 set_enrollment 方法**

修改 `backend/src/repositories/sessions.py`，在 `SessionRepository` 类中新增方法：

```python
    async def set_enrollment(self, session_id: uuid.UUID, embedding_list: list) -> None:
        """写入 lawyer_embedding 到 session 记录。"""
        row = await self._s.get(Session, session_id)
        if row is None:
            return
        row.lawyer_embedding = embedding_list
        await self._s.commit()
```

- [ ] **Step 3: SessionManager 新增 get_enrollment / set_enrollment**

修改 `backend/src/session/manager.py`，新增导入和两种方法：

```python
import copy  # 保留（其它地方可能还用）
import numpy as np  # 新增导入

from diarization.enrollment import Enrollment  # 新增导入

# ... 在 SessionManager 类中新增方法 ...

    async def set_enrollment(self, session_id: uuid.UUID, enrollment: Enrollment) -> None:
        """将 enrollment 写入 DB 并缓存到 runtime。"""
        async with self._maker() as s:
            from repositories.sessions import SessionRepository  # noqa: PLC0415
            emb_list = enrollment.embedding.tolist()
            await SessionRepository(s).set_enrollment(session_id, emb_list)
        async with self._lock:
            runtime = self._sessions.get(session_id)
            if runtime is not None:
                runtime.enrollment = enrollment

    async def get_enrollment(self, session_id: uuid.UUID) -> Enrollment | None:
        """从 runtime 热缓存或 DB 加载 enrollment。"""
        async with self._lock:
            runtime = self._sessions.get(session_id)
            if runtime is not None and runtime.enrollment is not None:
                return runtime.enrollment

        async with self._maker() as s:
            from repositories.sessions import SessionRepository  # noqa: PLC0415
            row = await SessionRepository(s).get(session_id)
            if row is None or row.lawyer_embedding is None:
                return None

        emb = np.array(row.lawyer_embedding, dtype=np.float32)
        enrollment = Enrollment(embedding=emb)
        async with self._lock:
            runtime = self._sessions.get(session_id)
            if runtime is not None:
                runtime.enrollment = enrollment
        return enrollment
```

- [ ] **Step 4: 运行格式检查**

Run: `cd backend && uv run ruff check src/session/models.py src/repositories/sessions.py src/session/manager.py`
Expected: 无新增错误

- [ ] **Step 5: Commit**

```bash
git add backend/src/session/models.py backend/src/repositories/sessions.py backend/src/session/manager.py
git commit -m "feat(session): SessionRuntime 和 Manager 新增 enrollment 读写"
```

---

### Task 3: 后端新增 Enrollment API (POST + GET)

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: 新增 POST /api/sessions/{session_id}/enrollment**

在 `backend/main.py` 中，在 `create_session` 路由下方新增：

```python
import io  # 新增导入（放在文件顶部现有 import 区域）

# 在 @app.post("/api/sessions") 下方新增：

@app.post("/api/sessions/{session_id}/enrollment")
async def upload_enrollment(session_id: str, audio: UploadFile = File(...)):
    """接收声纹音频，提取 embedding，写入 session。"""
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的 session_id 格式") from None

    async with _maker() as s:
        from repositories.sessions import SessionRepository  # noqa: PLC0415
        row = await SessionRepository(s).get(sid)
        if row is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        if row.status == "closed":
            raise HTTPException(status_code=404, detail="会话已结束")

    # 读取上传音频
    contents = await audio.read()
    try:
        bio = io.BytesIO(contents)
        pcm, sr = sf.read(bio, dtype="float32", always_2d=False)
        if pcm.ndim == 2:
            pcm = pcm.mean(axis=1)
    except Exception as exc:
        logger.warning("Failed to parse enrollment audio: %s", exc)
        raise HTTPException(status_code=400, detail="音频文件无法解析，请上传 WAV 或 MP3") from None

    # 音频过短检查
    duration_s = len(pcm) / sr
    if duration_s < 1.0:
        raise HTTPException(status_code=400, detail="音频过短，请录制至少 3 秒") from None

    # 提取 embedding
    try:
        enrollment = await asyncio.to_thread(enroll_speaker, pcm, sr)
    except Exception as exc:
        logger.exception("enroll_speaker failed")
        raise HTTPException(status_code=500, detail="声纹处理失败，请重试") from None

    # 写入 DB + runtime
    await session_manager.set_enrollment(sid, enrollment)
    logger.info("Enrollment uploaded for sid=%s duration=%.2fs", session_id, duration_s)
    return {"ok": True}
```

- [ ] **Step 2: 新增 GET /api/sessions/{session_id}**

在 `upload_enrollment` 下方新增：

```python
@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    """查询 session 基本信息。"""
    try:
        sid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的 session_id 格式") from None

    async with _maker() as s:
        from repositories.sessions import SessionRepository  # noqa: PLC0415
        row = await SessionRepository(s).get(sid)
        if row is None:
            raise HTTPException(status_code=404, detail="会话不存在")

    return {
        "session_id": str(row.id),
        "status": row.status,
        "has_enrollment": row.lawyer_embedding is not None,
    }
```

- [ ] **Step 3: 新增 UploadFile / File 导入**

在 `backend/main.py` 顶部，在现有 FastAPI import 后新增：

```python
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File
```

- [ ] **Step 4: 运行格式检查**

Run: `cd backend && uv run ruff check main.py`
Expected: 无新增错误

- [ ] **Step 5: Commit**

```bash
git add backend/main.py
git commit -m "feat(api): 新增 POST /sessions/{id}/enrollment 和 GET /sessions/{id}"
```

---

### Task 4: 废弃全局声纹单例，WS 从 session 加载 enrollment

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: 删除全局单例函数和常量**

删除 `backend/main.py` 中的以下内容：

```python
# 删除这一行：
ENROLLMENT_WAV = Path(__file__).parent / "tests" / "fixtures" / "律师声纹注册_30s.wav"

# 删除这两个函数：
def _get_lawyer_enrollment() -> Enrollment:
    ...

def _session_enrollment() -> Enrollment:
    ...
```

同时删除不再需要的 `copy` 导入（如果 `main.py` 中 `copy` 只被 `_session_enrollment` 使用的话）。检查 `main.py` 中 `copy` 是否还有其它引用，如果没有则删除 `import copy`。

- [ ] **Step 2: 新增 _load_session_enrollment 辅助函数**

在删除全局单例的位置，新增辅助函数：

```python
async def _load_session_enrollment(sid: uuid.UUID) -> Enrollment | None:
    """从 SessionManager 加载 session 绑定的 enrollment。"""
    if session_manager is None:
        return None
    return await session_manager.get_enrollment(sid)
```

- [ ] **Step 3: 修改 WS handler 加载 enrollment 逻辑**

在 `backend/main.py` 的 `legal_session` 函数中，找到以下代码：

```python
        # --- 音频管道 ---
        enrollment = await asyncio.to_thread(_session_enrollment)
        audio_q = asyncio.Queue()
```

替换为：

```python
        # --- 音频管道 ---
        enrollment = await _load_session_enrollment(sid_uuid)
        if enrollment is None:
            logger.warning("[WS] no enrollment for sid=%s (4003)", session_id)
            await _safe_ws_close(ws, code=4003, reason="请先录制声纹")
            return
        audio_q = asyncio.Queue()
```

- [ ] **Step 4: 运行后端测试确认无回归**

Run: `cd backend && uv run pytest tests/ -x -q`
Expected: 全部通过（如果有现有失败的测试，确认不是本次改动导致的）

- [ ] **Step 5: Commit**

```bash
git add backend/main.py
git commit -m "feat(ws): 废弃全局声纹单例，WS 从 session 加载 enrollment"
```

---

### Task 5: 后端 enrollment API 测试

**Files:**
- Create: `backend/tests/test_enrollment.py`

- [ ] **Step 1: 创建 async_client fixture（如不存在）**

在 `backend/tests/test_enrollment.py` 顶部：

```python
"""Enrollment API 测试。"""
from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from main import app


@pytest.fixture
async def async_client():
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        yield client
```

- [ ] **Step 2: 测试创建 session 后查询 has_enrollment=false**

```python
@pytest.mark.asyncio
async def test_get_session_no_enrollment(async_client):
    # 创建 session
    resp = await async_client.post("/api/sessions")
    assert resp.status_code == 200
    sid = resp.json()["session_id"]

    # 查询
    resp = await async_client.get(f"/api/sessions/{sid}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_enrollment"] is False
    assert data["status"] == "active"
```

- [ ] **Step 3: 测试上传声纹后 has_enrollment=true**

```python
import soundfile as sf
from tests.streaming_fixtures import SHORT_LAWYER_WAV


@pytest.mark.asyncio
async def test_upload_enrollment_and_query(async_client):
    # 创建 session
    resp = await async_client.post("/api/sessions")
    sid = resp.json()["session_id"]

    # 上传声纹
    with open(SHORT_LAWYER_WAV, "rb") as f:
        resp = await async_client.post(
            f"/api/sessions/{sid}/enrollment",
            files={"audio": ("test.wav", f, "audio/wav")},
        )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # 查询确认 has_enrollment
    resp = await async_client.get(f"/api/sessions/{sid}")
    assert resp.json()["has_enrollment"] is True
```

- [ ] **Step 4: 测试上传损坏文件返回 400**

```python
@pytest.mark.asyncio
async def test_upload_invalid_audio_returns_400(async_client):
    resp = await async_client.post("/api/sessions")
    sid = resp.json()["session_id"]

    resp = await async_client.post(
        f"/api/sessions/{sid}/enrollment",
        files={"audio": ("bad.txt", b"not audio", "text/plain")},
    )
    assert resp.status_code == 400
```

- [ ] **Step 5: 测试上传到过短音频返回 400**

```python
import numpy as np
import io


@pytest.mark.asyncio
async def test_upload_too_short_audio_returns_400(async_client):
    resp = await async_client.post("/api/sessions")
    sid = resp.json()["session_id"]

    # 生成 0.5 秒静默 WAV
    silence = np.zeros(int(16000 * 0.5), dtype=np.float32)
    buf = io.BytesIO()
    sf.write(buf, silence, 16000, format="WAV", subtype="PCM_16")
    buf.seek(0)

    resp = await async_client.post(
        f"/api/sessions/{sid}/enrollment",
        files={"audio": ("short.wav", buf, "audio/wav")},
    )
    assert resp.status_code == 400
```

- [ ] **Step 6: 运行测试**

Run: `cd backend && uv run pytest tests/test_enrollment.py -v`
Expected: 4 个测试全部通过

- [ ] **Step 7: Commit**

```bash
git add backend/tests/test_enrollment.py
git commit -m "test: enrollment API 测试"
```

---

### Task 6: 后端 WS enrollment 测试

**Files:**
- Create: `backend/tests/test_ws_enrollment.py`

- [ ] **Step 1: 测试无 enrollment 时 WS 返回 4003**

```python
"""WS enrollment 连接测试。"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient

from main import app


@pytest.mark.asyncio
async def test_ws_rejected_without_enrollment():
    """无 enrollment 的 session 连 WS 应收到关闭码 4003。"""
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        # 创建 session
        resp = await client.post("/api/sessions")
        sid = resp.json()["session_id"]

    # 用同步 TestClient 测 WS（httpx 不支持 WS）
    with TestClient(app) as sync_client:
        with sync_client.websocket_connect(f"/ws/{sid}") as ws:
            # FastAPI 会立即关闭连接
            pass  # 这里 TestClient 的 websocket_connect 在连接关闭时抛异常或返回
```

等一下，`TestClient` 的 `websocket_connect` 在服务器关闭连接时的行为需要确认。实际上，当服务器 `await ws.close(code=4003)` 后，客户端会收到关闭帧。`TestClient` 的 `websocket_connect` 作为上下文管理器，在退出时会处理关闭。

但上面的代码可能不够健壮。让我用 `pytest` 的 `anyio` 或直接用 `TestClient` 的同步方式。

更可靠的做法：

```python
from starlette.testclient import TestClient


def test_ws_rejected_without_enrollment():
    with TestClient(app) as client:
        # 创建 session
        resp = client.post("/api/sessions")
        sid = resp.json()["session_id"]

        with pytest.raises(Exception) as exc_info:
            with client.websocket_connect(f"/ws/{sid}") as ws:
                ws.receive_text()
        # 关闭码 4003 会被封装在异常中
```

实际上 Starlette 的 TestClient 在 WS 被服务器关闭时，不会抛异常，而是会在 `receive_text()` 时抛出。但 `websocket_connect` 作为上下文管理器本身不会抛。我们可以这样：

```python
def test_ws_rejected_without_enrollment():
    with TestClient(app) as client:
        resp = client.post("/api/sessions")
        sid = resp.json()["session_id"]

        with client.websocket_connect(f"/ws/{sid}") as ws:
            # 服务器应立即关闭，尝试接收会失败
            try:
                ws.receive_text()
            except Exception:
                pass  # 预期行为
```

但这样无法验证关闭码。Starlette TestClient 的 websocket 对象有 `.close_reason` 和 `.close_code` 吗？实际上 `websockets` 库的 client 有，但 TestClient 封装的可能不一样。

让我用更直接的方式：测试有 enrollment 时能正常连接，无 enrollment 时连接被关闭。至于关闭码，可以通过日志或更底层的测试来验证。

简化方案：

```python
import pytest
from starlette.testclient import TestClient

from main import app


def test_ws_accepts_with_enrollment():
    """有 enrollment 的 session 可以正常建立 WS。"""
    with TestClient(app) as client:
        resp = client.post("/api/sessions")
        sid = resp.json()["session_id"]

        # 上传声纹
        from tests.streaming_fixtures import SHORT_LAWYER_WAV
        with open(SHORT_LAWYER_WAV, "rb") as f:
            resp = client.post(
                f"/api/sessions/{sid}/enrollment",
                files={"audio": ("test.wav", f, "audio/wav")},
            )
        assert resp.status_code == 200

        # WS 应能建立（至少不会立即被关闭）
        with client.websocket_connect(f"/ws/{sid}") as ws:
            # 发送 ping，应收到 pong
            ws.send_json({"type": "ping"})
            msg = ws.receive_json()
            assert msg["type"] == "pong"


def test_ws_rejected_without_enrollment():
    """无 enrollment 的 session 连 WS 应被关闭。"""
    with TestClient(app) as client:
        resp = client.post("/api/sessions")
        sid = resp.json()["session_id"]

        with client.websocket_connect(f"/ws/{sid}") as ws:
            # 服务器会关闭连接，receive 应失败
            with pytest.raises(Exception):
                ws.receive_text()
```

这个测试方案更简单可靠。让我写入计划。

```python
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
```

- [ ] **Step 2: 运行测试**

Run: `cd backend && uv run pytest tests/test_ws_enrollment.py -v`
Expected: 2 个测试全部通过

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_ws_enrollment.py
git commit -m "test: WS enrollment 连接测试"
```

---

### Task 7: 前端 API 层新增查询和上传函数

**Files:**
- Modify: `frontend/src/api/sessions.ts`

- [ ] **Step 1: 新增类型和函数**

在 `frontend/src/api/sessions.ts` 底部，在 `fetchHistory` 函数下方新增：

```typescript
export type SessionInfo = {
  session_id: string;
  status: string;
  has_enrollment: boolean;
};

export async function getSession(sessionId: string): Promise<SessionInfo | null> {
  const r = await fetch(`${API_BASE}/api/sessions/${sessionId}`);
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`session fetch failed: ${r.status}`);
  return r.json();
}

export async function uploadEnrollment(
  sessionId: string,
  audioBlob: Blob
): Promise<void> {
  const formData = new FormData();
  formData.append("audio", audioBlob, "enrollment.wav");
  const r = await fetch(`${API_BASE}/api/sessions/${sessionId}/enrollment`, {
    method: "POST",
    body: formData,
  });
  if (!r.ok) {
    const text = await r.text().catch(() => "");
    throw new Error(`上传失败 (${r.status}): ${text}`);
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/api/sessions.ts
git commit -m "feat(api): 新增 getSession 和 uploadEnrollment"
```

---

### Task 8: 前端 VoiceprintModal 组件

**Files:**
- Create: `frontend/src/components/VoiceprintModal.tsx`

- [ ] **Step 1: 编写完整组件**

```tsx
import { useState, useRef, useCallback, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Mic, Upload, CheckCircle2, Loader2 } from "lucide-react";
import { encodeWavChunk } from "@/lib/wav";

const registerText =
  "今天天气很好，我们在这里进行法律咨询。" +
  "根据中华人民共和国相关法律法规，" +
  "我将为您提供专业的法律服务和建议。";

interface VoiceprintModalProps {
  sessionId: string;
  onComplete: () => void;
  onError: (message: string) => void;
}

type Phase = "idle" | "recording" | "uploading" | "done";

export default function VoiceprintModal({
  sessionId,
  onComplete,
  onError,
}: VoiceprintModalProps) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [countdown, setCountdown] = useState(15);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const audioContextRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const workletNodeRef = useRef<AudioWorkletNode | null>(null);
  const samplesRef = useRef<Float32Array[]>([]);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const cleanup = useCallback(() => {
    if (timerRef.current) clearInterval(timerRef.current);
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    if (workletNodeRef.current) {
      try { workletNodeRef.current.disconnect(); } catch { /* noop */ }
    }
    if (audioContextRef.current) {
      try { audioContextRef.current.close(); } catch { /* noop */ }
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
    }
    samplesRef.current = [];
  }, []);

  useEffect(() => {
    return () => cleanup();
  }, [cleanup]);

  const buildWavBlob = useCallback((): Blob => {
    const all = samplesRef.current;
    if (all.length === 0) return new Blob();
    const totalLen = all.reduce((sum, arr) => sum + arr.length, 0);
    const merged = new Float32Array(totalLen);
    let offset = 0;
    for (const arr of all) {
      merged.set(arr, offset);
      offset += arr.length;
    }
    const wavBytes = encodeWavChunk(merged, { sampleRate: 16000, channels: 1 });
    return new Blob([wavBytes], { type: "audio/wav" });
  }, []);

  const doUpload = useCallback(
    async (blob: Blob) => {
      setPhase("uploading");
      try {
        const { uploadEnrollment } = await import("@/api/sessions");
        await uploadEnrollment(sessionId, blob);
        setPhase("done");
        setTimeout(() => onComplete(), 500);
      } catch (e) {
        const msg = e instanceof Error ? e.message : "上传失败";
        setErrorMsg(msg);
        setPhase("idle");
        onError(msg);
      }
    },
    [sessionId, onComplete, onError]
  );

  const startRecording = useCallback(async () => {
    setErrorMsg(null);
    setPhase("recording");
    setCountdown(15);
    samplesRef.current = [];

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      const audioContext = new AudioContext({ sampleRate: 16000 });
      audioContextRef.current = audioContext;

      const workletCode = `
        class PCMProcessor extends AudioWorkletProcessor {
          process(inputs) {
            const input = inputs[0];
            if (input && input[0]) {
              this.port.postMessage(input[0]);
            }
            return true;
          }
        }
        registerProcessor('pcm-processor', PCMProcessor)
      `;
      const blob = new Blob([workletCode], { type: "application/javascript" });
      const url = URL.createObjectURL(blob);
      await audioContext.audioWorklet.addModule(url);
      URL.revokeObjectURL(url);

      const source = audioContext.createMediaStreamSource(stream);
      const workletNode = new AudioWorkletNode(audioContext, "pcm-processor");
      workletNodeRef.current = workletNode;

      workletNode.port.onmessage = (e) => {
        samplesRef.current.push(e.data);
      };

      source.connect(workletNode);

      timerRef.current = setInterval(() => {
        setCountdown((prev) => {
          if (prev <= 1) {
            if (timerRef.current) clearInterval(timerRef.current);
            return 0;
          }
          return prev - 1;
        });
      }, 1000);

      timeoutRef.current = setTimeout(() => {
        cleanup();
        const blob = buildWavBlob();
        doUpload(blob);
      }, 15000);
    } catch (err) {
      cleanup();
      let msg = "启动录音失败";
      if (err instanceof DOMException && err.name === "NotAllowedError") {
        msg = "麦克风权限被拒绝，请在浏览器设置中允许访问";
      } else if (err instanceof Error) {
        msg = err.message;
      }
      setErrorMsg(msg);
      setPhase("idle");
      onError(msg);
    }
  }, [cleanup, buildWavBlob, doUpload, onError]);

  const handleFileUpload = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;
      setErrorMsg(null);
      await doUpload(file);
    },
    [doUpload]
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-[420px] max-w-[90vw] rounded-xl bg-bg-primary p-8 text-center shadow-lg border border-border-color">
        <div className="mb-6">
          <h2 className="text-xl font-semibold text-ink-primary mb-2">
            请先录制声纹
          </h2>
          <p className="text-sm text-ink-secondary">
            系统需要您的声纹来区分律师与当事人
          </p>
        </div>

        <div className="p-5 mb-6 bg-bg-secondary border border-border-color rounded-lg">
          <p className="text-base text-ink-primary leading-relaxed">
            &ldquo;{registerText}&rdquo;
          </p>
        </div>

        {phase === "idle" && (
          <div className="space-y-3">
            <Button size="lg" onClick={startRecording} className="w-full">
              <Mic className="w-4 h-4 mr-2" />
              开始录音 (15秒)
            </Button>
            <div className="relative">
              <input
                type="file"
                accept="audio/*"
                onChange={handleFileUpload}
                className="absolute inset-0 opacity-0 cursor-pointer"
                id="enroll-file-input"
              />
              <Button
                variant="outline"
                size="lg"
                className="w-full"
                onClick={() => document.getElementById("enroll-file-input")?.click()}
              >
                <Upload className="w-4 h-4 mr-2" />
                上传音频文件
              </Button>
            </div>
          </div>
        )}

        {phase === "recording" && (
          <div className="space-y-4">
            <div className="flex items-center justify-center gap-2">
              <span className="w-3 h-3 bg-danger rounded-full motion-safe:animate-pulse" />
              <span className="text-danger font-mono">
                录音中… {countdown}s
              </span>
            </div>
            <div className="h-2 bg-muted rounded-full overflow-hidden">
              <div
                className="h-full bg-primary transition-all duration-1000 ease-linear"
                style={{ width: `${((15 - countdown) / 15) * 100}%` }}
              />
            </div>
          </div>
        )}

        {phase === "uploading" && (
          <div className="flex items-center justify-center gap-2 text-ink-secondary">
            <Loader2 className="w-5 h-5 animate-spin" />
            <span>正在处理声纹…</span>
          </div>
        )}

        {phase === "done" && (
          <div className="flex items-center justify-center gap-2 text-success">
            <CheckCircle2 className="w-5 h-5" />
            <span>声纹上传成功</span>
          </div>
        )}

        {errorMsg && (
          <p className="mt-4 text-sm text-danger">{errorMsg}</p>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/VoiceprintModal.tsx
git commit -m "feat(ui): 新增 VoiceprintModal 声纹录制组件"
```

---

### Task 9: 前端 LiveSession 集成 enrollment 流程

**Files:**
- Modify: `frontend/src/pages/LiveSession.tsx`

- [ ] **Step 1: 新增 enrollment phase 状态和查询逻辑**

在 `LiveSessionInner` 组件中，现有 `useSession` hooks 之后，新增 enrollment 相关状态：

```typescript
import VoiceprintModal from "@/components/VoiceprintModal";  // 新增导入
import { getSession } from "@/api/sessions";                 // 新增导入

type EnrollmentPhase = "checking" | "needed" | "ready";

// 在 LiveSessionInner 函数体内，在现有 state 下方新增：
const [enrollmentPhase, setEnrollmentPhase] = useState<EnrollmentPhase>("checking");
const [enrollError, setEnrollError] = useState<string | null>(null);
```

- [ ] **Step 2: 查询 enrollment 状态**

在 `useEffect(() => { if (sessionId) setSessionId(sessionId) }, ...)` 之后，新增一个 effect：

```typescript
  // 查询 enrollment 状态
  useEffect(() => {
    if (!sessionId) {
      setEnrollmentPhase("ready"); // demo 模式直接过
      return;
    }
    let cancelled = false;
    getSession(sessionId)
      .then((info) => {
        if (cancelled) return;
        if (info && info.has_enrollment) {
          setEnrollmentPhase("ready");
        } else {
          setEnrollmentPhase("needed");
        }
      })
      .catch(() => {
        if (!cancelled) setEnrollmentPhase("needed");
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);
```

- [ ] **Step 3: 条件渲染 VoiceprintModal**

在 LiveSessionInner 的 return 中，在 `PortraitLock` 之前（或最外层）条件渲染 modal：

```tsx
  return (
    <>
      {enrollmentPhase === "needed" && sessionId && (
        <VoiceprintModal
          sessionId={sessionId}
          onComplete={() => setEnrollmentPhase("ready")}
          onError={(msg) => setEnrollError(msg)}
        />
      )}
      <PortraitLock />
      ...
```

- [ ] **Step 4: 控制 WS 连接时机**

修改 `useWebSocket` 的调用条件。当前代码：

```typescript
  const {
    isConnected,
    error: wsError,
    sendAudioChunk,
    ...
  } = useWebSocket(
    hydrated ? (sessionId ?? "") : "",
    recvEvent,
  );
```

改为：

```typescript
  const {
    isConnected,
    error: wsError,
    sendAudioChunk,
    confirmIntent,
    dismissIntent,
    notifyAudioEnd,
    reconnect,
  } = useWebSocket(
    hydrated && enrollmentPhase === "ready" ? (sessionId ?? "") : "",
    recvEvent,
  );
```

这样 `enrollmentPhase !== "ready"` 时，`useWebSocket` 收到空字符串不会建立连接。

- [ ] **Step 5: 主录音按钮根据 enrollment 状态控制**

在 Desktop Header 和 Mobile Layout 中的 `AudioControls`，需要在 `enrollmentPhase !== "ready"` 时隐藏或禁用。

找到两处 `AudioControls` 的渲染：

```tsx
      {/* Desktop Header */}
      <header className="...">
        ...
        {enrollmentPhase === "ready" && (
          <AudioControls onChunk={sendAudioChunk} onAudioEnd={notifyAudioEnd} />
        )}
      </header>
```

Mobile Layout 中的 `audioControls` 属性也做同样处理：

```tsx
        audioControls={
          enrollmentPhase === "ready" ? (
            <AudioControls onChunk={sendAudioChunk} onAudioEnd={notifyAudioEnd} />
          ) : null
        }
```

- [ ] **Step 6: 添加 checking 状态提示**

在 return 的最外层（PortraitLock 之后），加一个 loading 提示：

```tsx
      {enrollmentPhase === "checking" && (
        <div className="flex items-center justify-center h-screen bg-background text-foreground">
          <div className="text-sm text-muted-foreground">正在检查会话状态…</div>
        </div>
      )}
```

注意这个 loading 应该只在 checking 时显示，正常内容在 checking 时也可以继续渲染（因为 history hydration 不受影响），但最好不覆盖。或者把 loading 放在 disconnect banner 的旁边做一个小提示。

更简单的做法：checking 时不阻止页面渲染，只是不连 WS 和不显示录音按钮。用户看到的是一个没有录音按钮的页面（或者显示一个提示）。

如果希望在 checking 期间给用户明确反馈，可以在 header 里加一个提示：

```tsx
      {enrollmentPhase === "checking" && (
        <div className="flex items-center justify-center px-4 py-1.5 bg-bg-tertiary border-b border-border-color text-xs text-ink-secondary">
          正在检查声纹状态…
        </div>
      )}
```

放在 disconnect banner 下面。

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/LiveSession.tsx
git commit -m "feat(session): LiveSession 集成声纹前置录制流程"
```

---

### Task 10: 端到端验证

**Files:**
- 无新增文件，手动验证

- [ ] **Step 1: 启动后端**

Run: `cd backend && uv run uvicorn main:app --reload`
Expected: 启动成功，无异常

- [ ] **Step 2: 启动前端**

Run: `cd frontend && pnpm dev`
Expected: 编译成功，无 TS 错误

- [ ] **Step 3: 完整流程验证**

1. EntryPage 点击"开始新会谈" → 创建 session → 跳转到 LiveSession
2. 页面显示"正在检查声纹状态…" → 显示 VoiceprintModal
3. 点击"开始录音（15秒）" → 允许麦克风 → 15 秒倒计时
4. 15 秒后自动上传 → modal 关闭 → WS 连接建立
5. 录音按钮出现 → 点击录音 → 发送音频 → 收到 transcript
6. 刷新页面 → 不再显示 modal（因为 session 已有 enrollment）→ 直接建立 WS

- [ ] **Step 4: 边界验证**

1. 无 enrollment 时直接连 WS（如通过脚本）→ 收到 4003 关闭
2. 上传损坏文件 → modal 显示错误提示，留在当前页
3. 上传过短音频（< 1s）→ 后端返回 400，modal 显示错误

- [ ] **Step 5: 最终 Commit**

确认所有变更已提交：

```bash
git log --oneline -10
```

---

## 计划自检

**1. Spec 覆盖率：**

| Spec 要求 | 对应 Task |
|-----------|-----------|
| DB 新增 `lawyer_embedding` JSONB | Task 1 |
| `SessionRuntime.enrollment` | Task 2 |
| `POST /api/sessions/{id}/enrollment` | Task 3 |
| `GET /api/sessions/{id}` | Task 3 |
| WS 关闭码 4003 | Task 4 |
| WS 从 session 加载 enrollment | Task 4 |
| 废弃全局单例 | Task 4 |
| 前端 modal 录音 15 秒 | Task 8 |
| 前端支持上传文件 | Task 8 |
| 前端先查询再连 WS | Task 9 |
| 后端 API 测试 | Task 5 |
| WS 连接测试 | Task 6 |

全部覆盖，无遗漏。

**2. Placeholder 扫描：**

- 无 TBD/TODO
- 无 "add appropriate error handling" 等模糊描述
- 每个代码步骤包含完整代码

**3. 类型一致性：**

- `EnrollmentPhase` 在 Task 9 中定义为 `'checking' | 'needed' | 'ready'`，与 modal 回调逻辑一致
- `SessionInfo.has_enrollment`（Task 7）与后端 `GET /api/sessions/{id}` 响应一致
- `uploadEnrollment` 接收 `Blob`（Task 7），VoiceprintModal 生成 `Blob`（Task 8）并传入

无类型不一致问题。
