import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { SessionProvider } from '@/context/SessionContext'
import { useSession } from '@/hooks/useSession'
import { fetchHistory } from '@/api/sessions'
import { useWebSocket, type SuggestionData } from '@/hooks/useWebSocket'
import DesktopLayout from '@/components/layout/DesktopLayout'
import MobileLayout from '@/components/layout/MobileLayout'
import PortraitLock from '@/components/layout/PortraitLock'
import InsightStream from '@/components/insights/InsightStream'
import TranscriptPanel from '@/components/transcript/TranscriptPanel'
import AudioControls from '@/components/AudioControls'
import { entriesToProfile, type Insight, type ProfileEntryItem, type TranscriptLine } from '@/types'

function ConnectionIndicator() {
  const { state } = useSession()
  const { connectionStatus } = state

  const config = {
    connecting: { dot: 'bg-primary', text: 'text-primary', label: '连接中…' },
    connected: { dot: 'bg-success', text: 'text-success', label: '已连接' },
    disconnected: { dot: 'bg-danger', text: 'text-danger', label: '离线' },
    reconnecting: { dot: 'bg-warning', text: 'text-warning', label: '重连中…' },
  }

  const cfg = config[connectionStatus]

  return (
    <div className="flex items-center gap-2 text-xs font-mono uppercase tracking-wide">
      <span className={`w-2 h-2 rounded-full ${cfg.dot}`} />
      <span className={cfg.text}>{cfg.label}</span>
    </div>
  )
}
function DisconnectBanner({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="flex items-center justify-between px-4 py-2 bg-danger/10 border-b border-danger/20 text-sm">
      <span className="text-danger">连接已断开，实时转写和分析已暂停</span>
      <button
        onClick={onRetry}
        className="px-3 py-1 text-xs font-medium rounded bg-danger text-white hover:bg-danger/90 transition-colors"
      >
        重新连接
      </button>
    </div>
  )
}

