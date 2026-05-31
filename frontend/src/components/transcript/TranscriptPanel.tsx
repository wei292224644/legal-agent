import { useCallback, useEffect, useRef } from 'react'
import { PanelRightClose, PanelRightOpen, MessageSquare } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { TranscriptLine } from '@/types'

export type TranscriptPanelProps = {
  transcripts: TranscriptLine[];
  isOpen: boolean;
  onToggle: () => void;
};

const speakerLabel: Record<TranscriptLine['speaker'], { label: string; color: string }> = {
  lawyer: { label: '律', color: 'text-accent' },
  client: { label: '当', color: 'text-ink-muted' },
  uncertain: { label: '未知', color: 'text-ink-muted' },
};

const SCROLL_BOTTOM_THRESHOLD = 40

export default function TranscriptPanel({ transcripts, isOpen, onToggle }: TranscriptPanelProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const isAtBottomRef = useRef(true)

  const handleScroll = useCallback(() => {
    const el = scrollRef.current
    if (!el) return
    isAtBottomRef.current =
      el.scrollHeight - el.scrollTop - el.clientHeight < SCROLL_BOTTOM_THRESHOLD
  }, [])

  useEffect(() => {
    if (isAtBottomRef.current && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [transcripts])
  if (!isOpen) {
    return (
      <div className="w-10 shrink-0 flex flex-col items-center py-4 border-l border-border-color bg-bg-secondary">
        <Button variant="ghost" size="icon" onClick={onToggle} className="h-8 w-8 text-ink-muted hover:text-ink-primary" title="展开转写面板">
          <PanelRightOpen className="w-4 h-4" />
        </Button>
      </div>
    );
  }

  return (
    <div className="w-[280px] shrink-0 flex flex-col bg-bg-secondary border-l border-border-color">
      <div className="px-5 h-10 shrink-0 flex items-center justify-between border-b border-border-color">
        <span className="text-xs font-semibold text-ink-muted">转写参考</span>
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono text-ink-muted">{transcripts.length} 条</span>
          <Button variant="ghost" size="icon" onClick={onToggle} className="h-8 w-8 text-ink-muted hover:text-ink-primary" title="收起转写面板">
            <PanelRightClose className="w-3.5 h-3.5" />
          </Button>
        </div>
      </div>
      <div ref={scrollRef} onScroll={handleScroll} className="flex-1 overflow-auto px-5 py-4">
        {transcripts.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-ink-muted gap-2">
            <MessageSquare className="w-6 h-6 opacity-20" />
            <p className="text-xs">开始说话后，转写文本将实时显示</p>
            <p className="text-xs text-ink-muted">系统会自动区分律师与当事人的发言</p>
          </div>
        ) : (
          <div className="space-y-4">
            {transcripts.map((line) => {
              const spk = speakerLabel[line.speaker];
              return (
                <div key={line.id} className="flex gap-2">
                  <span className={`text-xs font-mono shrink-0 ${spk.color}`}>{spk.label}</span>
                  <p className="text-xs text-ink-secondary leading-relaxed">{line.text}</p>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
