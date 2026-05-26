import { describe, it, expect, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useWebSocket, type WsLike } from './useWebSocket'

function createMockWs(): { ws: WsLike; open: () => void; close: () => void; msg: (data: object) => void; sent: () => (string | ArrayBuffer | Uint8Array)[] } {
  const sent: (string | ArrayBuffer | Uint8Array)[] = []
  let onopen: (() => void) | null = null
  let onclose: (() => void) | null = null
  let onmessage: ((e: MessageEvent) => void) | null = null

  return {
    ws: {
      set onopen(fn: (() => void) | null) { onopen = fn },
      set onclose(fn: (() => void) | null) { onclose = fn },
      set onmessage(fn: ((e: MessageEvent) => void) | null) { onmessage = fn },
      get readyState() { return WebSocket.OPEN },
      send(data) { sent.push(data) },
      close: vi.fn(),
      addEventListener: vi.fn(),
    },
    open: () => onopen?.(),
    close: () => onclose?.(),
    msg: (data: object) => onmessage?.(new MessageEvent('message', { data: JSON.stringify(data) })),
    sent: () => sent,
  }
}

describe('useWebSocket', () => {
  it('连接后 isConnected 为 true', async () => {
    const { ws, open } = createMockWs()
    const { result } = renderHook(() =>
      useWebSocket('ws://localhost:8000/ws/test', {}, () => ws)
    )

    expect(result.current.isConnected).toBe(false)
    await act(async () => { open() })
    expect(result.current.isConnected).toBe(true)
  })

  it('sendAudioChunk 发送数据', async () => {
    const { ws, open, sent } = createMockWs()
    const { result } = renderHook(() =>
      useWebSocket('ws://localhost:8000/ws/test', {}, () => ws)
    )

    await act(async () => { open() })

    const chunk = new Uint8Array([0, 1, 2, 3])
    act(() => { result.current.sendAudioChunk(chunk) })
    expect(sent().length).toBe(1)
  })

  it('收到 transcript 消息时调用 onTranscript', async () => {
    const { ws, open, msg } = createMockWs()
    const onTranscript = vi.fn()

    renderHook(() =>
      useWebSocket('ws://localhost:8000/ws/test', { onTranscript }, () => ws)
    )

    await act(async () => { open() })
    await act(async () => {
      msg({ type: 'transcript', text: '您这个情况属于...', speaker: '律师', is_final: true })
    })

    expect(onTranscript).toHaveBeenCalledWith({
      type: 'transcript',
      text: '您这个情况属于...',
      speaker: '律师',
      is_final: true,
    })
  })

  it('收到 analysis 消息时调用 onAnalysis', async () => {
    const { ws, open, msg } = createMockWs()
    const onAnalysis = vi.fn()

    renderHook(() =>
      useWebSocket('ws://localhost:8000/ws/test', { onAnalysis }, () => ws)
    )

    await act(async () => { open() })
    await act(async () => {
      msg({
        type: 'analysis', category: 'statute', title: '劳动合同法 第82条',
        content: '用人单位自用工之日起超过一个月...', citation: '《中华人民共和国劳动合同法》',
      })
    })

    expect(onAnalysis).toHaveBeenCalledWith({
      type: 'analysis', category: 'statute', title: '劳动合同法 第82条',
      content: '用人单位自用工之日起超过一个月...', citation: '《中华人民共和国劳动合同法》',
    })
  })

  it('断开后 isConnected 为 false', async () => {
    const { ws, open, close } = createMockWs()
    const { result } = renderHook(() =>
      useWebSocket('ws://localhost:8000/ws/test', {}, () => ws)
    )

    await act(async () => { open() })
    expect(result.current.isConnected).toBe(true)

    await act(async () => { close() })
    expect(result.current.isConnected).toBe(false)
  })
})
