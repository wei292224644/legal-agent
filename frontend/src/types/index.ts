export type Insight = {
  id: string
  uttId: string
  text: string
  createdAt: string
}

export type SuggestionStatus = 'pending' | 'running' | 'ready' | 'expired' | 'dismissed';

export type Suggestion = {
  id: string;
  requestId: string;
  status: SuggestionStatus;
  topic: string;
  rationale: string;
  text: string | null;
  progress?: number;
  source?: 'direct' | 'gated';
  createdAt: string;
};

export type SpeakerRole = 'lawyer' | 'client' | 'uncertain';

export type TranscriptLine = {
  id: string;
  speaker: SpeakerRole;
  text: string;
  timestamp: number;
};

export type ProfileCategory = 'basic_info' | 'emotion' | 'risk' | 'claim' | 'fact';

export type ProfileEntryItem = {
  key: string;
  value: string;
  subject: string;
  category: ProfileCategory;
  timestamp?: number;
  sourceUttId?: string;
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
    timestamp?: number;
    sourceUttId?: string;
  }>;
  risks: Array<{
    level: 'high' | 'medium' | 'low';
    description: string;
    timestamp?: number;
    sourceUttId?: string;
  }>;
  facts: Array<{
    text: string;
    confirmed: boolean;
    timestamp?: number;
    sourceUttId?: string;
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
  const sorted = [...entries].sort((a, b) => (b.timestamp ?? 0) - (a.timestamp ?? 0));
  const basicEntries = sorted.filter((e) => e.category === 'basic_info');
  const emotionEntries = sorted.filter((e) => e.category === 'emotion');

  return {
    entries: sorted,
    role: basicEntries.length > 0 ? '已建档' : '',
    caseType: '',
    sessionRound: '',
    emotion: emotionEntries.length > 0
      ? { label: emotionEntries[0].value, score: 50, description: '' }
      : null,
    claims: sorted
      .filter((e) => e.category === 'claim')
      .map((e) => ({
        text: `${e.key}: ${e.value}`,
        variant: 'default' as const,
        timestamp: e.timestamp,
        sourceUttId: e.sourceUttId,
      })),
    risks: sorted
      .filter((e) => e.category === 'risk')
      .map((e) => ({
        level: ('medium' as const),
        description: `${e.key}: ${e.value}`,
        timestamp: e.timestamp,
        sourceUttId: e.sourceUttId,
      })),
    facts: sorted
      .filter((e) => e.category === 'fact')
      .map((e) => ({
        text: `${e.key}: ${e.value}`,
        confirmed: true,
        timestamp: e.timestamp,
        sourceUttId: e.sourceUttId,
      })),
  };
}
