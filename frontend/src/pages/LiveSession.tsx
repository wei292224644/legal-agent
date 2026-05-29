import { useState, useCallback, memo } from 'react'
import { useWebSocket, type SuggestionData } from '@/hooks/useWebSocket'
import { Card } from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Badge } from '@/components/ui/badge'
import AudioControls from '@/components/AudioControls'

type TranscriptLine = { speaker: string; text: string }
type Analysis = {
  id: string
  category: 'statute' | 'contract' | 'risk'
  title: string
  content: string
  citation?: string
  level?: string
}

type Suggestion =
  | { kind: 'pending'; requestId: string; intentType: string; lawDomain: string | null }
  | { kind: 'ready'; id: string; requestId?: string; text: string; intentType: string }

type TranscriptData = { text: string; speaker: string; is_final: boolean }
type AnalysisData = { category: string; title: string; content: string; citation?: string; level?: string }

const categoryConfig = {
  statute: { label: '法规引用', emoji: '📋', border: 'border-amber-500/30', bg: 'bg-amber-500/5' },
  contract: { label: '合同条款', emoji: '📝', border: 'border-blue-400/30', bg: 'bg-blue-400/5' },
  risk: { label: '风险提示', emoji: '⚠️', border: 'border-red-400/40', bg: 'bg-red-400/5' },
} as const

const riskLevelClass = {
  '高': 'border-red-500/50 text-red-400',
  '中': 'border-amber-500/50 text-amber-400',
  '低': 'border-zinc-500/50 text-zinc-400',
} as const

const riskLevelEmoji = { '高': '🔴', '中': '🟡', '低': '🟢' } as const

// Hoisted static JSX (rendering-hoist-jsx)
const emptyTranscript = (
  <div className="flex items-center justify-center h-full text-zinc-600 font-serif italic">
    开始说话，转写文本将实时显示在这里...
  </div>
)

const emptyAnalysis = (
  <div className="flex items-center justify-center h-full text-zinc-600 font-serif italic text-sm">
    AI 正在实时分析对话内容...
  </div>
)

// Memoized sub-components (rerender-memo)
const TranscriptItem = memo(function TranscriptItem({ line }: { line: TranscriptLine }) {
  const isLawyer = line.speaker === '律师'
  return (
    <div className="flex gap-3">
      <span className={`shrink-0 text-xs font-mono mt-1 px-2 py-0.5 rounded ${
        isLawyer
          ? 'bg-amber-500/10 text-amber-300 border border-amber-500/20'
          : 'bg-zinc-800 text-zinc-400 border border-zinc-700'
      }`}>
        {isLawyer ? '🧑‍⚖️' : '👤'} {line.speaker}
      </span>
      <p className="text-zinc-300 leading-relaxed">{line.text}</p>
    </div>
  )
})

const AnalysisCard = memo(function AnalysisCard({ a }: { a: Analysis }) {
  const cfg = categoryConfig[a.category]
  return (
    <Card className={`p-4 ${cfg.bg} ${cfg.border} border transition-all duration-300`}>
      <div className="flex items-center gap-2 mb-2">
        <Badge variant="outline" className={`text-xs ${cfg.border} text-zinc-300`}>
          {cfg.emoji} {cfg.label}
        </Badge>
        {a.category === 'risk' && a.level && (
          <Badge variant="outline" className={`text-xs ${riskLevelClass[a.level as keyof typeof riskLevelClass] ?? ''}`}>
            {riskLevelEmoji[a.level as keyof typeof riskLevelEmoji] ?? ''} {a.level}
          </Badge>
        )}
      </div>
      <h3 className="font-serif text-sm font-medium text-zinc-200 mb-1">{a.title}</h3>
      <p className="text-xs text-zinc-400 leading-relaxed">{a.content}</p>
      {a.citation && (
        <p className="text-xs text-amber-500/70 mt-2 font-mono">{a.citation}</p>
      )}
    </Card>
  )
})

const SuggestionCard = memo(function SuggestionCard({
  s,
  onConfirm,
  onDismiss,
}: {
  s: Suggestion
  onConfirm: (requestId: string) => void
  onDismiss: (requestId: string) => void
}) {
  if (s.kind === 'pending') {
    return (
      <Card className="p-4 bg-amber-500/5 border-amber-500/30 border transition-all duration-300">
        <Badge variant="outline" className="text-xs border-amber-500/30 text-amber-300 mb-2">
          💡 需要深度分析？
        </Badge>
        <p className="text-xs text-zinc-400 leading-relaxed mb-3">
          {s.intentType}{s.lawDomain ? ` · ${s.lawDomain}` : ''}
        </p>
        <div className="flex gap-2">
          <Button size="sm" className="bg-amber-600 hover:bg-amber-500 text-zinc-900" onClick={() => onConfirm(s.requestId)}>
            确认分析
          </Button>
          <Button size="sm" variant="outline" className="border-zinc-700 text-zinc-400" onClick={() => onDismiss(s.requestId)}>
            忽略
          </Button>
        </div>
      </Card>
    )
  }
  return (
    <Card className="p-4 bg-blue-400/5 border-blue-400/30 border transition-all duration-300">
      <Badge variant="outline" className="text-xs border-blue-400/30 text-zinc-300 mb-2">
        ✅ {s.intentType}
      </Badge>
      <p className="text-xs text-zinc-300 leading-relaxed whitespace-pre-wrap">{s.text}</p>
    </Card>
  )
})

