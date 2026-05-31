import { useState, useEffect, useRef, memo } from 'react'
import { Activity, CheckCircle2, ChevronUp, ChevronDown } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import type { Suggestion } from '@/types'
import MarkdownText from './MarkdownText'

const PENDING_TIMEOUT_SECONDS = 30

export type SuggestionCardProps = {
  suggestion: Suggestion
  onConfirm: (requestId: string) => void
  onDismiss: (requestId: string) => void
}

function PendingCard({
  suggestion,
  onConfirm,
  onDismiss,
}: {
  suggestion: Suggestion
  onConfirm: (requestId: string) => void
  onDismiss: (requestId: string) => void
}) {
  const [timeLeft, setTimeLeft] = useState(PENDING_TIMEOUT_SECONDS)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    intervalRef.current = setInterval(() => {
      setTimeLeft((prev) => {
        if (prev <= 1) {
          if (intervalRef.current) clearInterval(intervalRef.current)
          return 0
        }
        return prev - 1
      })
    }, 1000)
    const timeout = setTimeout(() => {
      onDismiss(suggestion.requestId)
    }, PENDING_TIMEOUT_SECONDS * 1000)
    return () => {
      clearTimeout(timeout)
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [suggestion.requestId, onDismiss])

  const progress = (timeLeft / PENDING_TIMEOUT_SECONDS) * 100

  return (
    <div className="p-4 rounded-lg bg-accent-muted border border-accent/18">
      <div className="flex items-center gap-2 mb-2">
        <span className="w-1.5 h-1.5 rounded-full bg-accent" />
        <span className="text-xs font-medium text-accent">可分析意图</span>
      </div>
      <p className="text-sm text-ink-secondary leading-relaxed mb-3">
        {suggestion.rationale || suggestion.topic || '检测到可分析意图'}
      </p>
      <div className="flex items-center gap-2 mb-3">
        <div className="flex-1 h-1 rounded-full overflow-hidden bg-bg-tertiary">
          <div
            className="h-full rounded-full bg-accent transition-all duration-1000 ease-linear"
            style={{ width: `${progress}%` }}
          />
        </div>
        <span className="text-xs font-mono text-ink-muted w-10 text-right">{timeLeft}s</span>
      </div>
      <div className="flex gap-2">
        <Button
          size="sm"
          onClick={() => onConfirm(suggestion.requestId)}
          className="h-9 px-4 text-xs bg-accent text-bg-primary hover:bg-accent-hover"
        >
          生成深度分析
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={() => onDismiss(suggestion.requestId)}
          className="h-9 px-4 text-xs border-border-color text-ink-secondary hover:text-ink-primary bg-transparent"
        >
          忽略
        </Button>
      </div>
    </div>
  )
}

function RunningCard({ suggestion }: { suggestion: Suggestion }) {
  const progress = suggestion.progress ?? 0
  return (
    <div className="p-4 rounded-lg bg-accent-muted/50 border border-accent/10">
      <div className="flex items-center gap-2 mb-3">
        <Activity className="w-3 h-3 text-accent animate-pulse" />
        <span className="text-xs font-medium text-accent motion-safe:animate-pulse">
          分析中…{suggestion.topic ? ` · ${suggestion.topic}` : ''}
        </span>
      </div>
      <div className="h-1 rounded-full overflow-hidden bg-bg-tertiary">
        <div
          className="h-full rounded-full bg-accent transition-all duration-500"
          style={{ width: `${progress}%` }}
        />
      </div>
    </div>
  )
}

function stripMarkdown(text: string): string {
  return text
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/__(.+?)__/g, '$1')
    .replace(/\*(.+?)\*/g, '$1')
    .replace(/_(.+?)_/g, '$1')
    .replace(/`{1,3}(.+?)`{1,3}/gs, '$1')
    .replace(/\[(.+?)\]\(.+?\)/g, '$1')
    .replace(/^\s*[-*+]\s+/gm, '')
    .replace(/^\s*\d+\.\s+/gm, '')
    .replace(/\n+/g, ' ')
    .replace(/---/g, '')
    .trim()
}

function ReadyCard({ suggestion }: { suggestion: Suggestion }) {
  const [expanded, setExpanded] = useState(false)

  const preview = suggestion.text
    ? stripMarkdown(suggestion.text).slice(0, 120) + (suggestion.text.length > 120 ? '...' : '')
    : ''

  return (
    <div className="p-4 rounded-lg bg-bg-secondary border border-border-color">
      <Collapsible open={expanded} onOpenChange={setExpanded}>
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0 flex-1">
            <CheckCircle2 className="w-3 h-3 text-success shrink-0" />
            <span className="text-xs font-medium text-success truncate">
              {suggestion.topic || '深度分析'}
            </span>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setExpanded((v) => !v)}
            className="flex items-center gap-1 text-xs h-auto py-1 px-2 shrink-0 text-ink-secondary hover:text-ink-primary"
          >
            {expanded ? (
              <>
                <ChevronUp className="w-3 h-3" /> 收起
              </>
            ) : (
              <>
                <ChevronDown className="w-3 h-3" /> 展开
              </>
            )}
          </Button>
        </div>
        {!expanded && preview && (
          <p className="text-xs text-ink-muted line-clamp-2 mt-2">
            {preview}
          </p>
        )}
        <CollapsibleContent>
          <div className="mt-3">
            <MarkdownText>{suggestion.text ?? '分析结果为空'}</MarkdownText>
          </div>
        </CollapsibleContent>
      </Collapsible>
    </div>
  )
}

function SuggestionCardInner({ suggestion, onConfirm, onDismiss }: SuggestionCardProps) {
  if (suggestion.status === 'pending') {
    return <PendingCard suggestion={suggestion} onConfirm={onConfirm} onDismiss={onDismiss} />
  }
  if (suggestion.status === 'running') {
    return <RunningCard suggestion={suggestion} />
  }
  return <ReadyCard suggestion={suggestion} />
}

export default memo(SuggestionCardInner)
