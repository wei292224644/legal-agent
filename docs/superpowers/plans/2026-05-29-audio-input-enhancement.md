# 前端音频输入增强实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `LiveSession` 页面添加麦克风实时录音和音频文件上传功能，两者统一输出 WAV chunks 并通过 WebSocket 发送。

**Architecture:** 单 Hook (`useAudioInput`) 封装两种输入模式（`mic` / `file`），输出标准 16kHz 单声道 16-bit WAV chunks；`AudioControls` 组件负责 UI 展示；`LiveSession` 集成并替换现有空壳录音按钮。

**Tech Stack:** React 19, TypeScript, Web Audio API (AudioWorklet, AudioContext), Tailwind CSS, shadcn/ui, Vitest, Testing Library

---

## 文件结构

| 文件 | 操作 | 职责 |
|------|------|------|
| `frontend/src/lib/wav.ts` | 新建 | WAV header 封装 + Float32Array → Int16Array 转换工具 |
| `frontend/src/lib/wav.test.ts` | 新建 | WAV 工具函数单元测试 |
| `frontend/src/hooks/useAudioInput.ts` | 新建 | 核心 Hook：麦克风录音 + 文件解码/切片/播放 |
| `frontend/src/hooks/useAudioInput.test.ts` | 新建 | Hook 单元测试（大量 mock 浏览器 API） |
| `frontend/src/components/AudioControls.tsx` | 新建 | 音频控制面板 UI |
| `frontend/src/components/AudioControls.test.tsx` | 新建 | 组件交互测试 |
| `frontend/src/pages/LiveSession.tsx` | 修改 | Header 集成 `AudioControls`，删除空壳 `isRecording` |

---

## Task 1: WAV 编码工具函数

**Files:**
- Create: `frontend/src/lib/wav.ts`
- Test: `frontend/src/lib/wav.test.ts`

- [ ] **Step 1: 写失败测试**

```typescript
// frontend/src/lib/wav.test.ts
import { describe, it, expect } from 'vitest'
import { encodeWavChunk } from './wav'

describe('encodeWavChunk', () => {
  it('encodes Float32Array mono to WAV with correct header', () => {
    const samples = new Float32Array([0, 0.5, -0.5, 1, -1])
    const chunk = encodeWavChunk(samples, { sampleRate: 16000, channels: 1 })

    expect(chunk).toBeInstanceOf(Uint8Array)
    expect(chunk.length).toBe(44 + 5 * 2) // header + 5 samples * 2 bytes

    // Check WAV header: "RIFF" at offset 0
    const riff = String.fromCharCode(...chunk.slice(0, 4))
    expect(riff).toBe('RIFF')

    // Check "WAVE" at offset 8
    const wave = String.fromCharCode(...chunk.slice(8, 12))
    expect(wave).toBe('WAVE')

    // Check sample rate at offset 24 (little-endian uint32)
    const view = new DataView(chunk.buffer)
    expect(view.getUint32(24, true)).toBe(16000)

    // Check channels at offset 22
    expect(view.getUint16(22, true)).toBe(1)

    // Check bits per sample at offset 34
    expect(view.getUint16(34, true)).toBe(16)

    // Check first sample value (0 -> 0, 0.5 -> 16384, -0.5 -> -16384)
    expect(view.getInt16(44, true)).toBe(0)
    expect(view.getInt16(46, true)).toBeCloseTo(16384, -1)
    expect(view.getInt16(48, true)).toBeCloseTo(-16384, -1)
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /Users/wwj/Desktop/self/legal-agent/frontend
npx vitest run src/lib/wav.test.ts --reporter=verbose
```

Expected: FAIL with `Error: Cannot find module './wav'`

- [ ] **Step 3: 实现最小代码**

