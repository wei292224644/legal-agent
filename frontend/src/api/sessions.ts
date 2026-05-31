export type HistoryUtterance = {
  id: string;
  text: string;
  t_start: number;
  t_end: number;
  speaker: "lawyer" | "client" | "uncertain" | null;
  closed_by: string;
};

export type HistorySuggestion = {
  id: string;
  utt_id: string;
  request_id: string | null;
  source: "direct" | "gated";
  status: "pending" | "running" | "ready" | "expired" | "dismissed";
  preview_topic: string | null;
  preview_rationale: string | null;
  text: string | null;
  error: string | null;
  confirmed_at: string | null;
  created_at: string;
};

export type HistoryProfileEntry = {
  key: string;
  value: string;
  subject: string;
};

export type SessionHistory = {
  session_id: string;
  status: string;
  utterances: HistoryUtterance[];
  suggestions: HistorySuggestion[];
  profile_entries: HistoryProfileEntry[];
};

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export async function fetchHistory(
  sessionId: string
): Promise<SessionHistory | null> {
  const r = await fetch(`${API_BASE}/api/sessions/${sessionId}/history`);
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`history fetch failed: ${r.status}`);
  return r.json();
}
