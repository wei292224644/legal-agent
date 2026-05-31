import { useRef, useState, useCallback, useEffect } from 'react'
import type { ServerEvent } from '@/types/events'

export function useWebSocket(
  sessionId: string,
  onEvent: (evt: ServerEvent) => void,
) {
  const [isConnected, setIsConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const pingRef = useRef<ReturnType<typeof setInterval>>(null)
  const reconnectRef = useRef<ReturnType<typeof setTimeout>>(null)
  const onEventRef = useRef(onEvent)
  const connectRef = useRef<() => void>(() => {})
  const reconnectAttemptsRef = useRef(0)
  const maxReconnectAttempts = 3

  const wsUrl = `ws://localhost:8000/ws/${sessionId}`

  const cleanup = useCallback(() => {
    if (reconnectRef.current) clearTimeout(reconnectRef.current)
    if (pingRef.current) clearInterval(pingRef.current)
    const ws = wsRef.current
    if (ws) {
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
        } else if (pingRef.current) {
          clearInterval(pingRef.current)
        }
      }, 15_000)
    }

    ws.onclose = (e: CloseEvent) => {
      setIsConnected(false)
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
      try {
        const evt = JSON.parse(e.data) as ServerEvent
        onEventRef.current(evt)
      } catch {
        // 无效 JSON 直接丢弃,后端理论上不会发
      }
    }

    wsRef.current = ws
  }, [wsUrl, cleanup, sessionId])

  useEffect(() => {
    onEventRef.current = onEvent
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

  return {
    isConnected, error,
    sendAudioChunk, confirmIntent, dismissIntent, notifyAudioEnd, reconnect,
  }
}
