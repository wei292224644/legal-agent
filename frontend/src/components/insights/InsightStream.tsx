import { Activity } from 'lucide-react'
import { ScrollArea } from '@/components/ui/scroll-area'
import InsightCard from './InsightCard'
import SuggestionCard from './SuggestionCard'
import type { Insight, Suggestion } from '@/types'

export type InsightStreamProps = {
  insights: Insight[]
  suggestions: Suggestion[]
  onConfirm: (requestId: string) => void
  onDismiss: (requestId: string) => void
}

export default function InsightStream({
  insights,
  suggestions,
  onConfirm,
  onDismiss,
}: InsightStreamProps) {
  const hasContent = insights.length > 0 || suggestions.length > 0

  return (
    <div className="flex-1 flex flex-col min-w-0">
      <div className="px-6 h-10 shrink-0 flex items-center justify-between border-b border-border-color">
        <span className="text-xs font-semibold text-ink-primary">实时洞察</span>
        <span className="text-xs font-mono text-ink-muted">
          {suggestions.length + insights.length} 条
        </span>
      </div>
      <ScrollArea className="flex-1 px-6 py-5">
        {!hasContent ? (
          <div className="flex flex-col items-center justify-center h-full text-ink-muted gap-2 min-h-[200px]">
            <Activity className="w-8 h-8 opacity-20" />
            <p className="text-sm">准备就绪，等待对话开始</p>
            <p className="text-xs text-ink-muted">点击上方「开始录音」或「上传音频」开始会谈，AI 分析结果将实时显示在此处</p>
          </div>
        ) : (
          <div>
            {suggestions.map((s) => (
              <SuggestionCard
                key={s.requestId}
                suggestion={s}
                onConfirm={onConfirm}
                onDismiss={onDismiss}
              />
            ))}
            {insights.map((insight) => (
              <InsightCard key={insight.id} insight={insight} />
            ))}
          </div>
        )}
      </ScrollArea>
    </div>
  )
}
