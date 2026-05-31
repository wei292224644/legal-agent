import { useReducer, useCallback, type ReactNode } from 'react'
import {
  SessionContext,
  initialState,
  type SessionState,
  type SessionAction,
} from './session-context'
import type {
  ConnectionStatus,
  Insight,
  Profile,
  RecordingStatus,
  Suggestion,
  TranscriptLine,
} from '@/types'

function sessionReducer(state: SessionState, action: SessionAction): SessionState {
  switch (action.type) {
    case 'SET_SESSION_ID':
      return { ...state, sessionId: action.payload }
    case 'SET_PROFILE':
      return { ...state, profile: action.payload }
    case 'ADD_INSIGHT':
      return { ...state, insights: [action.payload, ...state.insights] }
    case 'ADD_SUGGESTION': {
      const exists = state.suggestions.some((s) => s.requestId === action.payload.requestId)
      if (exists) return state
      return { ...state, suggestions: [action.payload, ...state.suggestions] }
    }
    case 'UPDATE_SUGGESTION':
      return {
        ...state,
        suggestions: state.suggestions.map((s) =>
          s.requestId === action.payload.requestId ? { ...s, ...action.payload.updates } : s
        ),
      }
    case 'DISMISS_SUGGESTION':
      return {
        ...state,
        suggestions: state.suggestions.filter((s) => s.requestId !== action.payload),
      }
    case 'ADD_TRANSCRIPT':
      return { ...state, transcripts: [...state.transcripts, action.payload] }
    case 'SET_CONNECTION_STATUS':
      return { ...state, connectionStatus: action.payload }
    case 'SET_RECORDING_STATUS':
      return { ...state, recordingStatus: action.payload }
    case 'TOGGLE_TRANSCRIPT_PANEL':
      return { ...state, isTranscriptPanelOpen: !state.isTranscriptPanelOpen }
    case 'SET_ACTIVE_MOBILE_TAB':
      return { ...state, activeMobileTab: action.payload }
    case 'HYDRATE':
      return { ...state, ...action.payload }
    default:
      return state
  }
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(sessionReducer, initialState)

  const setSessionId = useCallback((id: string) => dispatch({ type: 'SET_SESSION_ID', payload: id }), [])
  const setProfile = useCallback((profile: Profile | null) => dispatch({ type: 'SET_PROFILE', payload: profile }), [])
  const addInsight = useCallback((insight: Insight) => dispatch({ type: 'ADD_INSIGHT', payload: insight }), [])
  const addSuggestion = useCallback((suggestion: Suggestion) => dispatch({ type: 'ADD_SUGGESTION', payload: suggestion }), [])
  const updateSuggestion = useCallback((requestId: string, updates: Partial<Suggestion>) => dispatch({ type: 'UPDATE_SUGGESTION', payload: { requestId, updates } }), [])
  const dismissSuggestion = useCallback((requestId: string) => dispatch({ type: 'DISMISS_SUGGESTION', payload: requestId }), [])
  const addTranscript = useCallback((line: TranscriptLine) => dispatch({ type: 'ADD_TRANSCRIPT', payload: line }), [])
  const setConnectionStatus = useCallback((status: ConnectionStatus) => dispatch({ type: 'SET_CONNECTION_STATUS', payload: status }), [])
  const setRecordingStatus = useCallback((status: RecordingStatus) => dispatch({ type: 'SET_RECORDING_STATUS', payload: status }), [])
  const toggleTranscriptPanel = useCallback(() => dispatch({ type: 'TOGGLE_TRANSCRIPT_PANEL' }), [])
  const setActiveMobileTab = useCallback((tab: 'insights' | 'profile' | 'transcript') => dispatch({ type: 'SET_ACTIVE_MOBILE_TAB', payload: tab }), [])
  const hydrate = useCallback((payload: Partial<SessionState>) => dispatch({ type: 'HYDRATE', payload }), [])

  return (
    <SessionContext.Provider
      value={{
        state,
        dispatch,
        setSessionId,
        setProfile,
        addInsight,
        addSuggestion,
        updateSuggestion,
        dismissSuggestion,
        addTranscript,
        setConnectionStatus,
        setRecordingStatus,
        toggleTranscriptPanel,
        setActiveMobileTab,
        hydrate,
      }}
    >
      {children}
    </SessionContext.Provider>
  )
}
