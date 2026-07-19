import { CONTROL_ORIGIN, requestJson } from './http-client'

export interface CompanionRecord {
  id: string
  name: string
  avatar?: string | null
  model_type?: string | null
  model_id?: string | null
  voice_profile?: {
    ref_audio?: string | null
    ref_text?: string | null
    lang?: string | null
    base_url?: string | null
  } | null
  persona_prompt?: string | null
  temperament?: string | null
  attachment_style?: string | null
  support_style?: string | null
  emotion_state?: string | null
  affinity_state?: number | null
  energy_state?: number | null
  trust_state?: number | null
  intimacy_state?: number | null
  interruptibility_state?: number | null
  fatigue_state?: number | null
  created_at: string | null
  updated_at: string | null
}

export interface RelationshipHistoryEvent {
  kind?: string
  mood?: string
  affinity?: number
  energy?: number
  text?: string
  timestamp?: string | null
  workspace_id?: string | null
  scope?: string | null
  importance?: number | null
  milestone?: boolean
}

export interface RelationshipSummary {
  event_count: number
  high_importance_count: number
  global_count: number
  workspace_count: number
  milestone_count: number
  recent_trust_shift_count: number
  recent_gratitude_count: number
  relationship_stage: string
  proactive_budget: number
  relationship_trend: string
  milestone_salience?: string | null
  milestone_reasoning?: string | null
}

export const companionClient = {
  list: async () => requestJson<{ companions: CompanionRecord[] }>(`${CONTROL_ORIGIN}/api/companions`),
  get: async (id: string) => requestJson<CompanionRecord>(`${CONTROL_ORIGIN}/api/companions/${encodeURIComponent(id)}`),
  create: async (payload: { id?: string; name: string; model_type?: string; model_id?: string; persona_prompt?: string; voice_profile?: CompanionRecord['voice_profile'] }) =>
    requestJson<CompanionRecord>(`${CONTROL_ORIGIN}/api/companions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  update: async (id: string, payload: Partial<Omit<CompanionRecord, 'id' | 'created_at' | 'updated_at'>>) =>
    requestJson<CompanionRecord>(`${CONTROL_ORIGIN}/api/companions/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  remove: async (id: string) =>
    requestJson<{ status: string }>(`${CONTROL_ORIGIN}/api/companions/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    }),
  relationshipHistory: async (id: string, limit = 20) =>
    requestJson<{ companion_id: string; events: RelationshipHistoryEvent[]; grouped: Record<string, Record<string, RelationshipHistoryEvent[]>>; milestones: RelationshipHistoryEvent[]; summary: RelationshipSummary }>(`${CONTROL_ORIGIN}/api/companions/${encodeURIComponent(id)}/relationship-history?limit=${encodeURIComponent(String(limit))}`),
}