export default function LiveSession() {
  const [transcript, setTranscript] = useState<TranscriptLine[]>([])
  const [analyses, setAnalyses] = useState<Analysis[]>([])
  const [suggestions, setSuggestions] = useState<Suggestion[]>([])
  const [status, setStatus] = useState('待连接...')

  const onTranscript = useCallback((data: TranscriptData) => {
    setTranscript(prev => [...prev, { speaker: data.speaker, text: data.text }])
    setStatus('正在听...')
  }, [])

  const onAnalysis = useCallback((data: AnalysisData) => {
    setAnalyses(prev => [{
      id: crypto.randomUUID(),
      category: data.category as Analysis['category'],
      title: data.title,
      content: data.content,
      citation: data.citation,
      level: data.level,
    }, ...prev])
  }, [])

  const onSuggestion = useCallback((data: SuggestionData) => {
    setSuggestions(prev => {
      if (data.type === 'suggestion.pending') {
        const pending: Suggestion = {
          kind: 'pending',
          requestId: data.meta.request_id ?? '',
          intentType: data.meta.intent_type,
          lawDomain: data.meta.law_domain,
        }
        return [pending, ...prev]
      }
      const ready: Suggestion = {
        kind: 'ready',
        id: crypto.randomUUID(),
        requestId: data.meta.request_id,
        text: data.text ?? '',
        intentType: data.meta.intent_type,
      }
      // 确认后的 ready 带 request_id：替换对应 pending 卡片；否则（simple 快速回答）直接插入
      if (data.meta.request_id) {
        return prev.map(s => (s.kind === 'pending' && s.requestId === data.meta.request_id ? ready : s))
      }
      return [ready, ...prev]
    })
  }, [])

  const { isConnected, sendAudioChunk, confirmIntent, dismissIntent } = useWebSocket(
    'ws://localhost:8000/ws/demo-session',
    { onTranscript, onAnalysis, onSuggestion }
  )

  const handleDismiss = useCallback((requestId: string) => {
    dismissIntent(requestId)
    setSuggestions(prev => prev.filter(s => !(s.kind === 'pending' && s.requestId === requestId)))
  }, [dismissIntent])

  return (
    <div className="flex h-screen bg-zinc-950 text-zinc-200">
      {/* 左侧：转写区域 */}
      <div className="flex-1 flex flex-col border-r border-zinc-800">
        <header className="flex items-center justify-between px-6 py-4 border-b border-zinc-800">
          <div>
            <h1 className="font-serif text-xl tracking-wide text-amber-200/90">实时会谈</h1>
            <p className="text-xs text-zinc-500 mt-0.5 font-mono">
              {isConnected ? '🟢 已连接' : '🟡 连接中...'} · {status}
            </p>
          </div>
          <AudioControls onChunk={sendAudioChunk} />
        </header>
        <ScrollArea className="flex-1 px-6 py-4">
          {transcript.length === 0
            ? emptyTranscript
            : (
              <div className="space-y-4">
                {transcript.map((line, i) => (
                  <TranscriptItem key={i} line={line} />
                ))}
              </div>
            )}
        </ScrollArea>
      </div>

      {/* 右侧：AI 分析侧边栏 */}
      <aside className="w-[380px] flex flex-col bg-zinc-900/50">
        <header className="px-6 py-4 border-b border-zinc-800">
          <h2 className="font-serif text-lg tracking-wide text-amber-200/90">AI 分析</h2>
          <p className="text-xs text-zinc-500 mt-0.5 font-mono">{suggestions.length + analyses.length} 条分析结果</p>
        </header>
        <ScrollArea className="flex-1 px-4 py-4">
          {suggestions.length === 0 && analyses.length === 0
            ? emptyAnalysis
            : (
              <div className="space-y-3">
                {suggestions.map((s) => (
                  <SuggestionCard
                    key={s.kind === 'pending' ? s.requestId : s.id}
                    s={s}
                    onConfirm={confirmIntent}
                    onDismiss={handleDismiss}
                  />
                ))}
                {analyses.map((a) => <AnalysisCard key={a.id} a={a} />)}
              </div>
            )}
        </ScrollArea>
      </aside>
    </div>
  )
}
