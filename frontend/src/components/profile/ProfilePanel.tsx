import { User, Heart, FileText, ShieldAlert, CheckCircle2 } from 'lucide-react'
import { ScrollArea } from '@/components/ui/scroll-area'
import type { Profile, ProfileCategory, ProfileEntryItem } from '@/types'

export type ProfilePanelProps = {
  profile: Profile | null;
  compact?: boolean;
};

const CATEGORY_LABELS: Record<ProfileCategory, string> = {
  basic_info: '基本信息',
  emotion: '情绪状态',
  risk: '风险暴露',
  claim: '关键主张',
  fact: '已确认事实',
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function EmptyModule({ label, icon: Icon }: { label: string; icon: React.ElementType }) {
  return (
    <div className="py-3 px-1">
      <div className="flex items-center gap-2 mb-2">
        <Icon className="w-3 h-3 text-ink-muted" />
        <span className="text-xs font-mono tracking-wide text-ink-muted uppercase">{label}</span>
      </div>
      <div className="h-8 rounded bg-bg-tertiary/50 animate-pulse" />
    </div>
  );
}

function EntryList({ entries }: { entries: ProfileEntryItem[] }) {
  if (entries.length === 0) {
    return <p className="text-xs text-ink-muted">暂无数据</p>
  }
  return (
    <div className="space-y-1.5">
      {entries.map((e, i) => (
        <div key={i} className="flex items-start gap-2">
          <span className="w-1 h-1 rounded-full mt-1.5 shrink-0 bg-ink-muted" />
          <div className="min-w-0">
            <span className="text-xs text-ink-primary leading-relaxed">{e.key}: {e.value}</span>
            {(e.timestamp != null || e.sourceUttId) && (
              <span className="block text-[10px] text-ink-muted font-mono mt-0.5">
                {e.timestamp != null ? formatTime(e.timestamp) : ''}
                {e.sourceUttId ? ` · 来源: ${e.sourceUttId}` : ''}
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

function KeyClaims({ profile }: { profile: Profile }) {
  return (
    <div>
      <div className="flex items-center gap-2 mb-2">
        <FileText className="w-3 h-3 text-ink-muted" />
        <span className="text-xs font-mono tracking-wide text-ink-muted uppercase">关键主张</span>
      </div>
      {profile.claims.length === 0 ? (
        <p className="text-xs text-ink-muted">暂无数据</p>
      ) : (
        <div className="space-y-1.5">
          {profile.claims.map((claim, i) => (
            <div key={i} className="flex items-start gap-2">
              <span
                className={`w-1 h-1 rounded-full mt-1.5 shrink-0 ${
                  claim.variant === 'danger' ? 'bg-danger' : 'bg-accent'
                }`}
              />
              <span className="text-xs text-ink-primary leading-relaxed">{claim.text}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ConfirmedFacts({ profile }: { profile: Profile }) {
  return (
    <div>
      <div className="flex items-center gap-2 mb-2">
        <CheckCircle2 className="w-3 h-3 text-ink-muted" />
        <span className="text-xs font-mono tracking-wide text-ink-muted uppercase">已确认事实</span>
      </div>
      {profile.facts.length === 0 ? (
        <p className="text-xs text-ink-muted">暂无数据</p>
      ) : (
        <div className="space-y-1.5">
          {profile.facts.map((fact, i) => (
            <div key={i} className="flex items-start gap-2">
              <CheckCircle2 className="w-3 h-3 mt-0.5 shrink-0 text-success" />
              <span className="text-xs text-ink-primary leading-relaxed">{fact.text}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function ProfilePanel({ profile, compact }: ProfilePanelProps) {
  if (!profile) {
    return (
      <div className="w-full h-full flex flex-col">
        <div className="px-5 h-10 shrink-0 flex items-center border-b border-border-color">
          <span className="text-xs font-semibold text-ink-primary">当事人画像</span>
        </div>
        <ScrollArea className="flex-1 px-5 py-4">
          <div className="space-y-4">
            <EmptyModule label="基本信息" icon={User} />
            <EmptyModule label="情绪状态" icon={Heart} />
            <EmptyModule label="关键主张" icon={FileText} />
            <EmptyModule label="风险暴露" icon={ShieldAlert} />
            <EmptyModule label="已确认事实" icon={CheckCircle2} />
          </div>
        </ScrollArea>
      </div>
    );
  }

  const categoryEntries = (cat: ProfileCategory) =>
    profile.entries.filter((e) => e.category === cat).reverse()

  if (compact) {
    const emotionEntries = categoryEntries('emotion')
    return (
      <div className="p-4 rounded-lg bg-bg-secondary border border-border-color">
        <div className="flex items-center justify-between mb-3">
          <span className="text-xs font-semibold text-ink-primary">当事人画像</span>
        </div>
        <div className="flex items-center gap-3 mb-2">
          <div className="flex-1">
            <div className="text-xs text-ink-muted mb-1">情绪</div>
            {profile.emotion ? (
              <div className="flex items-center gap-1.5">
                <div className="flex-1 h-1 rounded-full overflow-hidden bg-bg-tertiary">
                  <div
                    className="h-full rounded-full bg-success"
                    style={{ width: `${profile.emotion.score}%` }}
                  />
                </div>
                <span className="text-xs text-success">{profile.emotion.label}</span>
              </div>
            ) : emotionEntries.length > 0 ? (
              <span className="text-xs text-accent">{emotionEntries[emotionEntries.length - 1].value}</span>
            ) : (
              <span className="text-xs text-ink-muted">分析中…</span>
            )}
          </div>
          <div className="flex-1">
            <div className="text-xs text-ink-muted mb-1">案件</div>
            <span className="text-xs text-ink-primary">{profile.caseType || '—'}</span>
          </div>
        </div>
        <div className="flex items-center gap-1.5 flex-wrap">
          {profile.claims.slice(0, 3).map((claim, i) => (
            <span
              key={i}
              className={`text-xs px-2 py-0.5 rounded ${
                claim.variant === 'danger'
                  ? 'bg-danger/10 text-danger'
                  : 'bg-accent-muted text-accent'
              }`}
            >
              {claim.text.length > 8 ? claim.text.slice(0, 8) + '…' : claim.text}
            </span>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="w-full h-full flex flex-col">
      <div className="px-5 h-10 shrink-0 flex items-center border-b border-border-color">
        <span className="text-xs font-semibold text-ink-primary">当事人画像</span>
      </div>
      <ScrollArea className="flex-1 px-5 py-4">
        <div className="space-y-5">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <User className="w-3 h-3 text-ink-muted" />
              <span className="text-xs font-mono tracking-wide text-ink-muted uppercase">基本信息</span>
            </div>
            <EntryList entries={categoryEntries('basic_info')} />
          </div>

          <div>
            <div className="flex items-center gap-2 mb-2">
              <Heart className="w-3 h-3 text-ink-muted" />
              <span className="text-xs font-mono tracking-wide text-ink-muted uppercase">情绪状态</span>
            </div>
            <EntryList entries={categoryEntries('emotion')} />
          </div>

          <KeyClaims profile={profile} />

          <div>
            <div className="flex items-center gap-2 mb-2">
              <ShieldAlert className="w-3 h-3 text-ink-muted" />
              <span className="text-xs font-mono tracking-wide text-ink-muted uppercase">风险暴露</span>
            </div>
            {profile.risks.length === 0 ? (
              <p className="text-xs text-ink-muted">暂无数据</p>
            ) : (
              <div className="space-y-1.5">
                {profile.risks.map((risk, i) => (
                  <div key={i} className="flex items-start gap-2">
                    <span className={`w-1.5 h-1.5 rounded-full mt-1.5 shrink-0 ${
                      risk.level === 'high' ? 'bg-danger' : risk.level === 'medium' ? 'bg-warning' : 'bg-ink-muted'
                    }`} />
                    <span className="text-xs text-ink-primary leading-relaxed">{risk.description}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          <ConfirmedFacts profile={profile} />
        </div>
      </ScrollArea>
    </div>
  );
}
