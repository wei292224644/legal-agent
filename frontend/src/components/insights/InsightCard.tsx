import { Sparkles } from 'lucide-react'
import type { Insight } from '@/types'
import MarkdownText from './MarkdownText'

export type InsightCardProps = { insight: Insight }

/** 去掉 AI 可能自发加上的"快答"前缀（prompt 兜底）。 */
function stripQuickReply(text: string): string {
  return text.replace(/^\*{0,2}快答\*{0,2}[：:]\s*/u, '')
}

export default function InsightCard({ insight }: InsightCardProps) {
  return (
    <div className="py-4 border-t border-border-color first:border-t-0">
      <div className="flex items-center gap-2 mb-2">
        <Sparkles className="w-3 h-3 text-accent" />
        <span className="text-xs font-medium text-accent">实时洞察</span>
      </div>
      <MarkdownText>{stripQuickReply(insight.text)}</MarkdownText>
      <span className="text-[10px] text-ink-muted font-mono mt-2 block">
        来源: {insight.uttId}
      </span>
    </div>
  )
}
