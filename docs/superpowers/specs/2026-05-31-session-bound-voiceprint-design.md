# 声纹与会话绑定设计 — Session-Bound Voiceprint

## 背景

当前律师声纹通过进程级单例 `_get_lawyer_enrollment()` 从固定文件 `tests/fixtures/律师声纹注册_30s.wav` 加载，所有 session 共享同一份 embedding。这导致：

- 声纹与场景（session）解耦，无法支持多律师、多设备场景
- 声纹注册是独立页面 `/register`，与实际会谈流程脱节
- 双声纹自举的 `client_embedding` 靠 `copy.deepcopy` 隔离，是临时方案

本设计将声纹 embedding 数据与 session 本身绑定，把录制声纹作为进入实时会谈的前置步骤。

---

## 目标

1. 每个 session 拥有独立的律师声纹 embedding
2. 进入 LiveSession 后必须先录制/上传声纹，才能开始实时录音
3. 声纹数据持久化到数据库，支持 session 恢复和断线重连
4. 废弃全局固定文件单例

---

## 非目标

- 多律师账号体系（`lawyer_id` 仍用默认值 `"lawyer-default"`）
- client_embedding 持久化（仍为运行时自举，不存 DB）
- 声纹质量评分或自动重录提示

---

## 方案概述

**方案二：先上传声纹，再建立 WebSocket**

进入 LiveSession 后，前端先查询 session 是否已有声纹。没有则显示 modal（参考 VoiceprintRegister 的 15 秒录音 + 进度条，同时支持上传音频文件），录完后通过 HTTP 上传音频。后端提取 embedding 存入数据库。上传成功后，前端建立 WS 连接，后端从 session 加载声纹启动 STT 管道。

---

## 数据模型

### 数据库变更

在 `backend/src/db/models.py` 的 `Session` 表新增 `lawyer_embedding` 字段：

```python
from sqlalchemy.dialects.postgresql import JSONB

class Session(Base):
    __tablename__ = "sessions"
    ...
    lawyer_embedding: Mapped[list | None] = mapped_column(JSONB, nullable=True)
```

- 只存 embedding 向量（`list[float]`，192 维），不存 `tau_high`/`tau_low`/`client_embedding`
- 加载时构造 `Enrollment(embedding=np.array(...))`，其余字段用默认值
- 使用 JSONB 而非 BYTEA，便于人工查看和调试

### SessionRuntime 扩展

`backend/src/session/manager.py` 的 `SessionRuntime` 新增 `enrollment` 字段：

```python
@dataclass
class SessionRuntime:
    session_id: uuid.UUID
    status: str
    ctx: ContextStore | None = None
    orchestrator: Orchestrator | None = None
    enrollment: Enrollment | None = None   # 新增
```

**加载顺序：** WS handler 先从 `runtime.enrollment` 读（热数据），没有再查 DB 反序列化并缓存回 runtime。

### 废弃代码

- 删除 `main.py` 中的 `_get_lawyer_enrollment()` 和 `_session_enrollment()`
- 删除 `ENROLLMENT_WAV` 常量
- `copy.deepcopy` 的 import 若不再有其他用途一并删除

---

## 后端 API

### `POST /api/sessions/{session_id}/enrollment`

上传声纹音频，提取 embedding，写入 session。

**请求：** `multipart/form-data`，字段名 `audio`，支持 WAV / MP3 等 `soundfile` 能解析的格式。

**流程：**
1. 校验 `session_id` 格式，查询 session 存在且 `status != "closed"`
2. 用 `soundfile.read()` 读取上传音频 → `np.ndarray`
3. 若音频时长 < 1 秒，返回 `400`（过短 embedding 质量不可靠）
4. 调用 `enroll_speaker(audio, sr)` 提取 cam++ embedding
5. 将 `embedding.tolist()` 写入 DB `sessions.lawyer_embedding`
6. 若 `SessionRuntime` 已加载，同步更新 `runtime.enrollment`
7. 返回 `200 OK` + `{"ok": true}`

**错误码：**
- `404`：session 不存在或已关闭
- `400`：音频文件无法解析，或音频过短（< 1s）
- `500`：embedding 提取异常

**覆盖策略：** 同一 session 重复上传，后写入的覆盖前者。

### `GET /api/sessions/{session_id}`

查询 session 基本信息，供前端判断是否需要录制声纹。

**响应：**
```json
{
  "session_id": "...",
  "status": "active",
  "has_enrollment": true
}
```

- `has_enrollment`：根据 `lawyer_embedding IS NOT NULL` 判定
- `404`：session 不存在

---

## WebSocket 变更

### `/ws/{session_id}` handler

当前在 `try` 块内直接调用 `_session_enrollment()`（从固定文件 deep copy）。改为**从 session 本身加载**：

```python
enrollment = await _load_session_enrollment(sid_uuid)
if enrollment is None:
    await _safe_ws_close(ws, code=4003, reason="请先录制声纹")
    return
```

`_load_session_enrollment` 逻辑：
1. 优先读 `runtime.enrollment`（热数据）
2. 没有则查 DB `lawyer_embedding` 字段，反序列化后缓存回 runtime
3. 仍没有 → 返回 `None`

### WS 关闭码

| 码 | 含义 | 已有/新增 |
|---|---|---|
| `4001` | 会话已结束 | 已有 |
| `4002` | 会话不存在 | 已有 |
| `4003` | 尚未录制声纹 | **新增** |

 enrollment 加载成功后，STT 管道、speaker 分离、Orchestrator 链路完全不变。

