// 后端 backend/src/agent/events.py 的镜像。
// 改后端 schema 时必须同步本文件——CI 无法强制,靠 PR review 把关。

export type TranscriptDelta = {
  type: 'transcript'
  utt_id: string
  speaker: string  // 'lawyer' | 'client' | 'uncertain' (后端是宽 string)
  text: string
  t_start: number
  t_end: number
  closed_by: string | null
  is_final: boolean
}

export type InsightReady = {
  type: 'insight.ready'
  id: string
  utt_id: string
  text: string
  created_at: string
}

export type AnalysisProposed = {
  type: 'analysis.proposed'
  request_id: string
  utt_id: string
  topic: string
  rationale: string
  created_at: string
}

export type AnalysisReady = {
  type: 'analysis.ready'
  request_id: string
  utt_id: string
  text: string
}

export type AnalysisDismissed = {
  type: 'analysis.dismissed'
  request_id: string
  reason: 'dismissed' | 'expired' | 'abandoned'
}

export type ProfileEntryPayload = {
  key: string
  value: string
  subject: string
  timestamp: number
  source_utt_id: string
}

export type ProfileUpdated = {
  type: 'profile.updated'
  entries: ProfileEntryPayload[]
}

export type ConfirmAck = { type: 'confirm_ack'; request_id: string; ok: boolean }
export type ErrorEvent = { type: 'error'; message: string }
export type Pong = { type: 'pong' }

export type ServerEvent =
  | TranscriptDelta
  | InsightReady
  | AnalysisProposed
  | AnalysisReady
  | AnalysisDismissed
  | ProfileUpdated
  | ConfirmAck
  | ErrorEvent
  | Pong
