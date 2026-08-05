import { CONTROL_ORIGIN, requestJson } from './http-client'

const MEMORY_MAINTENANCE_TIMEOUT_MS = 5 * 60 * 1000

export interface MemoryDocListOptions {
  scope?: string
  workspaceId?: string
  sessionId?: string
  layer?: string
}

export interface MemoryMetadata extends Record<string, unknown> {
  expires_at?: string | null
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
}

const buildDocsUrl = (options?: MemoryDocListOptions) => {
  const search = new URLSearchParams()
  if (options?.scope) search.set('scope', options.scope)
  if (options?.workspaceId) search.set('workspace_id', options.workspaceId)
  if (options?.sessionId) search.set('session_id', options.sessionId)
  if (options?.layer) search.set('layer', options.layer)
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
  getIndexStatus: async () => requestJson<MemoryIndexStatus>(`${CONTROL_ORIGIN}/memory/index/status`),
  rebuildIndex: async () => requestJson<{ status: string; backend?: string; document_count?: number; indexed_count?: number; skipped_count?: number; message?: string }>(`${CONTROL_ORIGIN}/memory/index/rebuild`, {
    method: 'POST',
    timeoutMs: MEMORY_MAINTENANCE_TIMEOUT_MS,
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
