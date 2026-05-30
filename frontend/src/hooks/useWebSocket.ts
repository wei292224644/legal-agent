import { useRef, useState, useCallback, useEffect } from 'react'

type Callbacks = {
  onTranscript?: (data: TranscriptData) => void
  onAnalysis?: (data: AnalysisData) => void
  onSuggestion?: (data: SuggestionData) => void
  onConfirmAck?: (data: { request_id: string; ok: boolean }) => void
}

type TranscriptData = {
  text: string
  speaker: string
  is_final: boolean
}

type AnalysisData = {
  category: string
  title: string
  content: string
  citation?: string
}

export type SuggestionData = {
  type: 'suggestion.pending' | 'suggestion.ready'
  text: string | null
  meta: {
    utt_id: string
    request_id?: string
    // 仅 pending 携带,由 child agent 通过 deep_analysis 工具产出
    preview?: {
      topic: string
      rationale: string
    }
  }
}

export interface WsLike {
  set onopen(fn: (() => void) | null)
  set onclose(fn: ((e: CloseEvent) => void) | null)
  set onmessage(fn: ((e: MessageEvent) => void) | null)
  readonly readyState: number
  send(data: string | ArrayBuffer | Uint8Array): void
  close(): void
  addEventListener(type: string, cb: () => void, opts?: { once?: boolean }): void
}

type WsFactory = (url: string) => WsLike

const defaultFactory: WsFactory = (u) => new WebSocket(u) as unknown as WsLike

function getOrCreateSessionId(): string {
  const key = 'legal_session_id'
  const stored = localStorage.getItem(key)
  if (stored) return stored
  const id = crypto.randomUUID()
  localStorage.setItem(key, id)
  return id
}

export function useWebSocket(
  url: string,
  callbacks: Callbacks = {},
  factory: WsFactory = defaultFactory,
  sessionId?: string,
) {
  const [isConnected, setIsConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sessionIdState] = useState<string>(() => sessionId ?? getOrCreateSessionId())
  const wsRef = useRef<WsLike | null>(null)
  const pingRef = useRef<ReturnType<typeof setInterval>>(null)
  const reconnectRef = useRef<ReturnType<typeof setTimeout>>(null)
  const stableTimerRef = useRef<ReturnType<typeof setTimeout>>(null)
  const callbacksRef = useRef(callbacks)
  const connectRef = useRef<() => void>(() => {})
  const reconnectAttemptsRef = useRef(0)
  const maxReconnectAttempts = 3
  // 连接稳定多少毫秒后才算"成功"并允许重置重连计数。
  // 不加这个的话:open → close 立刻发生时计数器永远重置 → 无限循环重连。
  const stableConnectionMs = 5_000

  // 把 url 最后一段替换为 sessionId，保持 host/path 不变
  const baseUrl = url.replace(/\/[^/]*$/, '')
  const wsUrl = `${baseUrl}/${sessionIdState}`

  const cleanup = useCallback(() => {
    clearTimeout(reconnectRef.current)
    clearTimeout(stableTimerRef.current)
    clearInterval(pingRef.current)
    wsRef.current?.close()
    wsRef.current = null
  }, [])

  const connect = useCallback(() => {
    cleanup()
    const ws = factory(wsUrl)

    ws.onopen = () => {
      setIsConnected(true)
      setError(null)
      // 只有连接稳定保持 stableConnectionMs 才把计数器重置。
      // open 立即重置的话 → close 立即触发 → 重连 → open 又重置 → 无限循环。
      stableTimerRef.current = setTimeout(() => {
        reconnectAttemptsRef.current = 0
      }, stableConnectionMs)
      pingRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'ping' }))
        } else {
          clearInterval(pingRef.current)
        }
      }, 15_000)
    }

    ws.onclose = (e: CloseEvent) => {
      setIsConnected(false)
      clearTimeout(stableTimerRef.current)
      // 调试日志:为什么连接关了。CloseEvent.code 是关键信号。
      console.warn(
        `[ws] closed code=${e.code} reason=${e.reason || '(empty)'} wasClean=${e.wasClean}`,
      )
      // code 1008 = 排他连接被拒绝（session 已有活跃连接）
      if (e.code === 1008) {
        setError(e.reason || 'Session already connected')
        return
      }
      if (reconnectAttemptsRef.current < maxReconnectAttempts) {
        reconnectAttemptsRef.current += 1
        reconnectRef.current = setTimeout(() => connectRef.current(), 2000)
      } else {
        setError(`连接重试 ${maxReconnectAttempts} 次后放弃 (code=${e.code})`)
      }
    }

    ws.onmessage = (e: MessageEvent) => {
      let msg: Record<string, unknown>
      try {
        msg = JSON.parse(e.data)
      } catch {
        return
      }

      if (msg.type === 'pong') return

      if (msg.type === 'transcript') {
        callbacksRef.current.onTranscript?.(msg as unknown as TranscriptData)
        return
      }

      if (msg.type === 'analysis') {
        callbacksRef.current.onAnalysis?.(msg as unknown as AnalysisData)
        return
      }

      if (msg.type === 'suggestion.pending' || msg.type === 'suggestion.ready') {
        callbacksRef.current.onSuggestion?.(msg as unknown as SuggestionData)
        return
      }

      if (msg.type === 'confirm_ack') {
        callbacksRef.current.onConfirmAck?.(msg as { request_id: string; ok: boolean })
        return
      }
    }

    wsRef.current = ws
  }, [wsUrl, factory, cleanup])

  // Ref sync pattern (advanced-event-handler-refs / advanced-use-latest)
  useEffect(() => {
    callbacksRef.current = callbacks
    connectRef.current = connect
  })

  useEffect(() => {
    connect()
    return cleanup
  }, [connect, cleanup])

  const sendAudioChunk = useCallback((chunk: Uint8Array) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(chunk)
    }
  }, [])

  const confirmIntent = useCallback((requestId: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'confirm', request_id: requestId }))
    }
  }, [])

  const dismissIntent = useCallback((requestId: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'dismiss', request_id: requestId }))
    }
  }, [])

  return { isConnected, error, sendAudioChunk, confirmIntent, dismissIntent, sessionId: sessionIdState }
}