function LiveSessionInner() {
  const { id: sessionId } = useParams<{ id: string }>()
  const {
    state,
    addInsight,
    addSuggestion,
    updateSuggestion,
    dismissSuggestion,
    addTranscript,
    setConnectionStatus,
    setSessionId,
    setProfile,
    hydrate,
    toggleTranscriptPanel,
  } = useSession()

  const [hydrated, setHydrated] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const disconnectTimeRef = useRef<number | null>(null)

  useEffect(() => {
    if (sessionId) setSessionId(sessionId)
  }, [sessionId, setSessionId])

  // Hydrate from history on mount
  useEffect(() => {
    if (!sessionId) {
      Promise.resolve().then(() => setHydrated(true))
      return
    }
    let cancelled = false
    fetchHistory(sessionId)
      .then((h) => {
        if (cancelled) {
          setHydrated(true)
          return
        }
        if (!h) {
          setHydrated(true)
          return
        }
        const transcripts: TranscriptLine[] = h.utterances.map((u) => ({
          id: u.id,
          speaker: (u.speaker ?? 'uncertain') as TranscriptLine['speaker'],
          text: u.text,
          timestamp: u.t_start,
        }))

        const suggestions = h.suggestions
          .filter((s) => s.status !== 'expired' && s.status !== 'dismissed')
          .map((s) => ({
            id: s.id,
            requestId: s.request_id ?? `req-${s.id}`,
            status: s.status as 'pending' | 'running' | 'ready',
            topic: s.preview_topic ?? '',
            rationale: s.preview_rationale ?? '',
            text: s.text ?? null,
            createdAt: s.created_at,
          }))

        const profileEntries: ProfileEntryItem[] = (h.profile_entries ?? []).map(
          (e) => ({
            key: e.key,
            value: e.value,
            subject: e.subject,
          })
        )

        hydrate({
          transcripts,
          suggestions,
          profile: profileEntries.length > 0 ? entriesToProfile(profileEntries) : null,
        })
        setHydrated(true)
      })
      .catch(() => setHydrated(true))

    return () => {
      cancelled = true
    }
  }, [sessionId, hydrate])

  // Backfill history after reconnect
  const backfillHistory = useCallback(
    async (sid: string) => {
      setSyncing(true)
      try {
        const h = await fetchHistory(sid)
        if (!h) return
        const existingIds = new Set(state.transcripts.map((t) => t.id))
        const newTranscripts: TranscriptLine[] = h.utterances
          .filter((u) => !existingIds.has(u.id))
          .map((u) => ({
            id: u.id,
            speaker: (u.speaker ?? 'uncertain') as TranscriptLine['speaker'],
            text: u.text,
            timestamp: u.t_start,
          }))
        newTranscripts.forEach((t) => addTranscript(t))

        const existingSuggestionIds = new Set(state.suggestions.map((s) => s.id))
        const newSuggestions = h.suggestions
          .filter((s) => s.status !== 'expired' && s.status !== 'dismissed' && !existingSuggestionIds.has(s.id))
          .map((s) => ({
            id: s.id,
            requestId: s.request_id ?? `req-${s.id}`,
            status: s.status as 'pending' | 'running' | 'ready',
            topic: s.preview_topic ?? '',
            rationale: s.preview_rationale ?? '',
            text: s.text ?? null,
            createdAt: s.created_at,
          }))
        newSuggestions.forEach((s) => addSuggestion(s))

        const profileEntries: ProfileEntryItem[] = (h.profile_entries ?? []).map(
          (e) => ({
            key: e.key,
            value: e.value,
            subject: e.subject,
          })
        )
        if (profileEntries.length > 0) {
          setProfile(entriesToProfile(profileEntries))
        }
      } catch {
        // ignore backfill errors
      } finally {
        setSyncing(false)
      }
    },
    [state.transcripts, state.suggestions, addTranscript, addSuggestion, setProfile]
  )

  const onTranscript = useCallback(
    (data: { text: string; speaker: string }) => {
      addTranscript({
        id: crypto.randomUUID(),
        speaker: (data.speaker as TranscriptLine['speaker']) ?? 'uncertain',
        text: data.text,
        timestamp: Date.now(),
      })
    },
    [addTranscript]
  )

  const onAnalysis = useCallback(
    (data: { category: string; title: string; content: string; citation?: string }) => {
      const insight: Insight = {
        id: crypto.randomUUID(),
        category: data.category as Insight['category'],
        title: data.title,
        content: data.content,
        citation: data.citation,
        createdAt: new Date().toISOString(),
      }
      addInsight(insight)
    },
    [addInsight]
  )

  const onSuggestion = useCallback(
    (data: SuggestionData) => {
      if (data.type === 'suggestion.pending') {
        addSuggestion({
          id: crypto.randomUUID(),
          requestId: data.meta.request_id ?? `req-${Date.now()}`,
          status: 'pending',
          topic: data.meta.preview?.topic ?? '',
          rationale: data.meta.preview?.rationale ?? '',
          text: null,
          createdAt: new Date().toISOString(),
        })
        return
      }
      if (data.type === 'suggestion.ready') {
        const rid = data.meta.request_id
        if (rid) {
          updateSuggestion(rid, {
            status: 'ready',
            text: data.text,
            topic: data.meta.preview?.topic ?? '',
          })
        }
      }
    },
    [addSuggestion, updateSuggestion]
  )

  const {
    isConnected,
    error: wsError,
    sendAudioChunk,
    confirmIntent,
    dismissIntent,
    notifyAudioEnd,
    reconnect,
  } = useWebSocket(hydrated ? (sessionId ?? '') : '', {
    onTranscript,
    onAnalysis,
    onSuggestion,
    onConfirmAck: ({ ok, request_id }) => {
      if (!ok) {
        dismissSuggestion(request_id)
      }
    },
    onProfileUpdate: (entries: ProfileEntryItem[]) => {
      const merged = [...(state.profile?.entries ?? []), ...entries]
      setProfile(entriesToProfile(merged))
    },
  })

  useEffect(() => {
    if (wsError) {
      if (!disconnectTimeRef.current) {
        disconnectTimeRef.current = Date.now()
      }
      setConnectionStatus('disconnected')
    } else if (isConnected) {
      if (disconnectTimeRef.current && sessionId) {
        backfillHistory(sessionId)
        disconnectTimeRef.current = null
      }
      setConnectionStatus('connected')
    } else {
      setConnectionStatus('connecting')
    }
  }, [isConnected, wsError, setConnectionStatus, sessionId, backfillHistory])

  const handleConfirm = useCallback(
    (requestId: string) => {
      confirmIntent(requestId)
      updateSuggestion(requestId, { status: 'running', progress: 0 })
    },
    [confirmIntent, updateSuggestion]
  )

  const handleDismiss = useCallback(
    (requestId: string) => {
      dismissIntent(requestId)
      dismissSuggestion(requestId)
    },
    [dismissIntent, dismissSuggestion]
  )

  const insightStreamNode = (
    <InsightStream
      insights={state.insights}
      suggestions={state.suggestions}
      onConfirm={handleConfirm}
      onDismiss={handleDismiss}
    />
  )

  const transcriptPanelNode = (
    <TranscriptPanel
      transcripts={state.transcripts}
      isOpen={state.isTranscriptPanelOpen}
      onToggle={toggleTranscriptPanel}
    />
  )

  const connectionIndicatorNode = <ConnectionIndicator />

  return (
    <>
      <PortraitLock />
      <div className="flex flex-col h-screen bg-background text-foreground">
      {/* Disconnect Banner */}
      {state.connectionStatus === 'disconnected' && <DisconnectBanner onRetry={reconnect} />}

      {/* Syncing Banner */}
      {syncing && (
        <div className="flex items-center justify-center px-4 py-1.5 bg-accent-muted border-b border-accent/15 text-xs text-accent">
          正在同步离线期间的对话记录…
        </div>
      )}

      {/* Desktop Header */}
      <header className="hidden md:flex items-center justify-between px-6 h-12 border-b border-border-color bg-bg-primary shrink-0">
        <div className="flex items-center gap-4">
          <h1 className="text-base font-semibold text-ink-primary tracking-tight">实时会谈</h1>
          {connectionIndicatorNode}
        </div>
        <AudioControls onChunk={sendAudioChunk} onAudioEnd={notifyAudioEnd} />
      </header>

      {/* Desktop Layout */}
      <DesktopLayout
        profile={state.profile}
        insightStream={insightStreamNode}
        transcriptPanel={transcriptPanelNode}
      />

      {/* Mobile Layout */}
      <MobileLayout
        profile={state.profile}
        insightStream={insightStreamNode}
        transcriptPanel={transcriptPanelNode}
        connectionStatus={connectionIndicatorNode}
        audioControls={<AudioControls onChunk={sendAudioChunk} onAudioEnd={notifyAudioEnd} />}
      />
    </div>
    </>
  )
}

export default function LiveSession() {
  return (
    <SessionProvider>
      <LiveSessionInner />
    </SessionProvider>
  )
}
