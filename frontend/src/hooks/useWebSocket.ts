import { useRef, useState, useCallback, useEffect } from 'react'

type ProfileEntryData = {
  key: string
  value: string
  subject: string
}

type Callbacks = {
  onTranscript?: (data: TranscriptData) => void
  onAnalysis?: (data: AnalysisData) => void
  onSuggestion?: (data: SuggestionData) => void
  onConfirmAck?: (data: { request_id: string; ok: boolean }) => void
  onProfileUpdate?: (entries: ProfileEntryData[]) => void
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
    preview?: {
      topic: string
      rationale: string
    }
  }
}

export function useWebSocket(sessionId: string, callbacks: Callbacks = {}) {
  const [isConnected, setIsConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const pingRef = useRef<ReturnType<typeof setInterval>>(null)
  const reconnectRef = useRef<ReturnType<typeof setTimeout>>(null)
  const callbacksRef = useRef(callbacks)
  const connectRef = useRef<() => void>(() => {})
  const reconnectAttemptsRef = useRef(0)
  const maxReconnectAttempts = 3

  const wsUrl = `ws://localhost:8000/ws/${sessionId}`

  const cleanup = useCallback(() => {
    if (reconnectRef.current) clearTimeout(reconnectRef.current)
    if (pingRef.current) clearInterval(pingRef.current)
    const ws = wsRef.current
    if (ws) {
      // 解绑 onclose,避免主动关闭触发重连逻辑(StrictMode 双挂载下会形成 2 秒一次的无限循环)
      ws.onopen = null
      ws.onmessage = null
      ws.onclose = null
      ws.onerror = null
      ws.close()
    }
    wsRef.current = null
  }, [])

  const connect = useCallback(() => {
    if (!sessionId) return
    cleanup()
    const ws = new WebSocket(wsUrl)

    ws.onopen = () => {
      setIsConnected(true)
      setError(null)
      reconnectAttemptsRef.current = 0
      pingRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'ping' }))
        } else {
          if (pingRef.current) clearInterval(pingRef.current)
        }
      }, 15_000)
    }

    ws.onclose = (e: CloseEvent) => {
      setIsConnected(false)
      // code 4000-4999 = 业务关闭（被接管、已结束、不存在、无权访问），不重连
      if (e.code >= 4000 && e.code < 5000) {
        setError(e.reason || `连接已关闭 (code=${e.code})`)
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

      if (msg.type === 'profile_update') {
        const entries = (msg.entries as ProfileEntryData[]) ?? []
        callbacksRef.current.onProfileUpdate?.(entries)
        return
      }

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
  }, [wsUrl, cleanup, sessionId])

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
      wsRef.current.send(chunk.buffer as ArrayBuffer)
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

  const notifyAudioEnd = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'audio_end' }))
    }
  }, [])

  const reconnect = useCallback(() => {
    reconnectAttemptsRef.current = 0
    setError(null)
    connect()
  }, [connect])

  return { isConnected, error, sendAudioChunk, confirmIntent, dismissIntent, notifyAudioEnd, reconnect }
}
