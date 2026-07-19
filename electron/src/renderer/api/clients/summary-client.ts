import { CONTROL_ORIGIN, requestBlob, requestJson } from './http-client'

export interface SummaryQualityScores {
  overall?: number
  facts?: number
  preferences?: number
  goals_open_tasks?: number
}

export interface SummaryStatsPayload {
  session_id?: string
  summary_length?: number
  updated_at?: string | null
  compression_count?: number
  rewrite_count?: number
  messages_since_rewrite?: number
  has_summary?: boolean
  effective_rewrite_interval?: number
  quality_band?: string
  quality_scorer?: string
  quality_basis?: string
  quality_score_cooldown_seconds?: number
  quality_score_budget_per_hour?: number
  quality?: SummaryQualityScores
}

export interface SummaryDetailResponse {
  summary: string
  stats: SummaryStatsPayload
}

export interface SummarySessionItem extends SummaryDetailResponse {
  session_id: string
}

interface ReadinessCheck {
  ok?: boolean
  message?: string
}

export const summaryClient = {
  getSessions: async () => requestJson<{ sessions: SummarySessionItem[] }>(`${CONTROL_ORIGIN}/api/summary`),
  getSummary: async (sessionId: string) => requestJson<SummaryDetailResponse>(`${CONTROL_ORIGIN}/api/summary/${encodeURIComponent(sessionId)}`),
  getAudit: async (params?: Record<string, string | number>) => {
    const search = new URLSearchParams()
    Object.entries(params ?? {}).forEach(([key, value]) => {
      search.set(key, String(value))
    })
    const suffix = search.size ? `?${search.toString()}` : ''
    return requestJson<{ logs: unknown[] }>(`${CONTROL_ORIGIN}/api/summary/audit${suffix}`)
  },
  getGovernanceReport: async (days = 7) =>
    requestJson<{ trends: unknown[]; alerts: unknown[] }>(`${CONTROL_ORIGIN}/api/summary/report/json?days=${encodeURIComponent(String(days))}`),
  ackAlert: async (key: string) =>
    requestJson(`${CONTROL_ORIGIN}/api/summary/alerts/ack?key=${encodeURIComponent(key)}`, { method: 'POST' }),
  snoozeAlert: async (key: string, minutes: number) =>
    requestJson(`${CONTROL_ORIGIN}/api/summary/alerts/snooze?key=${encodeURIComponent(key)}&minutes=${encodeURIComponent(String(minutes))}`, {
      method: 'POST',
    }),
  clearAlerts: async () => requestJson(`${CONTROL_ORIGIN}/api/summary/alerts/clear`, { method: 'POST' }),
  getReadiness: async () => requestJson<{ ready: boolean; checks?: Record<string, ReadinessCheck> }>(`${CONTROL_ORIGIN}/api/readiness`),
  rewriteSummary: async (sessionId: string) =>
    requestJson<{ ok?: boolean; message?: string }>(`${CONTROL_ORIGIN}/api/summary/${encodeURIComponent(sessionId)}/rewrite`, {
      method: 'POST',
    }),
  exportGovernanceReport: async (format: 'json' | 'csv', days = 7) =>
    requestBlob(`${CONTROL_ORIGIN}/api/summary/report/${encodeURIComponent(format)}?days=${encodeURIComponent(String(days))}`),
}
