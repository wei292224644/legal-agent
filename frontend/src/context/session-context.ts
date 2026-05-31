import { createContext } from 'react'
import type {
  ConnectionStatus,
  Insight,
  Profile,
  RecordingStatus,
  Suggestion,
  TranscriptLine,
} from '@/types'

export type SessionState = {
  sessionId: string
  connectionStatus: ConnectionStatus
  recordingStatus: RecordingStatus
  profile: Profile | null
  insights: Insight[]
  suggestions: Suggestion[]
  transcripts: TranscriptLine[]
  isTranscriptPanelOpen: boolean
  activeMobileTab: 'insights' | 'profile' | 'transcript'
}

export const initialState: SessionState = {
  sessionId: '',
  connectionStatus: 'connecting',
  recordingStatus: 'idle',
  profile: null,
  insights: [],
  suggestions: [],
  transcripts: [],
  isTranscriptPanelOpen: true,
  activeMobileTab: 'insights',
}

export type SessionAction =
  | { type: 'SET_SESSION_ID'; payload: string }
  | { type: 'SET_PROFILE'; payload: Profile | null }
  | { type: 'ADD_INSIGHT'; payload: Insight }
  | { type: 'ADD_SUGGESTION'; payload: Suggestion }
  | { type: 'UPDATE_SUGGESTION'; payload: { requestId: string; updates: Partial<Suggestion> } }
  | { type: 'DISMISS_SUGGESTION'; payload: string }
  | { type: 'ADD_TRANSCRIPT'; payload: TranscriptLine }
  | { type: 'SET_CONNECTION_STATUS'; payload: ConnectionStatus }
  | { type: 'SET_RECORDING_STATUS'; payload: RecordingStatus }
  | { type: 'TOGGLE_TRANSCRIPT_PANEL' }
  | { type: 'SET_ACTIVE_MOBILE_TAB'; payload: 'insights' | 'profile' | 'transcript' }
  | { type: 'HYDRATE'; payload: Partial<SessionState> }

export type SessionContextValue = {
  state: SessionState
  dispatch: React.Dispatch<SessionAction>
  setSessionId: (id: string) => void
  setProfile: (profile: Profile | null) => void
  addInsight: (insight: Insight) => void
  addSuggestion: (suggestion: Suggestion) => void
  updateSuggestion: (requestId: string, updates: Partial<Suggestion>) => void
  dismissSuggestion: (requestId: string) => void
  addTranscript: (line: TranscriptLine) => void
  setConnectionStatus: (status: ConnectionStatus) => void
  setRecordingStatus: (status: RecordingStatus) => void
  toggleTranscriptPanel: () => void
  setActiveMobileTab: (tab: 'insights' | 'profile' | 'transcript') => void
  hydrate: (payload: Partial<SessionState>) => void
}

export const SessionContext = createContext<SessionContextValue | null>(null)
