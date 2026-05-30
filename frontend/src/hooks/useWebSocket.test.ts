import { describe, it, expect, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useWebSocket, type WsLike } from './useWebSocket'

function createMockWs(): { ws: WsLike; open: () => void; close: (code?: number, reason?: string) => void; msg: (data: object) => void; rawMsg: (data: string) => void; sent: () => (string | ArrayBuffer | Uint8Array)[] } {
  const sent: (string | ArrayBuffer | Uint8Array)[] = []
  let onopen: (() => void) | null = null
  let onclose: ((e: CloseEvent) => void) | null = null
  let onmessage: ((e: MessageEvent) => void) | null = null

  return {
    ws: {
      set onopen(fn: (() => void) | null) { onopen = fn },
      set onclose(fn: ((e: CloseEvent) => void) | null) { onclose = fn },
      set onmessage(fn: ((e: MessageEvent) => void) | null) { onmessage = fn },
      get readyState() { return WebSocket.OPEN },
      send(data) { sent.push(data) },
      close: vi.fn(),
      addEventListener: vi.fn(),
    },
    open: () => onopen?.(),
    close: (code = 1000, reason = '') => onclose?.(new CloseEvent('close', { code, reason })),
    msg: (data: object) => onmessage?.(new MessageEvent('message', { data: JSON.stringify(data) })),
    rawMsg: (data: string) => onmessage?.(new MessageEvent('message', { data })),
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

  it('收到 suggestion.pending 消息时调用 onSuggestion', async () => {
    const { ws, open, msg } = createMockWs()
    const onSuggestion = vi.fn()

    renderHook(() =>
      useWebSocket('ws://localhost:8000/ws/test', { onSuggestion }, () => ws)
    )

    await act(async () => { open() })
    const payload = {
      type: 'suggestion.pending', text: null,
      meta: { utt_id: 'u_1', request_id: 'req_abc', preview: { topic: '违法解除赔偿', rationale: '需要全画像判断 2N 还是 N+1' } },
    }
    await act(async () => { msg(payload) })

    expect(onSuggestion).toHaveBeenCalledWith(payload)
  })

  it('收到 suggestion.ready 消息时调用 onSuggestion', async () => {
    const { ws, open, msg } = createMockWs()
    const onSuggestion = vi.fn()

    renderHook(() =>
      useWebSocket('ws://localhost:8000/ws/test', { onSuggestion }, () => ws)
    )

    await act(async () => { open() })
    const payload = {
      type: 'suggestion.ready', text: '根据劳动法第87条，应支付2N赔偿金。',
      meta: { utt_id: 'u_2', request_id: 'req_abc' },
    }
    await act(async () => { msg(payload) })

    expect(onSuggestion).toHaveBeenCalledWith(payload)
  })

  it('confirmIntent 发送 confirm 消息', async () => {
    const { ws, open, sent } = createMockWs()
    const { result } = renderHook(() =>
      useWebSocket('ws://localhost:8000/ws/test', {}, () => ws)
    )

    await act(async () => { open() })
    act(() => { result.current.confirmIntent('req_abc') })

    expect(sent()).toContain(JSON.stringify({ type: 'confirm', request_id: 'req_abc' }))
  })

  it('dismissIntent 发送 dismiss 消息', async () => {
    const { ws, open, sent } = createMockWs()
    const { result } = renderHook(() =>
      useWebSocket('ws://localhost:8000/ws/test', {}, () => ws)
    )

    await act(async () => { open() })
    act(() => { result.current.dismissIntent('req_abc') })

    expect(sent()).toContain(JSON.stringify({ type: 'dismiss', request_id: 'req_abc' }))
  })

  it('收到非法 JSON 不抛异常', async () => {
    const { ws, open, rawMsg } = createMockWs()
    const onTranscript = vi.fn()

    renderHook(() =>
      useWebSocket('ws://localhost:8000/ws/test', { onTranscript }, () => ws)
    )

    await act(async () => { open() })
    expect(() => rawMsg('this is not json{')).not.toThrow()
    expect(onTranscript).not.toHaveBeenCalled()
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

  it('连续重连失败 3 次后停止重连', async () => {
    vi.useFakeTimers()
    const mocks: ReturnType<typeof createMockWs>[] = []
    const factory = vi.fn(() => {
      const m = createMockWs()
      mocks.push(m)
      return m.ws
    })

    const { result } = renderHook(() =>
      useWebSocket('ws://localhost:8000/ws/test', {}, factory)
    )

    // 初始连接成功
    await act(async () => { mocks[0].open() })
    expect(result.current.isConnected).toBe(true)

    // 第 1 次断开 → 触发重连，但不模拟连接成功（连续失败）
    await act(async () => { mocks[0].close() })
    expect(result.current.isConnected).toBe(false)
    act(() => { vi.advanceTimersByTime(2000) })
    expect(factory).toHaveBeenCalledTimes(2)

    // 第 2 次断开（重连失败）→ 再次触发重连
    await act(async () => { mocks[1].close() })
    act(() => { vi.advanceTimersByTime(2000) })
    expect(factory).toHaveBeenCalledTimes(3)

    // 第 3 次断开（重连失败）→ 最后一次重连
    await act(async () => { mocks[2].close() })
    act(() => { vi.advanceTimersByTime(2000) })
    expect(factory).toHaveBeenCalledTimes(4)

    // 第 4 次断开 → 已达最大重连次数，不再重连
    await act(async () => { mocks[3].close() })
    act(() => { vi.advanceTimersByTime(10000) })
    expect(factory).toHaveBeenCalledTimes(4)

    vi.useRealTimers()
  })

  it('收到 code 1008 后停止重连', async () => {
    vi.useFakeTimers()
    const mocks: ReturnType<typeof createMockWs>[] = []
    const factory = vi.fn(() => {
      const m = createMockWs()
      mocks.push(m)
      return m.ws
    })

    const { result } = renderHook(() =>
      useWebSocket('ws://localhost:8000/ws/test', {}, factory)
    )

    await act(async () => { mocks[0].open() })
    expect(result.current.isConnected).toBe(true)

    // 后端拒绝排他连接
    await act(async () => { mocks[0].close(1008, 'Session already connected') })
    expect(result.current.isConnected).toBe(false)

    // 不再重连
    act(() => { vi.advanceTimersByTime(10000) })
    expect(factory).toHaveBeenCalledTimes(1)

    vi.useRealTimers()
  })
})
