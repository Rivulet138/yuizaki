import { CONTROL_ORIGIN, requestBlob, requestJson } from './http-client'
import type {
  AgentPluginMutationResponse,
  AgentPluginsSnapshot,
  BackupRestoreResponse,
  ConnectorRegistrySnapshot,
  PlatformCapabilitySnapshot,
  VoiceDiagnosticsSnapshot,
  ConnectorDeliverySnapshot,
  ConnectorAccountSnapshot,
  MessageConnectorConfigSnapshot,
  MessageConnectorConfigUpdate,
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
  ProviderRegistrySnapshot,
  ConnectorRecoverySnapshot,
  ConnectorProbeSnapshot,
} from '@/../shared/agent'
import type { CapabilitiesSnapshot, SkillCatalogItem, SkillCatalogSnapshot, StreamActionsSnapshot, StreamDraftConsumeResponse, StreamDraftConsumerSnapshot, StreamDraftGenerateResponse, StreamDraftsSnapshot, StreamEventsSnapshot, StreamExecuteResponse, StreamModerationPolicySnapshot, StreamObsProfilesResponse, StreamPreviewResponse, StreamProbeResponse, StreamRuntimeSnapshot, StreamTakeoverResponse } from '@/../shared/capability'
import type { OrchestrationSnapshot } from '@/../shared/orchestration'

const SYSTEM_MAINTENANCE_TIMEOUT_MS = 30 * 60 * 1000
const MCP_OPERATION_TIMEOUT_MS = 2 * 60 * 1000

type RawConnectorDelivery = {
  delivery_key?: unknown
  idempotency_key?: unknown
  connector_id?: unknown
  event_id?: unknown
  status?: unknown
  attempt_count?: unknown
  last_error?: unknown
  updated_at?: unknown
  delivered_at?: unknown
  resolvable?: unknown
}

type RawConnectorRecovery = {
  schemaVersion?: unknown
  runs?: unknown
  inspected?: unknown
  recovered?: unknown
  failed?: unknown
  lastRunAt?: unknown
  lastError?: unknown
}

export interface UiCapabilitiesSnapshot {
  schemaVersion: string
  protocol: {
    http: boolean
    socketIo: boolean
    openapi: string
  }
  clients: {
    browser: UiClientCapabilities
    electron: UiClientCapabilities
  }
  browserPlatform: Record<string, unknown>
}

export interface UiClientCapabilities {
  mode: 'browser' | 'electron'
  coreRoutes: string[]
  hostCapabilities: {
    windowControls: boolean
    desktopActions: boolean
    screenCapture: boolean
    localFilePicker: boolean
  }
  limitations: string[]
}

const boundedCount = (value: unknown) => {
  const count = Number(value)
  return Number.isInteger(count) && count >= 0 && count <= 10_000_000 ? count : 0
}

const boundedText = (value: unknown, maxLength: number) => (
  value == null ? '' : String(value).slice(0, maxLength)
)

const boundedTimestamp = (value: unknown, fallback: number | null) => {
  const timestamp = Number(value)
  return Number.isFinite(timestamp) && timestamp >= 0 ? timestamp : fallback
}

const normalizeConnectorRecovery = (value: unknown): ConnectorRecoverySnapshot | null => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const row = value as RawConnectorRecovery
  const lastRunAt = Number(row.lastRunAt)
  return {
    schemaVersion: String(row.schemaVersion || 'yuizaki.connector-recovery.v1'),
    runs: boundedCount(row.runs),
    inspected: boundedCount(row.inspected),
    recovered: boundedCount(row.recovered),
    failed: boundedCount(row.failed),
    lastRunAt: Number.isFinite(lastRunAt) && lastRunAt >= 0 ? lastRunAt : null,
    lastError: row.lastError == null ? null : String(row.lastError).slice(0, 160),
  }
}

const normalizeConnectorDelivery = (row: RawConnectorDelivery): ConnectorDeliveryItem => {
  const status = boundedText(row.status || 'unknown', 40)
  return {
  deliveryKey: boundedText(row.delivery_key, 256),
  idempotencyKey: boundedText(row.idempotency_key, 256),
  connectorId: boundedText(row.connector_id, 80),
  eventId: boundedText(row.event_id, 256),
  status,
  attemptCount: boundedCount(row.attempt_count),
  lastError: row.last_error == null ? null : boundedText(row.last_error, 160),
  updatedAt: boundedTimestamp(row.updated_at, 0) ?? 0,
  deliveredAt: row.delivered_at == null ? null : boundedTimestamp(row.delivered_at, null),
  retryable: status === 'failed',
  cancellable: status === 'processing',
  resolvable: row.resolvable === true,
  }
}

