# 前端音频输入增强设计 — 实时会谈页面

**日期**: 2026-05-29
**范围**: 前端 `LiveSession` 页面
**目标**: 为实时会谈页面添加麦克风实时录音和音频文件上传两种音频输入方式，两者复用同一套 WebSocket chunk 传输逻辑。

---

## 1. 背景与现状

当前 `LiveSession` 页面已具备：
- 左侧转写面板：通过 WebSocket 接收 `transcript` 消息，展示律师/客户对话
- 右侧 AI 分析面板：接收 `analysis` 和 `suggestion` 消息，展示 Agent 反馈
- WebSocket Hook：`useWebSocket` 已暴露 `sendAudioChunk(chunk: Uint8Array)` 接口
- 录音按钮：UI 上有一个「🎤 开始录音」按钮，但点击后仅切换状态，**无实际音频录制逻辑**

**缺失能力**：
1. 麦克风无法真正录制并发送音频
2. 不支持上传音频文件模拟会谈流程
3. 上传音频时无法在浏览器同步播放

---

## 2. 设计决策

### 2.1 核心方案：单 Hook 统一封装

新建 `useAudioInput` Hook，内部封装麦克风录音和文件上传两条链路，对外暴露统一接口。两种输入方式最终都输出标准 WAV (PCM) chunks，通过同一 `onChunk` 回调送入 WebSocket。

**理由**：
- LiveSession 对音频输入应视为黑盒，不关心内部是麦克风还是文件
- 互斥逻辑内置，避免外层手动协调导致的竞态
- 符合项目现有 Hooks 优先的代码风格
- 取消音频功能时，只需删除 `AudioControls` 一行引用

### 2.2 互斥策略

麦克风录音和文件上传**完全互斥**。`useAudioInput` 内部维护单一 `mode` 状态（`'idle' | 'mic' | 'file'`），非 `idle` 状态下调用 `startRecording` 或 `startFile` 直接抛出错误。

### 2.3 音频格式

两种模式统一输出 **WAV (PCM)** 格式 chunks：
- **麦克风模式**：通过 `AudioWorklet` 采集原始 PCM，按 300ms 窗口封装 WAV header
- **文件模式**：`AudioContext.decodeAudioData` 解码后，按同样 300ms 切片封装 WAV

统一理由：后端 FunASR 对 WAV/PCM 支持最稳定；`MediaRecorder` 各浏览器输出格式不一致（Chrome=webm/opus, Safari=mp4/aac），不可控。

### 2.4 文件同步播放

文件上传模式下，解码后的 `AudioBuffer` 通过 `AudioBufferSourceNode` 同步本地播放，同时按固定间隔切片发送给后端。律师可边听边看转写和 Agent 反馈，体验与真实会谈一致。

进度计算：已发送采样数 / 总采样数 × 100%，而非依赖 `audio.currentTime`，确保进度反映的是「已向后端发送的数据量」。

---

## 3. 组件架构

```
LiveSession.tsx
├── Header
│   ├── Title + ConnectionStatus
│   └── AudioControls.tsx  ──→  useAudioInput.ts
│       ├── 🎤 开始录音按钮
│       ├── 📁 上传音频按钮
│       ├── ⏹ 停止按钮
│       └── 📊 播放进度条（file 模式时显示）
├── Left: TranscriptPanel（现有，转写对话）
└── Right: AnalysisSidebar（现有，Agent 反馈）
```

**新增文件**：
| 文件 | 职责 |
|------|------|
| `frontend/src/hooks/useAudioInput.ts` | 统一封装麦克风录音 + 文件解码/切片/播放 |
| `frontend/src/components/AudioControls.tsx` | 音频控制面板：按钮组 + 进度条 + 错误提示 |

**修改文件**：
| 文件 | 改动 |
|------|------|
| `frontend/src/pages/LiveSession.tsx` | Header 区域引入 `AudioControls`，删除现有空壳录音状态 |

---

## 4. `useAudioInput` Hook 设计

### 4.1 对外接口

