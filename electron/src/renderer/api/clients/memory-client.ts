import { CONTROL_ORIGIN, requestJson } from './http-client'

const MEMORY_MAINTENANCE_TIMEOUT_MS = 5 * 60 * 1000

export interface MemoryDocListOptions {
  scope?: string
  workspaceId?: string
  sessionId?: string
  layer?: string
  includeState?: 'active' | 'forgotten' | 'all'
}

export interface MemoryMetadata extends Record<string, unknown> {
  schema_version?: number
  revision?: number
  review_status?: MemoryReviewStatus
  valid_from?: string | null
  valid_to?: string | null
  occurred_at?: string | null
  ingested_at?: string | null
  source_ids?: string[]
  supersedes?: string | string[] | null
  superseded_by?: string | null
  expires_at?: string | null
  source_kind?: string
  source_id?: string
  turn_id?: string
  evidence?: unknown
  confidence_history?: Array<Record<string, unknown>>
}

export interface MemoryDocWritePayload {
  id?: string
  text: string
  metadata?: MemoryMetadata
  scope?: string
  workspace_id?: string
  session_id?: string
  layer?: string
  type?: string
  importance?: number
  confidence?: number
  confidence_source?: string
  source_kind?: string
  source_id?: string
  turn_id?: string
  evidence?: unknown
}

export interface MemoryMaintenancePolicyPayload {
  scope?: string
  workspace_id?: string
  session_id?: string
  working_retention_days: number
  low_quality_threshold: number
  include_stale_working: boolean
  include_low_quality: boolean
  include_exact_duplicates: boolean
}

export interface MemoryMaintenanceCandidate {
  id: string
  text: string
  action: 'delete'
  reasons: string[]
  layer: string
  importance: number
  confidence: number
  quality_score: number
  updated_at?: string
}

export interface MemoryMaintenancePreview {
  status: 'preview'
  preview_token: string
  policy: MemoryMaintenancePolicyPayload
  summary: {
    scanned_count: number
    active_count: number
    delete_count: number
  }
  candidates: MemoryMaintenanceCandidate[]
}

export interface MemoryIndexStatus {
  status: string
  count: number
  backend?: string
  healthy?: boolean
  message?: string
  metadata?: Record<string, unknown>
  job?: MemoryIndexRebuildJob | null
}

export interface MemoryIndexRebuildJob {
  job_id: string
  state: 'queued' | 'running' | 'cancelling' | 'cancelled' | 'failed' | 'interrupted' | 'completed'
  phase: string
  processed_count: number
  total_count: number
  started_at: string
  updated_at: string
  finished_at?: string | null
  last_error?: string | null
  recoverable: boolean
  retry_of?: string | null
  result?: Record<string, unknown> | null
}

export interface MemoryIndexRebuildResponse {
  status: string
  index_status: string
  job: MemoryIndexRebuildJob
}

export type MemoryLifecycleState = 'active' | 'forgotten' | 'expired' | 'scheduled' | 'superseded' | 'rejected'
export type MemoryReviewStatus = 'unreviewed' | 'pending' | 'accepted' | 'confirmed' | 'rejected' | 'superseded'
export type MemoryRecallFeedback = 'helpful' | 'not_helpful' | 'incorrect' | 'dismissed'

export interface MemoryOverview {
  total: number
  recallable: number
  by_state: Record<string, number>
  by_layer: Record<string, number>
  by_source: Record<string, number>
  by_review_status: Record<string, number>
  latest_activity: Array<{
    id: string
    text: string
    state: MemoryLifecycleState
    layer?: string
    source?: string
    updated_at?: string
    action?: string
  }>
  index_health: Omit<MemoryIndexStatus, 'count'>
}

export interface MemoryCandidate {
  id: string
  text: string
  metadata: MemoryMetadata
}

export interface MemoryExport {
  format: 'yuizaki-memory-export'
  version: number
  exported_at: string
  scope: string
  workspace_id?: string
  session_id?: string
  include_state: 'active' | 'forgotten' | 'all'
  count: number
  docs: Array<{ id: string; text: string; metadata: MemoryMetadata }>
}

export interface MemoryImportResult {
  status: string
  imported_ids: string[]
  imported_count: number
  skipped: Array<{ id?: string | null; reason: string; detail?: unknown }>
  skipped_count: number
  skipped_reason_counts?: Record<string, number>
  restored_soft_forgotten_count?: number
  effects?: {
    authority_store?: string
    index?: string
    chat_references?: string
  }
  scope: string
  workspace_id?: string
  session_id?: string
}