export const systemClient = {
  uiCapabilities: async () => requestJson<UiCapabilitiesSnapshot>(`${CONTROL_ORIGIN}/api/system/ui-capabilities`),
  pythonHealth: async () => {
    return requestJson(`${CONTROL_ORIGIN}/api/ping`)
  },
  activeApplication: async () => requestJson<{
    ok: boolean
    name: string
    title: string
    process_id: number
  }>(`${CONTROL_ORIGIN}/api/perception/active-application`),
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
  stream: async () => requestJson<StreamRuntimeSnapshot>(`${CONTROL_ORIGIN}/api/system/stream`),
  streamModeration: async () => requestJson<{ ok: boolean; moderation: StreamModerationPolicySnapshot }>(`${CONTROL_ORIGIN}/api/system/stream/moderation`),
  updateStreamModeration: async (payload: { enabled?: boolean; blockedTerms?: string[]; slowModeSeconds?: number; maxMessagesPerMinute?: number }) => requestJson<{ ok: boolean; moderation: StreamModerationPolicySnapshot; state?: StreamRuntimeSnapshot }>(`${CONTROL_ORIGIN}/api/system/stream/moderation`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  probeStream: async () => requestJson<StreamProbeResponse>(`${CONTROL_ORIGIN}/api/system/stream/probe`, { method: 'POST' }),
  obsProfiles: async () => requestJson<StreamObsProfilesResponse>(`${CONTROL_ORIGIN}/api/system/stream/obs/profiles`),
  configureObs: async (payload: { endpoint: string; password?: string; allowRemote?: boolean; clearPassword?: boolean }) => requestJson<Record<string, unknown>>(`${CONTROL_ORIGIN}/api/system/stream/obs`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  streamEvents: async (limit = 20) => requestJson<StreamEventsSnapshot>(`${CONTROL_ORIGIN}/api/system/stream/events?limit=${encodeURIComponent(String(limit))}`),
  streamActions: async (limit = 20) => requestJson<StreamActionsSnapshot>(`${CONTROL_ORIGIN}/api/system/stream/actions?limit=${encodeURIComponent(String(limit))}`),
  twitchConfig: async () => requestJson<{
    ok: boolean
    schemaVersion: string
    secureStorageAvailable: boolean
    configured: Record<string, boolean>
    subscriptionProvider: string
  }>(`${CONTROL_ORIGIN}/api/system/stream/twitch/config`),
  updateTwitchConfig: async (payload: Record<string, unknown>) => requestJson<Record<string, unknown>>(`${CONTROL_ORIGIN}/api/system/stream/twitch/config`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }),
  probeTwitch: async () => requestJson<Record<string, unknown>>(`${CONTROL_ORIGIN}/api/system/stream/twitch/probe`, { method: 'POST' }),
  reconfigureTwitch: async () => requestJson<Record<string, unknown>>(`${CONTROL_ORIGIN}/api/system/stream/twitch/reconfigure`, { method: 'POST' }),
  configureTwitchSubscriptions: async (subscriptions: string[]) => requestJson<Record<string, unknown>>(`${CONTROL_ORIGIN}/api/system/stream/twitch/subscriptions`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ subscriptions }),
  }),
  connectTwitch: async () => requestJson<Record<string, unknown>>(`${CONTROL_ORIGIN}/api/system/stream/twitch/connect`, { method: 'POST' }),
  disconnectTwitch: async () => requestJson<Record<string, unknown>>(`${CONTROL_ORIGIN}/api/system/stream/twitch/disconnect`, { method: 'POST' }),
  tickTwitch: async () => requestJson<Record<string, unknown>>(`${CONTROL_ORIGIN}/api/system/stream/twitch/tick`, { method: 'POST' }),
  streamDrafts: async (limit = 20) => requestJson<StreamDraftsSnapshot>(`${CONTROL_ORIGIN}/api/system/stream/drafts?limit=${encodeURIComponent(String(limit))}`),
  generateStreamDraft: async (payload: { eventId: string; workspaceId?: string; sessionId?: string; retry?: boolean }) => requestJson<StreamDraftGenerateResponse>(`${CONTROL_ORIGIN}/api/system/stream/drafts`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  consumeStreamDrafts: async (payload: { limit?: number; workspaceId?: string; sessionId?: string } = {}) => requestJson<StreamDraftConsumeResponse>(`${CONTROL_ORIGIN}/api/system/stream/drafts/consume`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  streamDraftConsumer: async () => requestJson<StreamDraftConsumerSnapshot>(`${CONTROL_ORIGIN}/api/system/stream/draft-consumer`),
  setStreamDraftConsumer: async (enabled: boolean) => requestJson<StreamDraftConsumerSnapshot>(`${CONTROL_ORIGIN}/api/system/stream/draft-consumer`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled }),
  }),
  createStreamEvent: async (payload: { kind: 'chat' | 'caption'; text: string; author?: string }) => requestJson<StreamEventsSnapshot>(`${CONTROL_ORIGIN}/api/system/stream/events`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  setStreamTakeover: async (enabled: boolean) => requestJson<StreamTakeoverResponse>(`${CONTROL_ORIGIN}/api/system/stream/takeover`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled }),
  }),
  previewStream: async (action: string, params: Record<string, unknown> = {}) => requestJson<StreamPreviewResponse>(`${CONTROL_ORIGIN}/api/system/stream/preview`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, params }),
  }),
  executeStream: async (payload: { requestId: string; action: string; params: Record<string, unknown>; confirmed: true }) => requestJson<StreamExecuteResponse>(`${CONTROL_ORIGIN}/api/system/stream/execute`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),
  providers: async () => requestJson<ProviderRegistrySnapshot>(`${CONTROL_ORIGIN}/api/system/providers`),
  voiceDiagnostics: async () => requestJson<VoiceDiagnosticsSnapshot>(`${CONTROL_ORIGIN}/api/system/voice-diagnostics`),
  beginVoiceDiagnosticsRun: async (runId?: string) => requestJson<{
    ok: boolean
    run_id: string
    sample_count: number
    schemaVersion: string
  }>(`${CONTROL_ORIGIN}/api/system/voice-diagnostics/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(runId ? { run_id: runId } : {}),
  }),
  recordVoiceComfort: async (payload: {
    scenario: string
    stop_audio_latency_ms?: number | null
    interrupt_ack_latency_ms?: number | null
    false_interruption?: boolean
    first_audio_latency_ms?: number | null
    continuous_turn_completed?: boolean | null
    run_id?: string | null
  }) => requestJson<Record<string, unknown>>(`${CONTROL_ORIGIN}/api/system/voice-diagnostics/comfort`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }),
  recordVoiceComfortSignal: async (payload: {
    signal: 'hesitation' | 'backchannel' | 'background_speech'
    source: 'provider_vad' | 'local_vad' | 'classifier'
    confidence: number
    duration_ms?: number | null
    run_id?: string | null
  }) => requestJson<{
    ok: boolean
    accepted: boolean
    signal: string
    source: string
    sample_count: number
    signal_counts: Record<string, number>
  }>(`${CONTROL_ORIGIN}/api/system/voice-diagnostics/comfort-signal`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }),
  recordVoiceDiagnosticSample: async (payload: {
    stage: string
    latency_ms: number
    ok?: boolean
    provider?: string | null
    error_kind?: string | null
    recovered?: boolean | null
    recovery_latency_ms?: number | null
    playback_underruns?: number | null
    run_id?: string | null
  }) => requestJson<{ ok: boolean; accepted: boolean; stage: string }>(`${CONTROL_ORIGIN}/api/system/voice-diagnostics/sample`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }),
  connectors: async () => requestJson<ConnectorRegistrySnapshot>(`${CONTROL_ORIGIN}/api/system/connectors`),
  platforms: async () => requestJson<PlatformCapabilitySnapshot>(`${CONTROL_ORIGIN}/api/system/platforms`),
  disableConnector: async (connectorId: string) => requestJson<{ ok: boolean; connector?: ConnectorRegistrySnapshot['connectors'][number] | null; error?: string }>(`${CONTROL_ORIGIN}/api/system/connectors/${encodeURIComponent(connectorId)}/disable`, { method: 'POST' }),
  connectorConfig: async (connectorId: MessageConnectorConfigSnapshot['id']) => requestJson<MessageConnectorConfigSnapshot>(`${CONTROL_ORIGIN}/api/system/connectors/${encodeURIComponent(connectorId)}/config`),
  probeConnector: async (connectorId: MessageConnectorConfigSnapshot['id']) => requestJson<ConnectorProbeSnapshot>(`${CONTROL_ORIGIN}/api/system/connectors/${encodeURIComponent(connectorId)}/probe`, { method: 'POST' }),
  updateConnectorConfig: async (connectorId: MessageConnectorConfigSnapshot['id'], payload: MessageConnectorConfigUpdate) => requestJson<{ ok: boolean; config: MessageConnectorConfigSnapshot }>(`${CONTROL_ORIGIN}/api/system/connectors/${encodeURIComponent(connectorId)}/config`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }),
  connectorAccount: async (connectorId: 'qq' | 'wechat') => requestJson<{ ok: boolean; account: ConnectorAccountSnapshot }>(`${CONTROL_ORIGIN}/api/system/connectors/${encodeURIComponent(connectorId)}/account`),
  loginConnectorAccount: async (connectorId: 'qq' | 'wechat') => requestJson<{ ok: boolean; account: ConnectorAccountSnapshot }>(`${CONTROL_ORIGIN}/api/system/connectors/${encodeURIComponent(connectorId)}/account/login`, { method: 'POST' }),
  refreshConnectorAccount: async (connectorId: 'qq' | 'wechat') => requestJson<{ ok: boolean; account: ConnectorAccountSnapshot }>(`${CONTROL_ORIGIN}/api/system/connectors/${encodeURIComponent(connectorId)}/account/status`),
  logoutConnectorAccount: async (connectorId: 'qq' | 'wechat') => requestJson<{ ok: boolean; account: ConnectorAccountSnapshot }>(`${CONTROL_ORIGIN}/api/system/connectors/${encodeURIComponent(connectorId)}/account/logout`, { method: 'POST' }),
  unbindConnectorAccount: async (connectorId: 'qq' | 'wechat') => requestJson<{ ok: boolean; account: ConnectorAccountSnapshot; config: MessageConnectorConfigSnapshot }>(`${CONTROL_ORIGIN}/api/system/connectors/${encodeURIComponent(connectorId)}/account`, { method: 'DELETE' }),
  connectorDeliveries: async (connectorId: MessageConnectorConfigSnapshot['id'], limit = 20) => {
    const result = await requestJson<{ ok: boolean; connector_id: string; items: RawConnectorDelivery[]; recovery?: RawConnectorRecovery | null }>(`${CONTROL_ORIGIN}/api/system/connectors/${encodeURIComponent(connectorId)}/deliveries?limit=${encodeURIComponent(String(limit))}`)
    return { ok: result.ok, connectorId: result.connector_id, items: (result.items || []).map(normalizeConnectorDelivery), recovery: normalizeConnectorRecovery(result.recovery) } satisfies ConnectorDeliverySnapshot
  },
  retryConnectorDelivery: async (connectorId: MessageConnectorConfigSnapshot['id'], deliveryKey: string) => {
    const result = await requestJson<{ ok: boolean; already_sent?: boolean; delivery?: RawConnectorDelivery }>(`${CONTROL_ORIGIN}/api/system/connectors/${encodeURIComponent(connectorId)}/deliveries/${encodeURIComponent(deliveryKey)}/retry`, { method: 'POST' })
    return {
      ok: result.ok,
      alreadySent: result.already_sent,
      delivery: result.delivery ? normalizeConnectorDelivery(result.delivery) : undefined,
    }
  },
  resolveConnectorEvent: async (connectorId: MessageConnectorConfigSnapshot['id'], eventId: string, outcome: 'delivered' | 'failed') => {
    const result = await requestJson<{ ok: boolean; already_resolved?: boolean; resolved?: boolean; outcome?: string; delivery?: RawConnectorDelivery }>(`${CONTROL_ORIGIN}/api/system/connectors/${encodeURIComponent(connectorId)}/events/${encodeURIComponent(eventId)}/resolve`, {
      method: 'POST',
      body: JSON.stringify({ outcome }),
      headers: { 'Content-Type': 'application/json' },
    })
    return {
      ok: result.ok,
      alreadyResolved: result.already_resolved === true,
      resolved: result.resolved === true,
      outcome: result.outcome,
      delivery: result.delivery ? normalizeConnectorDelivery(result.delivery) : undefined,
    }
  },
  cancelConnectorEvent: async (connectorId: MessageConnectorConfigSnapshot['id'], eventId: string) =>
    requestJson<{ ok: boolean; cancelled?: boolean; outcome?: 'cancelled' | 'too_late' | 'unknown'; status?: string }>(`${CONTROL_ORIGIN}/api/system/connectors/${encodeURIComponent(connectorId)}/events/${encodeURIComponent(eventId)}/cancel`, { method: 'POST' }),
  orchestration: async () => requestJson<OrchestrationSnapshot>(`${CONTROL_ORIGIN}/api/system/orchestration`),
  importedSkills: async () => requestJson<SkillCatalogSnapshot>(`${CONTROL_ORIGIN}/api/system/skills/imported`),
  saveImportedSkills: async (items: SkillCatalogItem[]) => requestJson<SkillCatalogSnapshot>(`${CONTROL_ORIGIN}/api/system/skills/imported`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ items }) }),
  removeImportedSkills: async (ids: string[]) => requestJson<SkillCatalogSnapshot & { ok: boolean; removed: number }>(`${CONTROL_ORIGIN}/api/system/skills/imported`, { method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids }) }),
  setActiveWorkspace: async (workspaceId: string) => requestJson<{ ok: boolean; workspace_id: string; companion?: HeartbeatSnapshot['active_companion'] }>(`${CONTROL_ORIGIN}/api/system/active-workspace`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ workspace_id: workspaceId }) }),
}
