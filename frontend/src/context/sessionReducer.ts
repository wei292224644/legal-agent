import type { ServerEvent } from '@/types/events'
import type { SessionAction, SessionState } from './session-context'
import { entriesToProfile } from '@/types'
import type {
  Insight, ProfileEntryItem, Suggestion, TranscriptLine,
} from '@/types'

function recvEvent(state: SessionState, evt: ServerEvent): SessionState {
  switch (evt.type) {
    case 'transcript': {
      const line: TranscriptLine = {
        id: evt.utt_id,
        speaker: (evt.speaker as TranscriptLine['speaker']) ?? 'uncertain',
        text: evt.text,
        timestamp: evt.t_start,
      }
      return { ...state, transcripts: [...state.transcripts, line] }
    }
    case 'insight.ready': {
      const insight: Insight = {
        id: evt.id,
        uttId: evt.utt_id,
        text: evt.text,
        createdAt: '',
      }
      return { ...state, insights: [insight, ...state.insights] }
    }
    case 'analysis.proposed': {
      const exists = state.suggestions.some((s) => s.requestId === evt.request_id)
      if (exists) return state
      const sug: Suggestion = {
        id: evt.request_id,
        requestId: evt.request_id,
        status: 'pending',
        topic: evt.topic,
        rationale: evt.rationale,
        text: null,
        createdAt: '',
      }
      return { ...state, suggestions: [sug, ...state.suggestions] }
    }
    case 'analysis.ready':
      return {
        ...state,
        suggestions: state.suggestions.map((s) =>
          s.requestId === evt.request_id
            ? { ...s, status: 'ready' as const, text: evt.text }
            : s
        ),
      }
    case 'analysis.dismissed':
      return {
        ...state,
        suggestions: state.suggestions.filter((s) => s.requestId !== evt.request_id),
      }
    case 'profile.updated': {
      const merged: ProfileEntryItem[] = [
        ...(state.profile?.entries ?? []),
        ...evt.entries.map((e) => ({
          key: e.key,
          value: e.value,
          subject: e.subject,
          category: 'fact' as const,
        })),
      ]
      return { ...state, profile: entriesToProfile(merged) }
    }
    case 'confirm_ack':
      return evt.ok
        ? state
        : {
            ...state,
            suggestions: state.suggestions.filter((s) => s.requestId !== evt.request_id),
          }
    case 'error':
    case 'pong':
      return state
    default: {
      const _exhaustive: never = evt
      void _exhaustive
      return state
    }
  }
}

export function sessionReducer(state: SessionState, action: SessionAction): SessionState {
  switch (action.type) {
    case 'RECV_EVENT':
      return recvEvent(state, action.payload)
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
          s.requestId === action.payload.requestId
            ? { ...s, ...action.payload.updates }
            : s
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