export interface MemoryDeletePreview {
  status: 'preview'
  ids: string[]
  total_count: number
  hard_delete_count: number
  candidate_tombstone_count: number
  affected_message_count: number
  effects: {
    authority_store: string
    index: string
    chat_references: string
    recoverable: boolean
  }
}

const buildDocsUrl = (options?: MemoryDocListOptions) => {
  const search = new URLSearchParams()
  if (options?.scope) search.set('scope', options.scope)
  if (options?.workspaceId) search.set('workspace_id', options.workspaceId)
  if (options?.sessionId) search.set('session_id', options.sessionId)
  if (options?.layer) search.set('layer', options.layer)
  if (options?.includeState) search.set('include_state', options.includeState)
  const suffix = search.toString()
  return `${CONTROL_ORIGIN}/memory/docs${suffix ? `?${suffix}` : ''}`
}

export const memoryClient = {
  getDocs: async (options?: MemoryDocListOptions) => requestJson<{ docs: unknown[] }>(buildDocsUrl(options)),
  addDoc: async (payload: MemoryDocWritePayload) =>
    requestJson<{ status: string; id: string; skipped?: boolean; reason?: string; duplicate_candidates?: unknown[] }>(`${CONTROL_ORIGIN}/memory/docs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  updateDoc: async (id: string, payload: MemoryDocWritePayload & { edit_reason?: string }) =>
    requestJson<{ status: string; id: string; layer?: string; scope?: string; importance?: number }>(`${CONTROL_ORIGIN}/memory/docs/${encodeURIComponent(id)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  correctDoc: async (id: string, payload: { text: string; reason?: string; turn_id?: string; evidence?: unknown }) =>
    requestJson<{ status: string; id: string; action?: string }>(`${CONTROL_ORIGIN}/memory/docs/${encodeURIComponent(id)}/correction`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    }),
  softForgetDoc: async (id: string, payload?: { reason?: string; turn_id?: string }) =>
    requestJson<{ status: string; id: string; action?: string }>(`${CONTROL_ORIGIN}/memory/docs/${encodeURIComponent(id)}/soft-forget`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload || {}),
    }),
  restoreDoc: async (id: string, payload?: { reason?: string }) =>
    requestJson<{ status: string; id: string; action?: string }>(`${CONTROL_ORIGIN}/memory/docs/${encodeURIComponent(id)}/restore`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload || {}),
    }),
  rollbackDoc: async (id: string, revision: number) =>
    requestJson<{ status: string; id: string; revision?: number; action?: string }>(`${CONTROL_ORIGIN}/memory/docs/${encodeURIComponent(id)}/rollback`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ revision }),
    }),
  recordRecallFeedback: async (id: string, feedback: MemoryRecallFeedback) =>
    requestJson<{ status: 'recorded'; id: string; feedback: MemoryRecallFeedback; counts: Record<string, number> }>(`${CONTROL_ORIGIN}/memory/docs/${encodeURIComponent(id)}/feedback`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ feedback }),
    }),
  getOverview: async (options?: MemoryDocListOptions) => {
    const search = new URLSearchParams()
    if (options?.scope) search.set('scope', options.scope)
    if (options?.workspaceId) search.set('workspace_id', options.workspaceId)
    if (options?.sessionId) search.set('session_id', options.sessionId)
    const suffix = search.toString()
    return requestJson<MemoryOverview>(`${CONTROL_ORIGIN}/memory/overview${suffix ? `?${suffix}` : ''}`)
  },
  getCandidates: async (options?: MemoryDocListOptions & { status?: MemoryReviewStatus }) => {
    const search = new URLSearchParams()
    if (options?.status) search.set('status', options.status)
    if (options?.scope) search.set('scope', options.scope)
    if (options?.workspaceId) search.set('workspace_id', options.workspaceId)
    if (options?.sessionId) search.set('session_id', options.sessionId)
    const suffix = search.toString()
    return requestJson<{ status: string; candidates: MemoryCandidate[]; count: number }>(
      `${CONTROL_ORIGIN}/memory/candidates${suffix ? `?${suffix}` : ''}`,
    )
  },
  exportDocs: async (options?: MemoryDocListOptions) => {
    const search = new URLSearchParams()
    if (options?.scope) search.set('scope', options.scope)
    if (options?.workspaceId) search.set('workspace_id', options.workspaceId)
    if (options?.sessionId) search.set('session_id', options.sessionId)
    if (options?.includeState) search.set('include_state', options.includeState)
    const suffix = search.toString()
    return requestJson<MemoryExport>(`${CONTROL_ORIGIN}/memory/export${suffix ? `?${suffix}` : ''}`)
  },
  importDocs: async (payload: {
    format: 'yuizaki-memory-export'
    version: number
    docs: Array<{ id?: string; text: string; metadata?: MemoryMetadata }>
    scope: string
    workspace_id?: string
    session_id?: string
    conflict?: 'skip'
  }) => requestJson<MemoryImportResult>(`${CONTROL_ORIGIN}/memory/import`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }),
  reviewCandidate: async (id: string, payload: { decision: 'approve' | 'reject'; reason?: string }) =>
    requestJson<{ status: string; id: string }>(`${CONTROL_ORIGIN}/memory/docs/${encodeURIComponent(id)}/review`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  getIndexStatus: async () => requestJson<MemoryIndexStatus>(`${CONTROL_ORIGIN}/memory/index/status`),
  rebuildIndex: async () => requestJson<MemoryIndexRebuildResponse>(`${CONTROL_ORIGIN}/memory/index/rebuild`, {
    method: 'POST',
    timeoutMs: MEMORY_MAINTENANCE_TIMEOUT_MS,
  }),
  getIndexRebuildJob: async (jobId: string) => requestJson<MemoryIndexRebuildResponse>(`${CONTROL_ORIGIN}/memory/index/rebuild/${encodeURIComponent(jobId)}`),
  cancelIndexRebuild: async (jobId: string) => requestJson<MemoryIndexRebuildResponse>(`${CONTROL_ORIGIN}/memory/index/rebuild/${encodeURIComponent(jobId)}/cancel`, {
    method: 'POST',
  }),
  retryIndexRebuild: async (jobId: string) => requestJson<MemoryIndexRebuildResponse>(`${CONTROL_ORIGIN}/memory/index/rebuild/${encodeURIComponent(jobId)}/retry`, {
    method: 'POST',
  }),
  addMemory: async (payload: Record<string, unknown>) =>
    requestJson<{ status?: string; id?: string; type?: string; layer?: string; scope?: string; importance?: number; skipped?: boolean; reason?: string; duplicate_candidates?: unknown[] }>(`${CONTROL_ORIGIN}/memory/memory/add`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      timeoutMs: MEMORY_MAINTENANCE_TIMEOUT_MS,
    }),
  removeDoc: async (id: string) =>
    requestJson(`${CONTROL_ORIGIN}/memory/docs/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    }),
  removeDocs: async (ids: string[]) =>
    requestJson<{ status: string; ids: string[]; deleted_count: number }>(`${CONTROL_ORIGIN}/memory/docs/batch-delete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids }),
    }),
  previewDelete: async (ids: string[]) =>
    requestJson<MemoryDeletePreview>(`${CONTROL_ORIGIN}/memory/docs/delete-preview`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids }),
    }),
  previewMaintenance: async (payload: MemoryMaintenancePolicyPayload) =>
    requestJson<MemoryMaintenancePreview>(`${CONTROL_ORIGIN}/memory/maintenance/preview`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      timeoutMs: MEMORY_MAINTENANCE_TIMEOUT_MS,
    }),
  applyMaintenance: async (payload: MemoryMaintenancePolicyPayload & { preview_token: string; confirmation: 'PERMANENT_DELETE' }) =>
    requestJson<{ status: 'purged'; changed_ids: string[]; changed_count: number; storage?: Record<string, unknown> | null }>(`${CONTROL_ORIGIN}/memory/maintenance/apply`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      timeoutMs: MEMORY_MAINTENANCE_TIMEOUT_MS,
    }),
  queryRag: async (payload: Record<string, unknown>) =>
    requestJson<{ results: unknown[]; trace?: unknown }>(`${CONTROL_ORIGIN}/memory/rag/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  query: async (payload: Record<string, unknown>) =>
    requestJson<{ query: string; results: unknown[]; trace?: unknown }>(`${CONTROL_ORIGIN}/memory/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  queryPipeline: async (query: string, options?: { sessionId?: string; topK?: number; workspaceId?: string; scope?: string; layers?: string[] }) => {
    const topK = options?.topK ?? 5
    const search = new URLSearchParams({ query, top_k: String(topK) })
    if (options?.sessionId) {
      search.set('session_id', options.sessionId)
    }
    if (options?.workspaceId) {
      search.set('workspace_id', options.workspaceId)
    }
    if (options?.scope) {
      search.set('scope', options.scope)
    }
    if (options?.layers?.length) {
      search.set('layers', options.layers.join(','))
    }
    return requestJson<{ results: unknown[]; trace: unknown }>(`${CONTROL_ORIGIN}/api/memory/pipeline/query?${search.toString()}`)
  },
}