```typescript
// frontend/src/lib/wav.ts
export interface WavOptions {
  sampleRate: number
  channels: number
}

export function encodeWavChunk(
  samples: Float32Array,
  options: WavOptions,
): Uint8Array {
  const { sampleRate, channels } = options
  const bitsPerSample = 16
  const bytesPerSample = bitsPerSample / 8
  const byteRate = sampleRate * channels * bytesPerSample
  const blockAlign = channels * bytesPerSample
  const dataSize = samples.length * channels * bytesPerSample
  const headerSize = 44
  const buffer = new ArrayBuffer(headerSize + dataSize)
  const view = new DataView(buffer)
  const bytes = new Uint8Array(buffer)

  // RIFF header
  writeString(view, 0, 'RIFF')
  view.setUint32(4, 36 + dataSize, true)
  writeString(view, 8, 'WAVE')

  // fmt sub-chunk
  writeString(view, 12, 'fmt ')
  view.setUint32(16, 16, true)           // subchunk size
  view.setUint16(20, 1, true)           // audio format: PCM
  view.setUint16(22, channels, true)
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, byteRate, true)
  view.setUint16(32, blockAlign, true)
  view.setUint16(34, bitsPerSample, true)

  // data sub-chunk
  writeString(view, 36, 'data')
  view.setUint32(40, dataSize, true)

  // PCM samples: Float32 [-1, 1] -> Int16
  let offset = headerSize
  for (let i = 0; i < samples.length; i++) {
    const clamped = Math.max(-1, Math.min(1, samples[i]))
    const int16 = Math.round(clamped * 32767)
    view.setInt16(offset, int16, true)
    offset += bytesPerSample
  }

  return bytes
}

function writeString(view: DataView, offset: number, str: string) {
  for (let i = 0; i < str.length; i++) {
    view.setUint8(offset + i, str.charCodeAt(i))
  }
}
```

- [ ] **Step 4: 运行测试确认通过**

```bash
npx vitest run src/lib/wav.test.ts --reporter=verbose
```

Expected: PASS (1 test)

- [ ] **Step 5: 提交**

```bash
git add frontend/src/lib/wav.ts frontend/src/lib/wav.test.ts
git commit -m "feat: Add WAV encoder utility for audio chunks

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: useAudioInput Hook — 骨架与状态机

**Files:**
- Create: `frontend/src/hooks/useAudioInput.ts`
- Test: `frontend/src/hooks/useAudioInput.test.ts`

- [ ] **Step 1: 写状态机失败测试**

```typescript
// frontend/src/hooks/useAudioInput.test.ts
import { describe, it, expect, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useAudioInput } from './useAudioInput'

