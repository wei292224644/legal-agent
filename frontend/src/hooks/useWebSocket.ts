import { useRef, useState, useCallback, useEffect } from 'react'

type Callbacks = {
  onTranscript?: (data: TranscriptData) => void
  onAnalysis?: (data: AnalysisData) => void
  onSuggestion?: (data: SuggestionData) => void
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
    severity: string
    intent_type: string
    law_domain: string | null
    entities: string[]
    utt_id: string
    request_id?: string
  }
}

export interface WsLike {
  set onopen(fn: (() => void) | null)
  set onclose(fn: (() => void) | null)
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
  const [sessionIdState] = useState<string>(() => sessionId ?? getOrCreateSessionId())
  const wsRef = useRef<WsLike | null>(null)
  const pingRef = useRef<ReturnType<typeof setInterval>>(null)
  const reconnectRef = useRef<ReturnType<typeof setTimeout>>(null)
  const callbacksRef = useRef(callbacks)
  const connectRef = useRef<() => void>(() => {})

  // 把 url 最后一段替换为 sessionId，保持 host/path 不变
  const baseUrl = url.replace(/\/[^/]*$/, '')
  const wsUrl = `${baseUrl}/${sessionIdState}`

  const cleanup = useCallback(() => {
    clearTimeout(reconnectRef.current)
    clearInterval(pingRef.current)
    wsRef.current?.close()
    wsRef.current = null
  }, [])

  const connect = useCallback(() => {
    cleanup()
    const ws = factory(wsUrl)

    ws.onopen = () => {
      setIsConnected(true)
      pingRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'ping' }))
        } else {
          clearInterval(pingRef.current)
        }
      }, 15_000)
    }

    ws.onclose = () => {
      setIsConnected(false)
      reconnectRef.current = setTimeout(() => connectRef.current(), 2000)
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
    wsRef.current?.send(chunk)
  }, [])

  const confirmIntent = useCallback((requestId: string) => {
    wsRef.current?.send(JSON.stringify({ type: 'confirm', request_id: requestId }))
  }, [])

  const dismissIntent = useCallback((requestId: string) => {
    wsRef.current?.send(JSON.stringify({ type: 'dismiss', request_id: requestId }))
  }, [])

  return { isConnected, sendAudioChunk, confirmIntent, dismissIntent, sessionId: sessionIdState }
}
