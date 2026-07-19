import { CONTROL_ORIGIN, requestJson } from './http-client'

export interface WorkspaceApiRecord {
  id: string
  name: string
  description?: string | null
  icon?: string | null
  color?: string | null
  companion_profile_id?: string | null
  default_model?: string | null
  system_prompt?: string | null
  tool_preset?: string | null
  memory_scope?: string | null
  mcp_preset_id?: string | null
  created_at: string | null
  updated_at: string | null
}

export type WorkspacePatchPayload = Partial<Pick<WorkspaceApiRecord,
  'name' |
  'description' |
  'companion_profile_id' |
  'memory_scope' |
  'default_model' |
  'system_prompt' |
  'tool_preset' |
  'mcp_preset_id'
>>

export const workspaceClient = {
  list: async () => requestJson<{ workspaces: WorkspaceApiRecord[] }>(`${CONTROL_ORIGIN}/api/workspaces`),
  create: async (payload: { id?: string; name: string; description?: string; companion_profile_id?: string }) =>
    requestJson<WorkspaceApiRecord>(`${CONTROL_ORIGIN}/api/workspaces`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  update: async (workspaceId: string, payload: WorkspacePatchPayload) =>
    requestJson<WorkspaceApiRecord>(`${CONTROL_ORIGIN}/api/workspaces/${encodeURIComponent(workspaceId)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  remove: async (workspaceId: string) =>
    requestJson<{ status: string }>(`${CONTROL_ORIGIN}/api/workspaces/${encodeURIComponent(workspaceId)}`, {
      method: 'DELETE',
    }),
  setActive: async (workspaceId: string) =>
    requestJson<{ ok: boolean; workspace_id: string; companion?: unknown }>(`${CONTROL_ORIGIN}/api/system/active-workspace`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace_id: workspaceId }),
    }),
}
