import { CONTROL_ORIGIN, requestBlob, requestJson } from './http-client'
import type {
  AgentPluginMutationResponse,
  AgentPluginsSnapshot,
  BackupRestoreResponse,
  AgentTraceSnapshot,
  ExperienceMetricsSnapshot,
  BackupTargetsSnapshot,
  DiagnosticsSnapshot,
  HeartbeatSnapshot,
  CompanionRuntimeSnapshot,
  MCPSnapshot,
  MCPMutationResponse,
  MCPRefreshResponse,
  PermissionMutationSnapshot,
  PermissionStateSnapshot,
  ScheduleMutationResponse,
  ScheduleCancellationResponse,
  SchedulesSnapshot,
  SystemLogsSnapshot,
} from '@/../shared/agent'
import type { CapabilitiesSnapshot, SkillCatalogItem, SkillCatalogSnapshot } from '@/../shared/capability'
import type { OrchestrationSnapshot } from '@/../shared/orchestration'

const SYSTEM_MAINTENANCE_TIMEOUT_MS = 30 * 60 * 1000
const MCP_OPERATION_TIMEOUT_MS = 2 * 60 * 1000

export const systemClient = {
  pythonHealth: async () => {
    return requestJson(`${CONTROL_ORIGIN}/api/ping`)
  },
  controlHealth: async () => {
    return requestJson(`${CONTROL_ORIGIN}/api/health`)
  },
  startPython: async () => window.petApi?.python?.start?.(),
  stopPython: async () => window.petApi?.python?.stop?.(),
  openExternal: async (url: string) => {
    if (window.petApi?.shell?.openExternal) {
      return window.petApi.shell.openExternal(url)
    }
    window.open(url, '_blank')
  },
  diagnostics: async () => requestJson<DiagnosticsSnapshot>(`${CONTROL_ORIGIN}/api/system/diagnostics`),
  systemStatus: async () => requestJson<Record<string, unknown>>(`${CONTROL_ORIGIN}/system/status`),
  databaseStats: async () => requestJson<Record<string, unknown>>(`${CONTROL_ORIGIN}/api/database/stats`),
  statistics: async () => requestJson<Record<string, unknown>>(`${CONTROL_ORIGIN}/api/statistics`),
  models: async () => requestJson<Record<string, unknown>>(`${CONTROL_ORIGIN}/v1/models`, { method: 'POST' }),
  updateStatistics: async () => requestJson<{ status: string }>(`${CONTROL_ORIGIN}/api/statistics/update`, { method: 'POST' }),
  effectivePreset: async (workspaceId: string) => requestJson<Record<string, unknown>>(`${CONTROL_ORIGIN}/api/workspaces/${encodeURIComponent(workspaceId)}/effective-preset`),
  exportData: async (kind: 'json' | 'csv', sessionId?: string, workspaceId?: string) => {
    const params = new URLSearchParams()
    if (sessionId) params.set('session_id', sessionId)
    if (workspaceId) params.set('workspace_id', workspaceId)
    const suffix = params.toString() ? `?${params.toString()}` : ''
    return requestBlob(`${CONTROL_ORIGIN}/api/export/${kind}${suffix}`, { method: 'POST' })
  },
  permissions: async () => requestJson<PermissionStateSnapshot>(`${CONTROL_ORIGIN}/api/system/permissions`),
  revokePermission: async (toolName: string) => requestJson<PermissionMutationSnapshot>(`${CONTROL_ORIGIN}/api/system/permissions/${encodeURIComponent(toolName)}`, { method: 'DELETE' }),
  clearPermissions: async () => requestJson<PermissionMutationSnapshot>(`${CONTROL_ORIGIN}/api/system/permissions`, { method: 'DELETE' }),
  mcp: async () => requestJson<MCPSnapshot>(`${CONTROL_ORIGIN}/api/system/mcp`),
  toggleMcp: async (serverName: string, enabled: boolean) => requestJson<MCPMutationResponse>(`${CONTROL_ORIGIN}/api/system/mcp/${encodeURIComponent(serverName)}/toggle`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled }) }),
  addMcp: async (payload: { name: string; base_url: string; transport: string; enabled: boolean; command?: string; args?: string[]; env?: Record<string, string>; headers?: Record<string, string> }) => requestJson<MCPMutationResponse>(`${CONTROL_ORIGIN}/api/system/mcp`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }),
  installMcpPreset: async (presetId: string) => requestJson<MCPMutationResponse & { error?: string }>(`${CONTROL_ORIGIN}/api/system/mcp/presets/${encodeURIComponent(presetId)}/install`, { method: 'POST', timeoutMs: MCP_OPERATION_TIMEOUT_MS }),
  removeMcp: async (serverName: string) => requestJson<{ ok: boolean }>(`${CONTROL_ORIGIN}/api/system/mcp/${encodeURIComponent(serverName)}`, { method: 'DELETE' }),
  refreshMcp: async (serverName: string) => requestJson<MCPRefreshResponse>(`${CONTROL_ORIGIN}/api/system/mcp/${encodeURIComponent(serverName)}/refresh`, { method: 'POST', timeoutMs: MCP_OPERATION_TIMEOUT_MS }),
  agentPlugins: async () => requestJson<AgentPluginsSnapshot>(`${CONTROL_ORIGIN}/api/system/agent-plugins`),
  toggleAgentPlugin: async (pluginId: string, enabled: boolean) => requestJson<AgentPluginMutationResponse>(`${CONTROL_ORIGIN}/api/system/agent-plugins/${encodeURIComponent(pluginId)}/toggle`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled }) }),
  updateAgentPluginConfig: async (pluginId: string, config: Record<string, unknown>) => requestJson<AgentPluginMutationResponse>(`${CONTROL_ORIGIN}/api/system/agent-plugins/${encodeURIComponent(pluginId)}/config`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(config) }),
  agentTrace: async () => requestJson<AgentTraceSnapshot>(`${CONTROL_ORIGIN}/api/system/agent-trace`),
  experienceMetrics: async () => requestJson<ExperienceMetricsSnapshot>(`${CONTROL_ORIGIN}/api/system/experience-metrics`),
  productMetricsConsent: async () => requestJson<{ consented: boolean; scope: string; transport: string }>(`${CONTROL_ORIGIN}/api/system/product-metrics/consent`),
  patchProductMetricsConsent: async (consented: boolean) => requestJson<{ consented: boolean; scope: string; transport: string }>(`${CONTROL_ORIGIN}/api/system/product-metrics/consent`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ consented }),
  }),
  schedules: async () => requestJson<SchedulesSnapshot>(`${CONTROL_ORIGIN}/api/system/schedules`),
  createOnceSchedule: async (payload: { name: string; prompt: string; run_after_seconds: number }) => requestJson<ScheduleMutationResponse>(`${CONTROL_ORIGIN}/api/system/schedules/once`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }),
  createIntervalSchedule: async (payload: { name: string; prompt: string; interval_seconds: number }) => requestJson<ScheduleMutationResponse>(`${CONTROL_ORIGIN}/api/system/schedules/interval`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }),
  removeSchedule: async (taskId: string) => requestJson<{ ok: boolean }>(`${CONTROL_ORIGIN}/api/system/schedules/${encodeURIComponent(taskId)}`, { method: 'DELETE' }),
  toggleSchedule: async (taskId: string, enabled: boolean) => requestJson<ScheduleMutationResponse>(`${CONTROL_ORIGIN}/api/system/schedules/${encodeURIComponent(taskId)}/toggle`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled }) }),
  runScheduleNow: async (taskId: string) => requestJson<ScheduleMutationResponse>(`${CONTROL_ORIGIN}/api/system/schedules/${encodeURIComponent(taskId)}/run`, { method: 'POST' }),
  resumeAgentRecovery: async (payload: { recovery_handle: string; workspace_id?: string; session_id: string; turn_id: string; failed_step_id: string }) =>
    requestJson<Record<string, unknown>>(`${CONTROL_ORIGIN}/api/agent/recovery/resume`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  cancelSchedule: async (taskJobOrRunId: string) => requestJson<ScheduleCancellationResponse>(`${CONTROL_ORIGIN}/api/system/schedules/${encodeURIComponent(taskJobOrRunId)}/cancel`, { method: 'POST' }),
  logs: async () => requestJson<SystemLogsSnapshot>(`${CONTROL_ORIGIN}/api/system/logs`),
  backupTargets: async () => requestJson<BackupTargetsSnapshot>(`${CONTROL_ORIGIN}/api/system/backup/targets`),
  createBackup: async () => requestJson<{ ok: boolean; backupDir: string }>(`${CONTROL_ORIGIN}/api/system/backup/create`, { method: 'POST', timeoutMs: SYSTEM_MAINTENANCE_TIMEOUT_MS }),
  restoreBackup: async (backupDir: string, dryRun = true) => requestJson<BackupRestoreResponse>(`${CONTROL_ORIGIN}/api/system/backup/restore`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ backupDir, dryRun }),
    timeoutMs: SYSTEM_MAINTENANCE_TIMEOUT_MS,
  }),
  heartbeat: async () => requestJson<HeartbeatSnapshot>(`${CONTROL_ORIGIN}/api/system/heartbeat`),
  companionRuntime: async (limit = 8) => requestJson<CompanionRuntimeSnapshot>(`${CONTROL_ORIGIN}/api/system/companion-runtime?limit=${encodeURIComponent(String(limit))}`),
  resolveCompanionOpportunity: async (jobId: string, payload: { request_id: string; outcome: 'delivered' | 'suppressed' | 'expired' | 'cancelled' | 'failed'; reason?: string }) => requestJson<{ ok: boolean }>(`${CONTROL_ORIGIN}/api/system/companion-runtime/opportunities/outcome/${encodeURIComponent(jobId)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }),
  cancelHeartbeatGoal: async (goalId: string, reason = 'cancelled') => requestJson<{ ok: boolean; goal_id: string }>(`${CONTROL_ORIGIN}/api/system/heartbeat/goals/${encodeURIComponent(goalId)}/cancel`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reason }) }),
  capabilities: async () => requestJson<CapabilitiesSnapshot>(`${CONTROL_ORIGIN}/api/system/capabilities`),
  orchestration: async () => requestJson<OrchestrationSnapshot>(`${CONTROL_ORIGIN}/api/system/orchestration`),
  importedSkills: async () => requestJson<SkillCatalogSnapshot>(`${CONTROL_ORIGIN}/api/system/skills/imported`),
  saveImportedSkills: async (items: SkillCatalogItem[]) => requestJson<SkillCatalogSnapshot>(`${CONTROL_ORIGIN}/api/system/skills/imported`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ items }) }),
  removeImportedSkills: async (ids: string[]) => requestJson<SkillCatalogSnapshot & { ok: boolean; removed: number }>(`${CONTROL_ORIGIN}/api/system/skills/imported`, { method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids }) }),
  setActiveWorkspace: async (workspaceId: string) => requestJson<{ ok: boolean; workspace_id: string; companion?: HeartbeatSnapshot['active_companion'] }>(`${CONTROL_ORIGIN}/api/system/active-workspace`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ workspace_id: workspaceId }) }),
}