---

## 前端流程

### LiveSession 加载流程

```
进入 LiveSession
  │
  ▼
设置 sessionId
  │
  ▼
Hydrate history（历史记录加载不受影响）
  │
  ▼
查询 GET /api/sessions/{session_id}
  │
  ├── has_enrollment = true ──→ 建立 WS，正常跑
  │
  └── has_enrollment = false ──→ 显示声纹录制 modal
                                  │
                                  ▼
                         用户录音 15 秒 或 选择文件上传
                                  │
                                  ▼
                         POST /api/sessions/{id}/enrollment
                                  │
                                  ▼
                         上传成功 ──→ 关闭 modal，建立 WS
                         上传失败 ──→ 显示错误，留在 modal
```

**关键规则：** modal 显示期间，主录音按钮隐藏，WS 不连接。

### 声纹录制 Modal

以覆盖层形式嵌入在 `LiveSession` 内，**阻断交互**（点击外部无法关闭）。

**布局（参考 VoiceprintRegister）：**

- 标题："请先录制声纹"
- 说明："系统需要您的声纹来区分律师与当事人"
- 朗读文本卡片（沿用原法律文本）
- 方式一："开始录音（15秒）"按钮 → 15 秒倒计时 + 进度条
- 方式二："上传音频文件"按钮 → 选择本地音频文件
- 底部状态：上传中 / 成功 / 错误提示

**录音实现：**

复用 `useAudioInput.startRecording()` 启动麦克风，在 `onChunk` 回调中累积 `Uint8Array` 到数组。15 秒后 `stop()`，合并所有 chunk 的 PCM 数据为 `Float32Array`，调用 `encodeWavChunk()` 生成 WAV `Blob`，通过 `FormData` POST 上传。

**文件上传：**

选择文件后直接通过 `FormData` POST，后端负责解码和 embedding 提取。

### 状态管理

enrollment 状态为页面加载流程的**本地状态**，不放进全局 `SessionContext`（与断线重连无关）。

```typescript
type EnrollmentPhase = 'checking' | 'needed' | 'uploading' | 'ready';
```

- `checking`：正在查询 session 状态，页面显示 loading
- `needed`：需要录制声纹，显示 modal
- `uploading`：正在上传音频
- `ready`：声纹已就绪，建立 WS 连接

`enrollmentPhase !== 'ready'` 时，主录音按钮禁用/隐藏，`useWebSocket` 不初始化。

---

## 错误处理

### 后端

| 场景 | 行为 | 前端感知 |
|------|------|----------|
| 上传音频格式不支持 | `soundfile.read()` 抛异常 → `400` | 提示"音频格式不支持" |
| 上传音频过短（< 1s） | 拒绝 → `400` | 提示"音频过短，请录制至少 3 秒" |
| 提取 embedding 失败 | 模型异常 → `500` | 提示"声纹处理失败，请重试" |
| session 已关闭时上传 | `404` | 提示"会话已结束" |
| WS 连接时 enrollment 缺失 | 关闭码 `4003` | 显示声纹 modal（兜底） |
| WS 连接时 session 不存在 | 关闭码 `4002` | 保持不变 |
| WS 连接时 session 已关闭 | 关闭码 `4001` | 保持不变 |

**兜底：** 即使前端查询接口说 `has_enrollment=true`，WS 连接时后端仍要再校验一次 enrollment 和 session 状态（防竞态）。

### 前端

| 场景 | 行为 |
|------|------|
| 麦克风权限被拒绝 | 提示"请在浏览器设置中允许麦克风访问" |
| 录音过程中页面刷新 | 录音丢失，重新查询状态，回到 modal |
| 上传网络失败 | 提示"网络错误，请重试" |
| 上传成功但 WS 连接失败 | 关闭 modal，由现有断线 banner + 重连逻辑处理 |

---

## 测试策略

### 后端

1. **Enrollment API**
   - 正常上传 WAV → 200，DB `lawyer_embedding` 非空
   - 上传损坏文件 → 400
   - 上传 MP3 → 200
   - session 不存在/已关闭 → 404
   - 重复上传 → 后者覆盖前者

2. **WS 连接**
   - 有 enrollment → WS 正常建立，STT 启动
   - 无 enrollment → WS 关闭码 `4003`

3. **Speaker 分离回归**
   - 从 DB 加载 enrollment 的 session，speaker 分离结果与之前固定文件加载一致

### 前端

1. **Modal 状态流转**
   - `checking` → 无 enrollment → `needed` → modal 显示
   - `needed` → 上传成功 → `ready` → modal 关闭，WS 建立
   - `needed` → 上传失败 → 停留 `needed`，显示错误

2. **录音逻辑**
   - 复用 `useAudioInput` 录制 15 秒，生成 WAV Blob
   - 验证 Blob type 为 `audio/wav`，大小合理

### e2e

1. **完整流程：** 创建 session → 进入 LiveSession → modal 出现 → 录音上传 → modal 关闭 → WS 连接 → 收发音频 → 收到 transcript
2. **绕过校验：** 直接对无 enrollment 的 session 连 WS → 收到 `4003`

---

## 兼容性

- `VoiceprintRegister` 页面（`/register`）暂时保留，但入口从 EntryPage 移除（或标记为废弃）
- 现有已创建的 session（无 `lawyer_embedding`）在恢复时会被要求重新录制声纹
- 前后端事件类型（`events.ts`）本次不变更，无需同步