```typescript
type AudioMode = 'idle' | 'mic' | 'file'

interface UseAudioInputOptions {
  onChunk: (chunk: Uint8Array) => void  // 直接复用 useWebSocket 的 sendAudioChunk
  chunkIntervalMs?: number               // 默认 300ms
}

// WAV 参数常量（与后端 FunASR 对齐）
const WAV_SAMPLE_RATE = 16000  // 16kHz，paraformer-zh 推荐采样率
const WAV_CHANNELS = 1         // 单声道
const WAV_BITS_PER_SAMPLE = 16 // 16-bit PCM

interface UseAudioInputReturn {
  mode: AudioMode
  isActive: boolean        // mode !== 'idle'
  progress: number | null  // 0-100，仅 file 模式有效
  error: string | null
  startRecording: () => Promise<void>
  startFile: (file: File) => Promise<void>
  stop: () => void
}

export function useAudioInput(options: UseAudioInputOptions): UseAudioInputReturn
```

### 4.2 内部状态机

```
idle ──startRecording()──→ mic ──stop()──→ idle
idle ──startFile(file)───→ file ──stop()──→ idle
```

`idle` 是唯一入口，`mic` 和 `file` 互斥，`stop()` 在任何状态下都安全回到 `idle`。

### 4.3 麦克风模式实现

1. 调用 `navigator.mediaDevices.getUserMedia({ audio: true })` 获取音频流
2. 创建 `AudioContext({ sampleRate: 16000 })`，通过 `audioContext.audioWorklet.addModule(blobURL)` 加载内联 AudioWorklet（worklet 代码以 inline blob URL 注入，避免额外文件）
3. `AudioWorkletNode` 每 128 采样帧输出一次 `Float32Array`，主线程积累到 `16000 * 0.3 = 4800` 采样点（约 300ms）后，转换为 16-bit PCM，封装 WAV header，经 `onChunk` 发出
4. `stop()` 时：关闭 AudioContext，释放 MediaStream tracks

### 4.4 文件模式实现

1. `FileReader.readAsArrayBuffer(file)` 读取文件
2. `AudioContext.decodeAudioData(arrayBuffer)` 解码为 `AudioBuffer`
3. 创建 `AudioBufferSourceNode` 开始本地同步播放
4. 启动定时器，按 `chunkIntervalMs` 从 `AudioBuffer` 中切出对应长度的 `Float32Array`，封装 WAV header，经 `onChunk` 发出
5. 发送完毕后或调用 `stop()` 时：停止 `AudioBufferSourceNode`，清理定时器，关闭 AudioContext

### 4.5 互斥与错误处理

- **重复启动**：`mode !== 'idle'` 时调用 `startRecording` 或 `startFile`，抛出 `Error('Audio input already active')`
- **麦克风权限被拒**：`error = '麦克风权限被拒绝，请在浏览器设置中允许访问'`
- **文件解码失败**：`error = '无法解析该音频文件，请尝试 MP3 或 WAV 格式'`
- **文件过大**：解码前检查 `file.size > 100MB`（防止浏览器内存溢出，`AudioContext.decodeAudioData` 会一次性将文件载入内存），直接报错 `'文件过大，请上传 100MB 以内的音频'`
- `stop()` 幂等：调用多次不报错，确保资源释放干净

---

## 5. `AudioControls` 组件设计

### 5.1 布局

位于 `LiveSession` Header 右侧。

**`idle` 状态**：
```
[🎤 开始录音] [📁 上传音频]
```

**`mic` 状态**：
```
[⏹ 停止]  🔴 录音中...
```

**`file` 状态**：
```
[⏹ 停止]  ▶️ 播放中...  [████████░░░░░░░░░░░░]  40%
```

### 5.2 交互细节

- **录音按钮**：点击调用 `startRecording()`。权限弹窗被拒时，`error` 由 `useAudioInput` 抛出，`AudioControls` 以红色小字展示在按钮下方，3 秒后自动清空
- **上传按钮**：使用隐藏 `<input type="file" accept="audio/*">`，点击按钮触发文件选择。选完文件后立即调用 `startFile(file)`
- **停止按钮**：点击调用 `stop()`，音频立刻停止（包括本地播放和向后端发送），回到 `idle`
- **模式切换**：非 `idle` 状态下，🎤 和 📁 按钮完全隐藏，只显示 ⏹ 停止按钮，避免禁用态的歧义

---

## 6. LiveSession 集成

### 6.1 Header 改造

替换现有的空壳录音按钮：

