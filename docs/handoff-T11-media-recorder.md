# Handoff: legal-agent — T11 前端 MediaRecorder Hook

**日期:** 2026-05-26 | **分支:** main | **前置任务:** T3+T9

## 任务目标

实现 `useMediaRecorder` hook — 浏览器采集麦克风音频，分块发送到 WebSocket。

## 依赖

- `useWebSocket` hook 已完成（`sendAudioChunk` 接口）
- LiveSession 页面已实现

## 文件

```
frontend/src/hooks/useMediaRecorder.ts  — 新增
frontend/src/pages/LiveSession.tsx      — 集成
```

## Hook 接口

```typescript
function useMediaRecorder(sendAudioChunk: (chunk: Uint8Array) => void): {
  isRecording: boolean
  start: () => Promise<void>   // 请求权限 + 开始采集
  stop: () => void              // 停止采集
}
```

## 实现要点

```typescript
export function useMediaRecorder(
  sendAudioChunk: (chunk: Uint8Array) => void,
  timeslice = 800,  // 每 800ms 切一块
) {
  const mediaRecorder = useRef<MediaRecorder | null>(null)
  const [isRecording, setIsRecording] = useState(false)

  const start = useCallback(async () => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    const recorder = new MediaRecorder(stream, { mimeType: 'audio/webm;codecs=opus' })

    recorder.ondataavailable = async (e) => {
      if (e.data.size > 0) {
        const buffer = await e.data.arrayBuffer()
        sendAudioChunk(new Uint8Array(buffer))
      }
    }

    recorder.start(timeslice)
    mediaRecorder.current = recorder
    setIsRecording(true)
  }, [sendAudioChunk, timeslice])

  const stop = useCallback(() => {
    mediaRecorder.current?.stop()
    mediaRecorder.current?.stream.getTracks().forEach(t => t.stop())
    setIsRecording(false)
  }, [])

  return { isRecording, start, stop }
}
```

## LiveSession 集成

```tsx
// 替换现有的 setIsRecording 为真实录音
const { isRecording, start, stop } = useMediaRecorder(sendAudioChunk)

<Button onClick={isRecording ? stop : start}>
  {isRecording ? '⏹ 停止' : '🎤 开始录音'}
</Button>
```

## 边缘情况

- 权限拒绝 → catch 并显示明确提示
- 标签页后台 → MediaRecorder 继续采集（浏览器默认行为）
- 不支持 webm → 降级到其他 mimeType

## 测试

Chrome 手动测试（需要真实麦克风）：
- 点击录音 → 权限弹窗 → 允许 → 开始采集
- 录音中 → WebSocket 收到 audio_chunk
- 点击停止 → stream 释放
- 权限拒绝 → 显示错误提示

## 估时

human ~30min / CC ~10min
