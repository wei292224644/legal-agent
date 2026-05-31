import { BookOpen, ShieldAlert, FileText, Brain, type LucideIcon } from 'lucide-react'
import type { Insight } from '@/types'

const categoryConfig: Record<
  Insight['category'],
  { label: string; icon: LucideIcon; dot: string; text: string }
> = {
  law_citation: {
    label: '法规引用',
    icon: BookOpen,
    dot: 'bg-accent',
    text: 'text-accent',
  },
  risk_warning: {
    label: '风险提示',
    icon: ShieldAlert,
    dot: 'bg-danger',
    text: 'text-danger',
  },
  contract_clause: {
    label: '合同条款',
    icon: FileText,
    dot: 'bg-contract',
    text: 'text-contract',
  },
  behavior_analysis: {
    label: '行为分析',
    icon: Brain,
    dot: 'bg-success',
    text: 'text-success',
  },
};

export type InsightCardProps = {
  insight: Insight;
};

export default function InsightCard({ insight }: InsightCardProps) {
  const cfg = categoryConfig[insight.category];
  const Icon = cfg.icon;

  return (
    <div className="py-4 border-t border-border-color first:border-t-0">
      <div className="flex items-center gap-2 mb-2">
        <span className={`w-1.5 h-1.5 rounded-full ${cfg.dot}`} />
        <span className={`text-xs font-medium ${cfg.text}`}>
          <Icon className="w-3 h-3 inline mr-1" />
          {cfg.label}
        </span>
        {insight.riskLevel && (
          <span className="text-xs font-mono tracking-wide text-danger">
            {insight.riskLevel === 'high' ? '高' : insight.riskLevel === 'medium' ? '中' : '低'}
          </span>
        )}
      </div>
      <h3 className="text-sm font-semibold text-ink-primary mb-1">{insight.title}</h3>
      <p className="text-sm text-ink-secondary leading-relaxed">{insight.content}</p>
      {insight.citation && (
        <p className="text-xs font-mono tracking-wide text-accent/85 mt-2">
          {insight.citation}
        </p>
      )}
    </div>
  );
}
