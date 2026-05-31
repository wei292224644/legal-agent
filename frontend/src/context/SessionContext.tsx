import { useReducer, useCallback, type ReactNode } from 'react'
import {
  SessionContext,
  initialState,
} from './session-context'
import { sessionReducer } from './sessionReducer'
import type { ServerEvent } from '@/types/events'
import type {
  ConnectionStatus,
  Insight,
  Profile,
  RecordingStatus,
  Suggestion,
  TranscriptLine,
} from '@/types'

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(sessionReducer, initialState)

  const recvEvent = useCallback(
    (evt: ServerEvent) => dispatch({ type: 'RECV_EVENT', payload: evt }),
    []
  )
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
        recvEvent,
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
