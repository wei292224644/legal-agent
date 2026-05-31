import { Sparkles } from 'lucide-react'
import type { Insight } from '@/types'

export type InsightCardProps = { insight: Insight }

export default function InsightCard({ insight }: InsightCardProps) {
  return (
    <div className="py-4 border-t border-border-color first:border-t-0">
      <div className="flex items-center gap-2 mb-2">
        <Sparkles className="w-3 h-3 text-accent" />
        <span className="text-xs font-medium text-accent">实时洞察</span>
      </div>
      <p className="text-sm text-ink-secondary leading-relaxed whitespace-pre-wrap">
        {insight.text}
      </p>
    </div>
  )
}
