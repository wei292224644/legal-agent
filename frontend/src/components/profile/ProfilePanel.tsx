import { User, Heart, FileText, ShieldAlert, CheckCircle2 } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { Profile, ProfileCategory, ProfileEntryItem } from "@/types";

export type ProfilePanelProps = {
  profile: Profile | null;
  compact?: boolean;
};

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function MetaLine({
  timestamp,
  sourceUttId,
}: {
  timestamp?: number;
  sourceUttId?: string;
}) {
  if (timestamp == null && !sourceUttId) return null;
  return (
    <span className="block text-[10px] text-ink-muted font-mono mt-1">
      {timestamp != null ? formatTime(timestamp) : ""}
      {timestamp != null && sourceUttId ? " · " : ""}
      {sourceUttId ? `来源: ${sourceUttId.slice(0, 8)}…` : ""}
    </span>
  );
}

function SectionHeader({
  icon: Icon,
  label,
}: {
  icon: React.ElementType;
  label: string;
}) {
  return (
    <div className="flex items-center gap-2 mb-3">
      <Icon className="w-3 h-3 text-ink-muted" />
      <span className="text-xs font-mono tracking-wide text-ink-muted uppercase">
        {label}
      </span>
    </div>
  );
}

function ItemRow({
  dot,
  children,
}: {
  dot?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-start gap-3 rounded bg-bg-tertiary/20">
      {dot ?? (
        <span className="w-1 h-1 rounded-full mt-1.5 shrink-0 bg-ink-muted" />
      )}
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

function EmptyHint() {
  return <p className="text-xs text-ink-muted">暂无数据</p>;
}

function Section({
  children,
  first,
}: {
  children: React.ReactNode;
  first?: boolean;
}) {
  return (
    <div className={first ? undefined : "border-t border-border-color pt-4"}>
      {children}
    </div>
  );
}

function EmptyModule({
  label,
  icon: Icon,
}: {
  label: string;
  icon: React.ElementType;
}) {
  return (
    <div className="py-3 px-1">
      <div className="flex items-center gap-2 mb-2">
        <Icon className="w-3 h-3 text-ink-muted" />
        <span className="text-xs font-mono tracking-wide text-ink-muted uppercase">
          {label}
        </span>
      </div>
      <div className="h-8 rounded bg-bg-tertiary/50 animate-pulse" />
    </div>
  );
}

function EntryList({ entries }: { entries: ProfileEntryItem[] }) {
  if (entries.length === 0) {
    return <EmptyHint />;
  }
  return (
    <div className="flex flex-col gap-1">
      {entries.map((e, i) => (
        <ItemRow key={i}>
          <span className="text-xs text-ink-primary leading-relaxed">
            {e.key}: {e.value}
          </span>
          <MetaLine timestamp={e.timestamp} sourceUttId={e.sourceUttId} />
        </ItemRow>
      ))}
    </div>
  );
}

function KeyClaims({ profile }: { profile: Profile }) {
  return (
    <div>
      <SectionHeader icon={FileText} label="关键主张" />
      {profile.claims.length === 0 ? (
        <EmptyHint />
      ) : (
        <div className="flex flex-col gap-1">
          {profile.claims.map((claim, i) => (
            <ItemRow
              key={i}
              dot={
                <span
                  className={`w-1 h-1 rounded-full mt-1.5 shrink-0 ${
                    claim.variant === "danger" ? "bg-danger" : "bg-accent"
                  }`}
                />
              }
            >
              <span className="text-xs text-ink-primary leading-relaxed">
                {claim.text}
              </span>
              <MetaLine
                timestamp={claim.timestamp}
                sourceUttId={claim.sourceUttId}
              />
            </ItemRow>
          ))}
        </div>
      )}
    </div>
  );
}

function ConfirmedFacts({ profile }: { profile: Profile }) {
  return (
    <div>
      <SectionHeader icon={CheckCircle2} label="已确认事实" />
      {profile.facts.length === 0 ? (
        <EmptyHint />
      ) : (
        <div className="flex flex-col gap-1">
          {profile.facts.map((fact, i) => (
            <ItemRow
              key={i}
              dot={
                <CheckCircle2 className="w-3 h-3 mt-0.5 shrink-0 text-success" />
              }
            >
              <span className="text-xs text-ink-primary leading-relaxed">
                {fact.text}
              </span>
              <MetaLine
                timestamp={fact.timestamp}
                sourceUttId={fact.sourceUttId}
              />
            </ItemRow>
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
        <div className="px-4 sm:px-5 h-10 shrink-0 flex items-center border-b border-border-color">
          <span className="text-xs font-semibold text-ink-primary">
            当事人画像
          </span>
        </div>
        <ScrollArea className="flex-1 px-4 sm:px-5 py-4">
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
    profile.entries.filter((e) => e.category === cat);

  if (compact) {
    const emotionEntries = categoryEntries("emotion");
    return (
      <div className="p-4 rounded-lg bg-bg-secondary border border-border-color">
        <div className="flex items-center justify-between mb-3">
          <span className="text-xs font-semibold text-ink-primary">
            当事人画像
          </span>
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
                <span className="text-xs text-success">
                  {profile.emotion.label}
                </span>
              </div>
            ) : emotionEntries.length > 0 ? (
              <span className="text-xs text-accent">
                {emotionEntries[0].value}
              </span>
            ) : (
              <span className="text-xs text-ink-muted">分析中…</span>
            )}
          </div>
          <div className="flex-1">
            <div className="text-xs text-ink-muted mb-1">案件</div>
            <span className="text-xs text-ink-primary">
              {profile.caseType || "—"}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-1.5 flex-wrap">
          {profile.claims.slice(0, 3).map((claim, i) => (
            <span
              key={i}
              className={`text-xs px-2 py-0.5 rounded ${
                claim.variant === "danger"
                  ? "bg-danger/10 text-danger"
                  : "bg-accent-muted text-accent"
              }`}
            >
              {claim.text.length > 8
                ? claim.text.slice(0, 8) + "…"
                : claim.text}
            </span>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="w-full h-full flex flex-col">
      <div className="px-4 sm:px-5 h-10 shrink-0 flex items-center border-b border-border-color">
        <span className="text-xs font-semibold text-ink-primary">
          当事人画像
        </span>
      </div>
      <ScrollArea className="flex-1 px-4 sm:px-5 py-4">
        <div className="space-y-6">
          <Section first>
            <SectionHeader icon={User} label="基本信息" />
            <EntryList entries={categoryEntries("basic_info")} />
          </Section>

          <Section>
            <SectionHeader icon={Heart} label="情绪状态" />
            <EntryList entries={categoryEntries("emotion")} />
          </Section>

          <Section>
            <KeyClaims profile={profile} />
          </Section>

          <Section>
            <SectionHeader icon={ShieldAlert} label="风险暴露" />
            {profile.risks.length === 0 ? (
              <EmptyHint />
            ) : (
              <div className="flex flex-col gap-1">
                {profile.risks.map((risk, i) => (
                  <ItemRow
                    key={i}
                          dot={
                      <span
                        className={`w-1.5 h-1.5 rounded-full mt-1.5 shrink-0 ${
                          risk.level === "high"
                            ? "bg-danger"
                            : risk.level === "medium"
                              ? "bg-warning"
                              : "bg-ink-muted"
                        }`}
                      />
                    }
                  >
                    <span className="text-xs text-ink-primary leading-relaxed">
                      {risk.description}
                    </span>
                    <MetaLine
                      timestamp={risk.timestamp}
                      sourceUttId={risk.sourceUttId}
                    />
                  </ItemRow>
                ))}
              </div>
            )}
          </Section>

          <Section>
            <ConfirmedFacts profile={profile} />
          </Section>
        </div>
      </ScrollArea>
    </div>
  );
}
