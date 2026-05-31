export type InsightCategory =
  | 'law_citation'
  | 'risk_warning'
  | 'contract_clause'
  | 'behavior_analysis';

export type Insight = {
  id: string;
  category: InsightCategory;
  title: string;
  content: string;
  citation?: string;
  riskLevel?: 'high' | 'medium' | 'low';
  createdAt: string;
};

export type SuggestionStatus = 'pending' | 'running' | 'ready' | 'expired' | 'dismissed';

export type Suggestion = {
  id: string;
  requestId: string;
  status: SuggestionStatus;
  topic: string;
  rationale: string;
  text: string | null;
  progress?: number;
  createdAt: string;
};

export type SpeakerRole = 'lawyer' | 'client' | 'uncertain';

export type TranscriptLine = {
  id: string;
  speaker: SpeakerRole;
  text: string;
  timestamp: number;
};

export type ProfileEntryItem = {
  key: string;
  value: string;
  subject: string;
};

export type Profile = {
  entries: ProfileEntryItem[];
  role: string;
  caseType: string;
  sessionRound: string;
  emotion: {
    label: string;
    score: number;
    description: string;
  } | null;
  claims: Array<{
    text: string;
    variant: 'default' | 'danger';
  }>;
  risks: Array<{
    level: 'high' | 'medium' | 'low';
    description: string;
  }>;
  facts: Array<{
    text: string;
    confirmed: boolean;
  }>;
};

export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'reconnecting';
export type RecordingStatus = 'idle' | 'recording' | 'paused';

export type Session = {
  sessionId: string;
  connectionStatus: ConnectionStatus;
  recordingStatus: RecordingStatus;
  profile: Profile | null;
  insights: Insight[];
  suggestions: Suggestion[];
  transcripts: TranscriptLine[];
  isTranscriptPanelOpen: boolean;
  activeMobileTab: 'insights' | 'profile' | 'transcript';
};

export function entriesToProfile(entries: ProfileEntryItem[]): Profile {
  return {
    entries,
    role: '',
    caseType: '',
    sessionRound: '',
    emotion: null,
    claims: entries
      .filter((e) => e.subject === '当事人')
      .map((e) => ({ text: `${e.key}: ${e.value}`, variant: 'default' as const })),
    risks: [],
    facts: entries.map((e) => ({ text: `${e.key}: ${e.value}`, confirmed: true })),
  };
}