```tsx
<header className="flex items-center justify-between px-6 py-4 border-b border-zinc-800">
  <div>
    <h1 className="font-serif text-xl tracking-wide text-amber-200/90">实时会谈</h1>
    <p className="text-xs text-zinc-500 mt-0.5 font-mono">
      {isConnected ? '🟢 已连接' : '🟡 连接中...'} · {status}
    </p>
  </div>
  <AudioControls onChunk={sendAudioChunk} />
</header>
```

### 6.2 生命周期

- `AudioControls` 内部维护所有音频资源（`MediaStream`、`AudioContext`、定时器）
- `stop()` 时自动释放所有资源
- LiveSession 页面卸载时，`useAudioInput` 的 `useEffect` cleanup 自动调用 `stop()`
- 现有 `isRecording` 空壳状态可删除，`status` 保留（由 transcript 回调更新）

### 6.3 数据流

```
[🎤 麦克风] ──useAudioInput──→ sendAudioChunk ──→ WebSocket ──→ 后端 STT
[📁 文件] ────useAudioInput──→ sendAudioChunk ──→ WebSocket ──→ 后端 STT
                                                          ↓
                              transcript / analysis / suggestion
                                                          ↓
                                                   LiveSession state
                                                          ↓
                                                      UI 渲染
```

---

## 7. 边界情况与错误处理

| 场景 | 行为 | 用户可见 |
|------|------|---------|
| 麦克风权限被拒 | `startRecording()` reject，`error` 有值 | 红色提示，3 秒后消失 |
| 文件格式不支持 | `decodeAudioData` throw，`error` 有值 | 同上 |
| 文件超过 100MB | 解码前直接拦截，`error` 有值 | 同上 |
| WebSocket 断开时正在活跃 | `useAudioInput` 不感知 WS 状态，继续发送。WS 重连后后端自动恢复接收 | 由 WS 连接状态指示器展示 |
| 切换浏览器标签页 | 不暂停，保持录音/播放继续 | 无 |
| 上传中点击停止 | 立即停止播放和切片，未发送的 chunks 丢弃 | 进度归零，回到 idle |
| 组件卸载时正在活跃 | `useEffect` cleanup 自动 `stop()`，释放资源 | 无 |

**无暂停/继续功能**：真实会谈没有暂停场景，停止即结束，再开即新会话。UI 最简单。

---

## 8. 测试策略

### 8.1 `useAudioInput` Hook 测试（`useAudioInput.test.ts`）

使用 `vitest` + `@testing-library/react`，大量 mock 浏览器 API：

1. **模式切换**：`idle → mic → idle`，断言 `mode` / `isActive` 变化正确
2. **互斥保护**：`mic` 状态下调用 `startFile` 应 throw error
3. **麦克风 chunk 产出**：mock `AudioWorklet` / `getUserMedia`，断言 `onChunk` 被预期次数调用，参数为 `Uint8Array`
4. **文件模式 chunk 产出**：mock `AudioContext.decodeAudioData`，断言 `onChunk` 产出正确数量 chunks，进度 0 → 100
5. **错误态**：mock `getUserMedia` reject，断言 `error` 有值且可被读取

### 8.2 `AudioControls` 组件测试（`AudioControls.test.tsx`）

1. **idle 态**：渲染出 🎤 和 📁 两个按钮
2. **点击录音**：mock `useAudioInput`，断言 `startRecording` 被调用
3. **文件上传**：触发 `<input type="file">` change，断言 `startFile` 被调用
4. **mic 态**：渲染出 ⏹ 按钮，🎤/📁 不可见
5. **file 态**：渲染出进度条，数值正确
6. **错误展示**：传入 `error`，断言红色提示文字可见

### 8.3 不测试范围

- 真实麦克风硬件录制（需要权限，CI 不可行）
- 真实音频文件解码（mock 替代）
- WebSocket 连通性（已有 `useWebSocket.test.ts` 覆盖）

---

## 9. 待确认 / 风险

1. **后端 FunASR 的输入格式**：当前假设后端支持标准 WAV (PCM)。如后端仅支持特定采样率（如 16kHz），前端需在封装 WAV 时做重采样。
2. **音频文件格式支持**：`AudioContext.decodeAudioData` 原生支持 MP3、WAV、OGG、AAC（浏览器差异）。如遇不支持的格式，降级提示用户转换。
3. **AudioWorklet 兼容性**：Chrome 66+、Firefox 76+、Safari 15+ 已支持。企业内部环境如使用旧版浏览器，需降级为 `ScriptProcessorNode`（已废弃但兼容）。
