import { ref } from 'vue'
import { systemClient } from '@/api/client'
import { useDomainRequest } from '@/shared/composables/useDomainRequest'
import type {
  AgentPluginMutationResponse,
  AgentPluginsSnapshot,
  BackupRestoreResponse,
  ConnectorRegistrySnapshot,
  ConnectorDeliveryItem,
  ConnectorRecoverySnapshot,
  ConnectorProbeSnapshot,
  ConnectorAccountSnapshot,
  AgentTraceSnapshot,
  CompanionRuntimeSnapshot,
  ExperienceMetricsSnapshot,
  BackupTarget,
  DiagnosticsSnapshot,
  MCPMutationResponse,
  MCPRefreshResponse,
  MCPSnapshot,
  PermissionMutationSnapshot,
  PermissionStateSnapshot,
  ScheduleMutationResponse,
  ScheduleTask,
  SchedulesSnapshot,
  SystemLogsSnapshot,
} from '@/../shared/agent'

export function useSystemDomain() {
  const diagnostics = ref<DiagnosticsSnapshot | null>(null)
  const logs = ref<{ renderer: string | null; python: string | null; electron: string | null } | null>(null)
  const backupTargets = ref<BackupTarget[]>([])
  const backupResult = ref('')
  const permissions = ref<PermissionStateSnapshot | null>(null)
  const mcp = ref<MCPSnapshot | null>(null)
  const agentPlugins = ref<AgentPluginsSnapshot | null>(null)
  const schedules = ref<ScheduleTask[]>([])
  const agentTrace = ref<AgentTraceSnapshot | null>(null)
  const companionRuntime = ref<CompanionRuntimeSnapshot | null>(null)
  const experienceMetrics = ref<ExperienceMetricsSnapshot | null>(null)
  const connectors = ref<ConnectorRegistrySnapshot | null>(null)
  const connectorDeliveries = ref<Record<string, ConnectorDeliveryItem[]>>({})
  const connectorRecovery = ref<Record<string, ConnectorRecoverySnapshot | null>>({})
  const connectorAccounts = ref<Record<string, ConnectorAccountSnapshot>>({})
  const connectorProbes = ref<Record<string, ConnectorProbeSnapshot | null>>({})

  const diagnosticsRequest = useDomainRequest<DiagnosticsSnapshot>()
  const logsRequest = useDomainRequest<SystemLogsSnapshot>()
  const backupTargetsRequest = useDomainRequest<{ targets: BackupTarget[] }>()
  const createBackupRequest = useDomainRequest<{ backupDir: string }>()
  const restoreBackupRequest = useDomainRequest<BackupRestoreResponse>()
  const permissionsRequest = useDomainRequest<PermissionStateSnapshot>()
  const revokePermissionRequest = useDomainRequest<PermissionMutationSnapshot>()
  const clearPermissionsRequest = useDomainRequest<PermissionMutationSnapshot>()
  const mcpRequest = useDomainRequest<MCPSnapshot>()
  const toggleMcpRequest = useDomainRequest<MCPMutationResponse>()
  const addMcpRequest = useDomainRequest<MCPMutationResponse>()
  const installMcpPresetRequest = useDomainRequest<MCPMutationResponse & { error?: string }>()
  const removeMcpRequest = useDomainRequest<{ ok: boolean }>()
  const refreshMcpRequest = useDomainRequest<MCPRefreshResponse>()
  const agentPluginsRequest = useDomainRequest<AgentPluginsSnapshot>()
  const toggleAgentPluginRequest = useDomainRequest<AgentPluginMutationResponse>()
  const updateAgentPluginConfigRequest = useDomainRequest<AgentPluginMutationResponse>()
  const schedulesRequest = useDomainRequest<SchedulesSnapshot>()
  const createOnceScheduleRequest = useDomainRequest<ScheduleMutationResponse>()
  const createIntervalScheduleRequest = useDomainRequest<ScheduleMutationResponse>()
  const removeScheduleRequest = useDomainRequest<{ ok: boolean }>()
  const toggleScheduleRequest = useDomainRequest<ScheduleMutationResponse>()
  const runScheduleNowRequest = useDomainRequest<ScheduleMutationResponse>()
  const cancelScheduleRequest = useDomainRequest<{ ok: boolean }>()
  const agentTraceRequest = useDomainRequest<AgentTraceSnapshot>()
  const companionRuntimeRequest = useDomainRequest<CompanionRuntimeSnapshot>()
  const resolveCompanionOpportunityRequest = useDomainRequest<{ ok: boolean }>()
  const cancelHeartbeatGoalRequest = useDomainRequest<{ ok: boolean; goal_id: string }>()
  const experienceMetricsRequest = useDomainRequest<ExperienceMetricsSnapshot>()
  const connectorsRequest = useDomainRequest<ConnectorRegistrySnapshot>()
  const disableConnectorRequest = useDomainRequest<{ ok: boolean; connector?: ConnectorRegistrySnapshot['connectors'][number] | null; error?: string }>()
  const connectorDeliveriesRequest = useDomainRequest<{ ok: boolean; connectorId: string; items: ConnectorDeliveryItem[]; recovery?: ConnectorRecoverySnapshot | null }>()
  const retryConnectorDeliveryRequest = useDomainRequest<{ ok: boolean; alreadySent?: boolean; delivery?: ConnectorDeliveryItem }>()
  const resolveConnectorEventRequest = useDomainRequest<{ ok: boolean; alreadyResolved?: boolean; resolved?: boolean; outcome?: string; delivery?: ConnectorDeliveryItem }>()
  const cancelConnectorEventRequest = useDomainRequest<{ ok: boolean; cancelled?: boolean; outcome?: 'cancelled' | 'too_late' | 'unknown'; status?: string }>()
  const connectorAccountRequest = useDomainRequest<{ ok: boolean; account: ConnectorAccountSnapshot }>()
  const connectorProbeRequest = useDomainRequest<ConnectorProbeSnapshot>()

  const loadDiagnostics = async () => {
    const result = await diagnosticsRequest.execute(() => systemClient.diagnostics())
    if (result) {
      diagnostics.value = result
    }
  }

  const loadLogs = async () => {
    const result = await logsRequest.execute(() => systemClient.logs())
    if (result) {
      logs.value = result.logs
    }
  }

  const loadBackupTargets = async () => {
    const result = await backupTargetsRequest.execute(() => systemClient.backupTargets())
    if (result) {
      backupTargets.value = result.targets
    }
  }

  const createBackup = async () => {
    const result = await createBackupRequest.execute(() => systemClient.createBackup())
    if (result) {
      backupResult.value = result.backupDir
      await loadBackupTargets()
    }
  }

  const restoreBackup = async (backupDir: string, dryRun = true) => {
    const result = await restoreBackupRequest.execute(() => systemClient.restoreBackup(backupDir, dryRun))
    if (result && !result.dryRun) {
      await loadBackupTargets()
    }
    return result
  }

  const loadPermissions = async () => {
    const result = await permissionsRequest.execute(() => systemClient.permissions())
    if (result) {
      permissions.value = result
    }
  }

  const revokePermission = async (toolName: string) => {
    const result = await revokePermissionRequest.execute(() => systemClient.revokePermission(toolName))
    if (result) {
      permissions.value = { remembered: result.remembered, audit: result.audit }
    }
    return result
  }

  const clearPermissions = async () => {
    const result = await clearPermissionsRequest.execute(() => systemClient.clearPermissions())
    if (result) {
      permissions.value = { remembered: result.remembered, audit: result.audit }
    }
    return result
  }

  const loadMcp = async () => {
    const result = await mcpRequest.execute(() => systemClient.mcp())
    if (result) {
      mcp.value = result
    }
  }

  const toggleMcp = async (serverName: string, enabled: boolean) => {
    const result = await toggleMcpRequest.execute(() => systemClient.toggleMcp(serverName, enabled))
    if (result?.ok) {
      await loadMcp()
    }
    return result
  }

  const addMcp = async (payload: {
    name: string
    base_url: string
    transport: string
    enabled: boolean
    command?: string
    args?: string[]
    env?: Record<string, string>
    headers?: Record<string, string>
  }) => {
    const result = await addMcpRequest.execute(() => systemClient.addMcp(payload))
    if (result?.ok) {
      await loadMcp()
    }
    return result
  }

  const installMcpPreset = async (presetId: string) => {
    const result = await installMcpPresetRequest.execute(() => systemClient.installMcpPreset(presetId))
    if (result?.ok) {
      await loadMcp()
    }
    return result
  }

  const removeMcp = async (serverName: string) => {
    const result = await removeMcpRequest.execute(() => systemClient.removeMcp(serverName))
    if (result?.ok) {
      await loadMcp()
    }
    return result
  }

  const refreshMcp = async (serverName: string) => {
    const result = await refreshMcpRequest.execute(() => systemClient.refreshMcp(serverName))
    await loadMcp()
    return result
  }

  const loadSchedules = async () => {
    const result = await schedulesRequest.execute(() => systemClient.schedules())
    if (result) {
      schedules.value = result.tasks || []
    }
  }

  const loadAgentTrace = async () => {
    const result = await agentTraceRequest.execute(() => systemClient.agentTrace())
    if (result) {
      agentTrace.value = result
    }
  }

  const loadCompanionRuntime = async () => {
    const result = await companionRuntimeRequest.execute(() => systemClient.companionRuntime(32))
    if (result) {
      companionRuntime.value = result
    }
    return result
  }

  const resolveCompanionOpportunity = async (jobId: string, payload: {
    request_id: string
    outcome: 'delivered' | 'suppressed' | 'expired' | 'cancelled' | 'failed'
    reason?: string
  }) => {
    const result = await resolveCompanionOpportunityRequest.execute(() => systemClient.resolveCompanionOpportunity(jobId, payload))
    if (result?.ok) {
      await loadCompanionRuntime()
    }
    return result
  }

  const cancelHeartbeatGoal = async (goalId: string, reason = 'cancelled') => {
    const result = await cancelHeartbeatGoalRequest.execute(() => systemClient.cancelHeartbeatGoal(goalId, reason))
    if (result?.ok) await loadCompanionRuntime()
    return result
  }

  const loadExperienceMetrics = async () => {
    const result = await experienceMetricsRequest.execute(() => systemClient.experienceMetrics())
    if (result) {
      experienceMetrics.value = result
    }
  }

  const loadConnectors = async () => {
    const result = await connectorsRequest.execute(() => systemClient.connectors())
    if (result) connectors.value = result
    return result
  }

  const disableConnector = async (connectorId: string) => {
    const result = await disableConnectorRequest.execute(() => systemClient.disableConnector(connectorId))
    if (result?.ok) await loadConnectors()
    return result
  }

  const loadConnectorDeliveries = async (connectorId: 'telegram' | 'discord' | 'qq' | 'wechat') => {
    const result = await connectorDeliveriesRequest.execute(() => systemClient.connectorDeliveries(connectorId, 20))
    if (result) {
      connectorDeliveries.value[connectorId] = result.items || []
      connectorRecovery.value[connectorId] = result.recovery || null
    }
    return result
  }

  const retryConnectorDelivery = async (connectorId: 'telegram' | 'discord' | 'qq' | 'wechat', deliveryKey: string) => {
    const result = await retryConnectorDeliveryRequest.execute(() => systemClient.retryConnectorDelivery(connectorId, deliveryKey))
    if (result?.ok) await loadConnectorDeliveries(connectorId)
    return result
  }

  const resolveConnectorEvent = async (connectorId: 'telegram' | 'discord' | 'qq' | 'wechat', eventId: string, outcome: 'delivered' | 'failed') => {
    const result = await resolveConnectorEventRequest.execute(() => systemClient.resolveConnectorEvent(connectorId, eventId, outcome))
    if (result?.ok) await loadConnectorDeliveries(connectorId)
    return result
  }

  const cancelConnectorEvent = async (connectorId: 'telegram' | 'discord' | 'qq' | 'wechat', eventId: string) => {
    const result = await cancelConnectorEventRequest.execute(() => systemClient.cancelConnectorEvent(connectorId, eventId))
    await loadConnectorDeliveries(connectorId)
    return result
  }

  const loadConnectorAccount = async (connectorId: 'qq' | 'wechat') => {
    const result = await connectorAccountRequest.execute(() => systemClient.connectorAccount(connectorId))
    if (result?.account) connectorAccounts.value[connectorId] = result.account
    return result?.account
  }

  const probeConnector = async (connectorId: 'telegram' | 'discord' | 'qq' | 'wechat') => {
    const result = await connectorProbeRequest.execute(() => systemClient.probeConnector(connectorId))
    if (result) connectorProbes.value[connectorId] = result
    return result
  }

  const loginConnectorAccount = async (connectorId: 'qq' | 'wechat') => {
    const result = await connectorAccountRequest.execute(() => systemClient.loginConnectorAccount(connectorId))
    if (result?.account) connectorAccounts.value[connectorId] = result.account
    return result?.account
  }

  const refreshConnectorAccount = async (connectorId: 'qq' | 'wechat') => {
    const result = await connectorAccountRequest.execute(() => systemClient.refreshConnectorAccount(connectorId))
    if (result?.account) connectorAccounts.value[connectorId] = result.account
    return result?.account
  }

  const logoutConnectorAccount = async (connectorId: 'qq' | 'wechat') => {
    const result = await connectorAccountRequest.execute(() => systemClient.logoutConnectorAccount(connectorId))
    if (result?.account) connectorAccounts.value[connectorId] = result.account
    return result?.account
  }

  const loadAgentPlugins = async () => {
    const result = await agentPluginsRequest.execute(() => systemClient.agentPlugins())
    if (result) {
      agentPlugins.value = result
    }
  }

  const toggleAgentPlugin = async (pluginId: string, enabled: boolean) => {
    const result = await toggleAgentPluginRequest.execute(() => systemClient.toggleAgentPlugin(pluginId, enabled))
    if (result?.ok) {
      await loadAgentPlugins()
    }
    return result
  }

  const updateAgentPluginConfig = async (pluginId: string, config: Record<string, unknown>) => {
    const result = await updateAgentPluginConfigRequest.execute(() => systemClient.updateAgentPluginConfig(pluginId, config))
    if (result?.ok) {
      await loadAgentPlugins()
    }
    return result
  }

  const createOnceSchedule = async (payload: { name: string; prompt: string; run_after_seconds: number }) => {
    const result = await createOnceScheduleRequest.execute(() => systemClient.createOnceSchedule(payload))
    if (result?.ok) {
      await loadSchedules()
    }
    return result
  }

  const createIntervalSchedule = async (payload: { name: string; prompt: string; interval_seconds: number }) => {
    const result = await createIntervalScheduleRequest.execute(() => systemClient.createIntervalSchedule(payload))
    if (result?.ok) {
      await loadSchedules()
    }
    return result
  }

  const removeSchedule = async (taskId: string) => {
    const result = await removeScheduleRequest.execute(() => systemClient.removeSchedule(taskId))
    if (result?.ok) {
      await loadSchedules()
    }
    return result
  }

  const toggleSchedule = async (taskId: string, enabled: boolean) => {
    const result = await toggleScheduleRequest.execute(() => systemClient.toggleSchedule(taskId, enabled))
    if (result?.ok) {
      await loadSchedules()
    }
    return result
  }

  const runScheduleNow = async (taskId: string) => {
    const result = await runScheduleNowRequest.execute(() => systemClient.runScheduleNow(taskId))
    if (result?.ok) {
      await loadSchedules()
    }
    return result
  }

  const cancelSchedule = async (taskOrJobId: string) => {
    const result = await cancelScheduleRequest.execute(() => systemClient.cancelSchedule(taskOrJobId))
    if (result?.ok) {
      await loadSchedules()
    }
    return result
  }

  return {
    diagnostics,
    logs,
    backupTargets,
    backupResult,
    permissions,
    mcp,
    agentPlugins,
    schedules,
    agentTrace,
    companionRuntime,
    experienceMetrics,
    connectors,
    connectorDeliveries,
    connectorRecovery,
    connectorAccounts,
    connectorProbes,
    diagnosticsRequest,
    logsRequest,
    backupTargetsRequest,
    createBackupRequest,
    restoreBackupRequest,
    permissionsRequest,
    revokePermissionRequest,
    clearPermissionsRequest,
    mcpRequest,
    toggleMcpRequest,
    addMcpRequest,
    installMcpPresetRequest,
    removeMcpRequest,
    refreshMcpRequest,
    agentPluginsRequest,
    toggleAgentPluginRequest,
    updateAgentPluginConfigRequest,
    schedulesRequest,
    createOnceScheduleRequest,
    createIntervalScheduleRequest,
    removeScheduleRequest,
    toggleScheduleRequest,
    runScheduleNowRequest,
    cancelScheduleRequest,
    agentTraceRequest,
    companionRuntimeRequest,
    resolveCompanionOpportunityRequest,
    cancelHeartbeatGoalRequest,
    experienceMetricsRequest,
    connectorsRequest,
    disableConnectorRequest,
    connectorDeliveriesRequest,
    retryConnectorDeliveryRequest,
    resolveConnectorEventRequest,
    cancelConnectorEventRequest,
    connectorAccountRequest,
    connectorProbeRequest,
    loadDiagnostics,
    loadLogs,
    loadBackupTargets,
    createBackup,
    restoreBackup,
    loadPermissions,
    revokePermission,
    clearPermissions,
    loadMcp,
    toggleMcp,
    addMcp,
    installMcpPreset,
    removeMcp,
    refreshMcp,
    loadAgentPlugins,
    toggleAgentPlugin,
    updateAgentPluginConfig,
    loadSchedules,
    loadAgentTrace,
    loadCompanionRuntime,
    loadExperienceMetrics,
    loadConnectors,
    loadConnectorDeliveries,
    retryConnectorDelivery,
    resolveConnectorEvent,
    cancelConnectorEvent,
    loadConnectorAccount,
    probeConnector,
    loginConnectorAccount,
    refreshConnectorAccount,
    logoutConnectorAccount,
    disableConnector,
    createOnceSchedule,
    createIntervalSchedule,
    removeSchedule,
    toggleSchedule,
    runScheduleNow,
    cancelSchedule,
    resolveCompanionOpportunity,
    cancelHeartbeatGoal,
  }
}