describe('useAudioInput state machine', () => {
  it('starts in idle mode', () => {
    const { result } = renderHook(() =>
      useAudioInput({ onChunk: vi.fn() }),
    )
    expect(result.current.mode).toBe('idle')
    expect(result.current.isActive).toBe(false)
    expect(result.current.progress).toBeNull()
    expect(result.current.error).toBeNull()
  })

  it('throws when startFile called during mic mode', async () => {
    const { result } = renderHook(() =>
      useAudioInput({ onChunk: vi.fn() }),
    )

    // Mock getUserMedia so startRecording doesn't immediately fail
    vi.stubGlobal('navigator', {
      mediaDevices: {
        getUserMedia: vi.fn().mockResolvedValue({
          getTracks: () => [{ stop: vi.fn() }],
        }),
      },
    })

    await act(async () => {
      await result.current.startRecording()
    })
    expect(result.current.mode).toBe('mic')

    await expect(
      act(async () => {
        await result.current.startFile(new File([], 'test.wav'))
      }),
    ).rejects.toThrow('Audio input already active')
  })

  it('returns to idle after stop', async () => {
    const { result } = renderHook(() =>
      useAudioInput({ onChunk: vi.fn() }),
    )

    vi.stubGlobal('navigator', {
      mediaDevices: {
        getUserMedia: vi.fn().mockResolvedValue({
          getTracks: () => [{ stop: vi.fn() }],
        }),
      },
    })

    await act(async () => {
      await result.current.startRecording()
    })
    expect(result.current.mode).toBe('mic')

    act(() => {
      result.current.stop()
    })
    expect(result.current.mode).toBe('idle')
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

```bash
npx vitest run src/hooks/useAudioInput.test.ts --reporter=verbose
```

Expected: FAIL — module not found

- [ ] **Step 3: 实现 Hook 骨架（状态机 + 错误处理）**

```typescript
// frontend/src/hooks/useAudioInput.ts
import { useState, useCallback, useRef, useEffect } from 'react'
import { encodeWavChunk } from '@/lib/wav'

export type AudioMode = 'idle' | 'mic' | 'file'

export interface UseAudioInputOptions {
  onChunk: (chunk: Uint8Array) => void
  chunkIntervalMs?: number
}

export interface UseAudioInputReturn {
  mode: AudioMode
  isActive: boolean
  progress: number | null
  error: string | null
  startRecording: () => Promise<void>
  startFile: (file: File) => Promise<void>
  stop: () => void
}

const DEFAULT_CHUNK_MS = 300
const MAX_FILE_SIZE = 100 * 1024 * 1024 // 100MB
const SAMPLE_RATE = 16000
const CHANNELS = 1

export function useAudioInput(
  options: UseAudioInputOptions,
): UseAudioInputReturn {
  const { onChunk, chunkIntervalMs = DEFAULT_CHUNK_MS } = options
  const [mode, setMode] = useState<AudioMode>('idle')
  const [progress, setProgress] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  const modeRef = useRef(mode)
  const chunkTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const audioContextRef = useRef<AudioContext | null>(null)
  const sourceNodeRef = useRef<AudioBufferSourceNode | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const workletNodeRef = useRef<AudioWorkletNode | null>(null)
  const samplesRef = useRef<Float32Array[]>([])
  const sentSamplesRef = useRef(0)
  const totalSamplesRef = useRef(0)
  const onChunkRef = useRef(onChunk)

  useEffect(() => {
    modeRef.current = mode
  }, [mode])

  useEffect(() => {
    onChunkRef.current = onChunk
  }, [onChunk])

  const reset = useCallback(() => {
    if (chunkTimerRef.current) {
      clearInterval(chunkTimerRef.current)
      chunkTimerRef.current = null
    }
    if (sourceNodeRef.current) {
      try { sourceNodeRef.current.stop() } catch {}
      sourceNodeRef.current = null
    }
    if (workletNodeRef.current) {
      try { workletNodeRef.current.disconnect() } catch {}
      workletNodeRef.current = null
    }
    if (audioContextRef.current) {
      try { audioContextRef.current.close() } catch {}
      audioContextRef.current = null
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop())
      streamRef.current = null
    }
    samplesRef.current = []
    sentSamplesRef.current = 0
    totalSamplesRef.current = 0
    setProgress(null)
    setError(null)
  }, [])

  const stop = useCallback(() => {
    reset()
    setMode('idle')
  }, [reset])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      reset()
    }
  }, [reset])

  const assertIdle = useCallback(() => {
    if (modeRef.current !== 'idle') {
      throw new Error('Audio input already active')
    }
  }, [])

  const emitWavChunk = useCallback(
    (samples: Float32Array) => {
      const wav = encodeWavChunk(samples, { sampleRate: SAMPLE_RATE, channels: CHANNELS })
      onChunkRef.current(wav)
    },
    [],
  )

  const startRecording = useCallback(async () => {
    assertIdle()
    setError(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream

      const audioContext = new AudioContext({ sampleRate: SAMPLE_RATE })
      audioContextRef.current = audioContext

      // Inject AudioWorklet processor as inline blob
      const workletCode = `
        class PCMProcessor extends AudioWorkletProcessor {
          process(inputs) {
            const input = inputs[0]
            if (input && input[0]) {
              this.port.postMessage(input[0])
            }
            return true
          }
        }
        registerProcessor('pcm-processor', PCMProcessor)
      `
      const blob = new Blob([workletCode], { type: 'application/javascript' })
      const url = URL.createObjectURL(blob)
      await audioContext.audioWorklet.addModule(url)
      URL.revokeObjectURL(url)

      const source = audioContext.createMediaStreamSource(stream)
      const workletNode = new AudioWorkletNode(audioContext, 'pcm-processor')
      workletNodeRef.current = workletNode

      workletNode.port.onmessage = (e) => {
        const float32 = new Float32Array(e.data)
        samplesRef.current.push(float32)
      }

      source.connect(workletNode)

      // Emit chunks on interval
      const chunkSamples = Math.floor((SAMPLE_RATE * chunkIntervalMs) / 1000)
      chunkTimerRef.current = setInterval(() => {
        const allSamples = samplesRef.current
        if (allSamples.length === 0) return

        // Flatten accumulated samples
        let totalLen = 0
        for (const s of allSamples) totalLen += s.length
        if (totalLen < chunkSamples) return

        const flat = new Float32Array(chunkSamples)
        let written = 0
        while (written < chunkSamples && allSamples.length > 0) {
          const s = allSamples[0]
          const need = chunkSamples - written
          const take = Math.min(need, s.length)
          flat.set(s.subarray(0, take), written)
          written += take
          if (take === s.length) {
            allSamples.shift()
          } else {
            allSamples[0] = s.subarray(take)
          }
        }
        emitWavChunk(flat)
      }, chunkIntervalMs)

      setMode('mic')
    } catch (err) {
      reset()
      const message =
        err instanceof DOMException && err.name === 'NotAllowedError'
          ? '麦克风权限被拒绝，请在浏览器设置中允许访问'
          : err instanceof Error
            ? err.message
            : '启动录音失败'
      setError(message)
      throw err
    }
  }, [assertIdle, chunkIntervalMs, emitWavChunk, reset])

  const startFile = useCallback(
    async (file: File) => {
      assertIdle()
      setError(null)

      if (file.size > MAX_FILE_SIZE) {
        const msg = '文件过大，请上传 100MB 以内的音频'
        setError(msg)
        throw new Error(msg)
      }

      try {
        const arrayBuffer = await file.arrayBuffer()
        const audioContext = new AudioContext({ sampleRate: SAMPLE_RATE })
        audioContextRef.current = audioContext

        const audioBuffer = await audioContext.decodeAudioData(arrayBuffer)
        const channelData = audioBuffer.getChannelData(0)
        totalSamplesRef.current = channelData.length

        // Start local playback
        const sourceNode = audioContext.createBufferSource()
        sourceNode.buffer = audioBuffer
        sourceNode.connect(audioContext.destination)
        sourceNode.start()
        sourceNodeRef.current = sourceNode

        // Emit chunks on interval
        const chunkSamples = Math.floor((SAMPLE_RATE * chunkIntervalMs) / 1000)
        let offset = 0

        chunkTimerRef.current = setInterval(() => {
          if (offset >= channelData.length) {
            stop()
            return
          }
          const end = Math.min(offset + chunkSamples, channelData.length)
          const slice = channelData.slice(offset, end)
          emitWavChunk(slice)
          offset = end
          sentSamplesRef.current = offset
          setProgress(Math.round((offset / channelData.length) * 100))
        }, chunkIntervalMs)

        // Handle natural end
        sourceNode.onended = () => {
          if (modeRef.current === 'file') {
            stop()
          }
        }

        setMode('file')
      } catch (err) {
        reset()
        const message =
          err instanceof Error && err.name === 'NotSupportedError'
            ? '无法解析该音频文件，请尝试 MP3 或 WAV 格式'
            : err instanceof Error
              ? err.message
              : '文件处理失败'
        setError(message)
        throw err
      }
    },
    [assertIdle, chunkIntervalMs, emitWavChunk, reset, stop],
  )

  return {
    mode,
    isActive: mode !== 'idle',
    progress,
    error,
    startRecording,
    startFile,
    stop,
  }
}
```

- [ ] **Step 4: 运行测试确认通过**

```bash
npx vitest run src/hooks/useAudioInput.test.ts --reporter=verbose
```

Expected: PASS (3 tests)

- [ ] **Step 5: 提交**

```bash
git add frontend/src/hooks/useAudioInput.ts frontend/src/hooks/useAudioInput.test.ts
git commit -m "feat: Add useAudioInput hook with state machine

Supports mic recording and file upload modes with mutual exclusion.
Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: AudioControls 组件

**Files:**
- Create: `frontend/src/components/AudioControls.tsx`
- Test: `frontend/src/components/AudioControls.test.tsx`

- [ ] **Step 1: 写交互失败测试**

```typescript
// frontend/src/components/AudioControls.test.tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import AudioControls from './AudioControls'

describe('AudioControls', () => {
  it('renders record and upload buttons in idle state', () => {
    render(<AudioControls onChunk={vi.fn()} />)
    expect(screen.getByText('🎤 开始录音')).toBeInTheDocument()
    expect(screen.getByText('📁 上传音频')).toBeInTheDocument()
  })

  it('calls startRecording when record button clicked', async () => {
    render(<AudioControls onChunk={vi.fn()} />)
    const btn = screen.getByText('🎤 开始录音')

    // Mock getUserMedia
    vi.stubGlobal('navigator', {
      mediaDevices: {
        getUserMedia: vi.fn().mockResolvedValue({
          getTracks: () => [{ stop: vi.fn() }],
        }),
      },
    })

    fireEvent.click(btn)
    // After async start, mode changes to mic
    await vi.waitFor(() => {
      expect(screen.getByText('⏹ 停止')).toBeInTheDocument()
    })
  })

  it('shows error message when provided', () => {
    // We need to trigger an error - easiest is to mock the hook
    const { useAudioInput } = await import('@/hooks/useAudioInput')
    vi.mocked(useAudioInput).mockReturnValue({
      mode: 'idle',
      isActive: false,
      progress: null,
      error: '测试错误',
      startRecording: vi.fn(),
      startFile: vi.fn(),
      stop: vi.fn(),
    })

    render(<AudioControls onChunk={vi.fn()} />)
    expect(screen.getByText('测试错误')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

```bash
npx vitest run src/components/AudioControls.test.tsx --reporter=verbose
```

Expected: FAIL

- [ ] **Step 3: 实现组件**

```tsx
// frontend/src/components/AudioControls.tsx
import { useRef, useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { useAudioInput } from '@/hooks/useAudioInput'

interface AudioControlsProps {
  onChunk: (chunk: Uint8Array) => void
}

export default function AudioControls({ onChunk }: AudioControlsProps) {
  const { mode, isActive, progress, error, startRecording, startFile, stop } =
    useAudioInput({ onChunk })
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [visibleError, setVisibleError] = useState<string | null>(null)

  useEffect(() => {
    if (error) {
      setVisibleError(error)
      const timer = setTimeout(() => setVisibleError(null), 3000)
      return () => clearTimeout(timer)
    }
  }, [error])

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) {
      startFile(file)
    }
    // Reset input so same file can be selected again
    e.target.value = ''
  }

  return (
    <div className="flex items-center gap-3">
      {mode === 'idle' && (
        <>
          <Button
            size="sm"
            onClick={() => startRecording()}
            className="bg-amber-600 hover:bg-amber-500 text-zinc-900 border-amber-500"
          >
            🎤 开始录音
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => fileInputRef.current?.click()}
            className="border-zinc-700 text-zinc-300 hover:bg-zinc-800"
          >
            📁 上传音频
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            accept="audio/*"
            className="hidden"
            onChange={handleFileChange}
          />
        </>
      )}

      {mode === 'mic' && (
        <div className="flex items-center gap-3">
          <Button
            size="sm"
            variant="destructive"
            onClick={stop}
            className="bg-red-900 hover:bg-red-800 text-red-200 border-red-700"
          >
            ⏹ 停止
          </Button>
          <span className="flex items-center gap-2 text-sm text-red-400">
            <span className="w-2 h-2 bg-red-500 rounded-full animate-pulse" />
            录音中...
          </span>
        </div>
      )}

      {mode === 'file' && (
        <div className="flex items-center gap-3">
          <Button
            size="sm"
            variant="destructive"
            onClick={stop}
            className="bg-red-900 hover:bg-red-800 text-red-200 border-red-700"
          >
            ⏹ 停止
          </Button>
          <span className="text-sm text-zinc-300">▶️ 播放中...</span>
          {progress !== null && (
            <div className="w-32 h-2 bg-zinc-800 rounded-full overflow-hidden">
              <div
                className="h-full bg-amber-500 transition-all duration-300"
                style={{ width: `${progress}%` }}
              />
            </div>
          )}
          {progress !== null && (
            <span className="text-xs text-zinc-500 font-mono w-10 text-right">
              {progress}%
            </span>
          )}
        </div>
      )}

      {visibleError && (
        <span className="text-xs text-red-400 animate-in fade-in slide-in-from-top-1">
          {visibleError}
        </span>
      )}
    </div>
  )
}
```

- [ ] **Step 4: 运行测试确认通过**

```bash
npx vitest run src/components/AudioControls.test.tsx --reporter=verbose
```

Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/AudioControls.tsx frontend/src/components/AudioControls.test.tsx
git commit -m "feat: Add AudioControls component

UI for mic recording and file upload with progress and error display.
Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: LiveSession 集成

**Files:**
- Modify: `frontend/src/pages/LiveSession.tsx`

- [ ] **Step 1: 修改 LiveSession Header**

将现有空壳录音按钮替换为 `AudioControls`：

```tsx
// frontend/src/pages/LiveSession.tsx
// 1. 添加 import
import AudioControls from '@/components/AudioControls'

// 2. 删除 isRecording state（第136行附近）
// 删除: const [isRecording, setIsRecording] = useState(false)

// 3. 替换 header 中的按钮区域
// 从（约第201-211行）:
<Button
  variant={isRecording ? 'destructive' : 'default'}
  size="sm"
  onClick={() => setIsRecording(prev => !prev)}
  className={...}
>
  {isRecording ? '⏹ 停止' : '🎤 开始录音'}
</Button>

// 替换为:
<AudioControls onChunk={sendAudioChunk} />
```

完整修改后的 Header 区域（约第191-212行）：

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

- [ ] **Step 2: 清理未使用的 import 和 state**

删除：`useState` 中的 `isRecording`（如果 `Button` import 只被录音按钮使用，也删除 `Button` import，检查是否还有其他地方用 Button）

检查：LiveSession 中是否还有其他地方用 `isRecording`？没有的话删掉这行 state。

- [ ] **Step 3: 运行 lint 检查**

```bash
cd /Users/wwj/Desktop/self/legal-agent/frontend
pnpm lint
```

Expected: 无错误

- [ ] **Step 4: 运行现有测试确保没破坏**

```bash
npx vitest run --reporter=verbose
```

Expected: 所有现有测试通过 + 新增测试通过

- [ ] **Step 5: 提交**

```bash
git add frontend/src/pages/LiveSession.tsx
git commit -m "feat: Integrate AudioControls into LiveSession

Replace dummy recording button with real AudioControls component.
Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: 端到端验证

**Files:** 不涉及文件修改，手动验证

- [ ] **Step 1: 启动后端服务**

```bash
cd /Users/wwj/Desktop/self/legal-agent/backend
uv run uvicorn main:app --reload
```

在另一个终端确认后端启动成功。

- [ ] **Step 2: 启动前端开发服务器**

```bash
cd /Users/wwj/Desktop/self/legal-agent/frontend
pnpm dev
```

- [ ] **Step 3: 麦克风录音验证**

1. 浏览器打开 `http://localhost:5173/session/demo`
2. 点击「🎤 开始录音」
3. 允许麦克风权限
4. 说话 10 秒
5. 观察左侧转写面板是否出现文本
6. 点击「⏹ 停止」
7. 确认转写停止更新

- [ ] **Step 4: 文件上传验证**

1. 点击「📁 上传音频」
2. 选择一个 10-30 秒的 MP3/WAV 文件
3. 确认浏览器开始播放音频
4. 观察进度条从 0% 走到 100%
5. 观察左侧转写面板是否出现文本
6. 确认右侧分析面板出现 Agent 反馈
7. 点击「⏹ 停止」确认播放和发送都停止

- [ ] **Step 5: 互斥验证**

1. 开始录音
2. 确认上传按钮消失
3. 停止录音
4. 上传文件
5. 确认录音按钮消失
6. 停止播放
7. 两个按钮都恢复

- [ ] **Step 6: 错误处理验证**

1. 拒绝麦克风权限 → 确认出现红色错误提示
2. 上传一个 `.txt` 文件重命名为 `.mp3` → 确认解码错误提示
3. 上传一个 200MB 文件 → 确认文件过大提示

---

## Plan Self-Review

### Spec Coverage Check

| Spec 章节 | 覆盖任务 |
|-----------|---------|
| 2.1 单 Hook 统一封装 | Task 2 |
| 2.2 互斥策略 | Task 2 (assertIdle + mode state) |
| 2.3 音频格式 WAV/PCM | Task 1 (encodeWavChunk) + Task 2 |
| 2.4 文件同步播放 | Task 2 (AudioBufferSourceNode) |
| 3 组件架构 | Task 3 + Task 4 |
| 4.1 接口 | Task 2 |
| 4.3 麦克风模式 | Task 2 (AudioWorklet) |
| 4.4 文件模式 | Task 2 (decodeAudioData + 切片) |
| 4.5 错误处理 | Task 2 |
| 5 AudioControls UI | Task 3 |
| 6 LiveSession 集成 | Task 4 |
| 7 边界情况 | Task 2 + Task 5 |
| 8 测试策略 | Task 1-4 的测试步骤 |

**Gap: 无。** 所有 spec 需求都有对应任务。

### Placeholder Scan

- [x] 无 "TBD" / "TODO" / "implement later"
- [x] 无 "Add appropriate error handling"（具体到了每种错误的消息文本）
- [x] 无 "Similar to Task N"
- [x] 每个代码步骤都有完整代码
- [x] 每个命令都有预期输出

### Type Consistency

- `UseAudioInputOptions.onChunk` 签名 `(chunk: Uint8Array) => void` 在 Task 2、3、4 中一致
- `AudioMode` 类型 `'idle' | 'mic' | 'file'` 在 Task 2、3 中一致
- WAV 参数 `SAMPLE_RATE = 16000`、`CHANNELS = 1` 在 Task 1、2 中一致

---

**Plan saved to:** `docs/superpowers/plans/2026-05-29-audio-input-enhancement.md`
