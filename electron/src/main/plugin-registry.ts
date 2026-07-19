import path from 'node:path'
import type {
  DesktopPetPlugin,
  PluginActiveExecution,
  PluginAuditRecord,
  PluginContributionSummary,
  PluginLoadFailure,
  PluginManifestValidationIssue,
  PluginModelProviderContribution,
  PluginRegistrySnapshot,
  PluginRouteContribution,
  PluginRuntimeState,
  PluginToolCapabilityContribution,
} from '../shared/plugin'

interface ExecutionController {
  invocationId: string
  pluginId: string
  routeId: string
  startedAt: string
  timeoutMs: number
  token: {
    aborted: boolean
    reason?: 'cancelled' | 'timeout'
  }
  cancel: (reason: 'cancelled' | 'timeout') => void
}

const createEmptyStats = () => ({
  totalInvocations: 0,
  okCount: 0,
  errorCount: 0,
  timeoutCount: 0,
  deniedCount: 0,
  cancelledCount: 0,
})

const toActiveExecution = (execution: ExecutionController): PluginActiveExecution => ({
  invocationId: execution.invocationId,
  routeId: execution.routeId,
  startedAt: execution.startedAt,
  timeoutMs: execution.timeoutMs,
  status: execution.token.reason === 'timeout' ? 'timed_out' : execution.token.reason === 'cancelled' ? 'cancelled' : 'running',
})

const toPublicRoute = (route: PluginRouteContribution): PluginRouteContribution => {
  const { handler: _handler, ...publicRoute } = route
  return { ...publicRoute }
}

const toPublicModelProvider = (provider: PluginModelProviderContribution): PluginModelProviderContribution => {
  if (typeof provider.assetPath === 'string' && path.isAbsolute(provider.assetPath)) {
    const { assetPath: _assetPath, ...publicProvider } = provider
    return { ...publicProvider }
  }
  return { ...provider }
}

const toPublicToolCapability = (tool: PluginToolCapabilityContribution): PluginToolCapabilityContribution => ({
  ...tool,
  ...(tool.scopes ? { scopes: [...tool.scopes] } : {}),
  ...(tool.tags ? { tags: [...tool.tags] } : {}),
})

const toPublicPlugin = (plugin: DesktopPetPlugin): DesktopPetPlugin => {
  const {
    manifestPath: _manifestPath,
    routes,
    modelProviders,
    toolCapabilities,
    petEvents,
    ...publicPlugin
  } = plugin
  const result: DesktopPetPlugin = {
    ...publicPlugin,
    permissions: {
      routes: [...plugin.permissions.routes],
      toolScopes: [...plugin.permissions.toolScopes],
      modelScopes: [...plugin.permissions.modelScopes],
      ...(plugin.permissions.agentBridge === true ? { agentBridge: true } : {}),
      ...(plugin.permissions.allowedHosts ? { allowedHosts: [...plugin.permissions.allowedHosts] } : {}),
      ...(plugin.permissions.allowedPaths ? { allowedPaths: [...plugin.permissions.allowedPaths] } : {}),
      ...(plugin.permissions.allowedCommands ? { allowedCommands: [...plugin.permissions.allowedCommands] } : {}),
    },
    execution: { ...plugin.execution },
  }
  if (routes) {
    result.routes = routes.map(toPublicRoute)
  }
  if (modelProviders) {
    result.modelProviders = modelProviders.map(toPublicModelProvider)
  }
  if (toolCapabilities) {
    result.toolCapabilities = toolCapabilities.map(toPublicToolCapability)
  }
  if (petEvents) {
    result.petEvents = petEvents.map((event) => ({ ...event }))
  }
  return result
}

const toPublicLoadFailure = (failure: PluginLoadFailure): PluginLoadFailure => ({
  ...failure,
  manifestPath: path.basename(failure.manifestPath),
  validationIssues: failure.validationIssues.map((issue) => ({ ...issue })),
})

export class PluginRegistry {
  private readonly plugins: DesktopPetPlugin[] = []
  private readonly auditLog: PluginAuditRecord[] = []
  private readonly loadFailures: PluginLoadFailure[] = []
  private readonly runtimeStates = new Map<string, PluginRuntimeState>()
  private readonly activeExecutions = new Map<string, Map<string, ExecutionController>>()

  register(plugin: DesktopPetPlugin, validationIssues: PluginManifestValidationIssue[] = []): void {
    if (this.plugins.some((item) => item.id === plugin.id)) {
      return
    }

    this.plugins.push(plugin)
    const loadedAt = new Date().toISOString()
    this.runtimeStates.set(plugin.id, {
      pluginId: plugin.id,
      status: validationIssues.length > 0 ? 'degraded' : 'loaded',
      executionIsolation: 'node-permission-process',
      loadedAt,
      validationIssues: [...validationIssues],
      activeExecutions: [],
      stats: createEmptyStats(),
    })
  }

  snapshot(): PluginRegistrySnapshot {
    const contributionSummary: PluginContributionSummary[] = [
      {
        category: 'capability',
        count: this.plugins.flatMap((plugin) => [...(plugin.toolCapabilities ?? []), ...(plugin.modelProviders ?? [])]).length,
        items: this.plugins.flatMap((plugin) => [
          ...(plugin.toolCapabilities ?? []).map((item) => item.id),
          ...(plugin.modelProviders ?? []).map((item) => item.id),
        ]),
      },
      {
        category: 'event',
        count: this.plugins.flatMap((plugin) => plugin.petEvents ?? []).length
          + this.auditLog.filter((item) => item.routeId === 'proactive_dispatch').length,
        items: [
          ...this.plugins.flatMap((plugin) => (plugin.petEvents ?? []).map((item) => `${plugin.id}:${item.event}`)),
          ...this.auditLog.filter((item) => item.routeId === 'proactive_dispatch').map((item) => item.pluginId),
        ],
      },
      {
        category: 'policy',
        count: this.plugins.filter((plugin) => plugin.permissions.toolScopes.length > 0 || plugin.permissions.routes.length > 0 || plugin.permissions.modelScopes.length > 0).length,
        items: this.plugins
          .filter((plugin) => plugin.permissions.toolScopes.length > 0 || plugin.permissions.routes.length > 0 || plugin.permissions.modelScopes.length > 0)
          .map((plugin) => plugin.id),
      },
    ]

    return {
      plugins: this.plugins.map(toPublicPlugin),
      routes: this.plugins.flatMap((plugin) => (plugin.routes ?? []).map(toPublicRoute)),
      modelProviders: this.plugins.flatMap((plugin) => (plugin.modelProviders ?? []).map(toPublicModelProvider)),
      toolCapabilities: this.plugins.flatMap((plugin) => plugin.toolCapabilities ?? []),
      contributionSummary,
      pluginStates: [...this.runtimeStates.values()].map((state) => ({
        ...state,
        validationIssues: [...state.validationIssues],
        activeExecutions: state.activeExecutions.map((execution) => ({ ...execution })),
        stats: { ...state.stats },
      })),
      loadFailures: this.loadFailures.map(toPublicLoadFailure),
      audit: [...this.auditLog],
    }
  }

  getPluginById(pluginId: string): DesktopPetPlugin | undefined {
    return this.plugins.find((plugin) => plugin.id === pluginId)
  }

  recordAudit(entry: PluginAuditRecord): void {
    this.auditLog.unshift(entry)
    if (this.auditLog.length > 200) {
      this.auditLog.length = 200
    }

    const state = this.runtimeStates.get(entry.pluginId)
    if (!state) {
      return
    }

    state.lastAuditAt = entry.timestamp
    state.stats.totalInvocations += 1

    switch (entry.status) {
      case 'ok':
        state.stats.okCount += 1
        if (entry.detail) {
          state.lastError = entry.detail
        } else {
          delete state.lastError
        }
        if (state.status !== 'blocked') {
          state.status = state.validationIssues.length > 0 ? 'degraded' : 'loaded'
        }
        break
      case 'error':
        state.stats.errorCount += 1
        if (entry.detail) {
          state.lastError = entry.detail
        } else {
          delete state.lastError
        }
        state.status = 'error'
        break
      case 'timeout':
        state.stats.timeoutCount += 1
        if (entry.detail) {
          state.lastError = entry.detail
        } else {
          delete state.lastError
        }
        state.status = 'degraded'
        break
      case 'denied':
        state.stats.deniedCount += 1
        if (entry.detail) {
          state.lastError = entry.detail
        } else {
          delete state.lastError
        }
        state.status = 'blocked'
        break
      case 'cancelled':
        state.stats.cancelledCount += 1
        if (entry.detail) {
          state.lastError = entry.detail
        } else {
          delete state.lastError
        }
        state.status = 'degraded'
        break
    }
  }

  getAuditLog(): PluginAuditRecord[] {
    return [...this.auditLog]
  }

  recordLoadFailure(failure: PluginLoadFailure): void {
    this.loadFailures.unshift(failure)
    if (this.loadFailures.length > 100) {
      this.loadFailures.length = 100
    }
  }

  getActiveExecutionCount(pluginId: string): number {
    return this.activeExecutions.get(pluginId)?.size ?? 0
  }

  startExecution(pluginId: string, routeId: string, timeoutMs: number): {
    invocationId: string
    cancellationToken: { aborted: boolean; reason?: 'cancelled' | 'timeout' }
    cancellationPromise: Promise<never>
  } {
    const invocationId = `${pluginId}:${routeId}:${Date.now()}:${Math.random().toString(36).slice(2, 8)}`
    let cancel!: (reason: 'cancelled' | 'timeout') => void
    const token: { aborted: boolean; reason?: 'cancelled' | 'timeout' } = { aborted: false }
    const cancellationPromise = new Promise<never>((_, reject) => {
      cancel = (reason) => {
        token.aborted = true
        token.reason = reason
        reject(new Error(reason === 'timeout' ? 'Plugin route execution timeout' : 'Plugin route execution cancelled'))
      }
    })

    const execution: ExecutionController = {
      invocationId,
      pluginId,
      routeId,
      startedAt: new Date().toISOString(),
      timeoutMs,
      token,
      cancel,
    }

    const executions = this.activeExecutions.get(pluginId) ?? new Map<string, ExecutionController>()
    executions.set(invocationId, execution)
    this.activeExecutions.set(pluginId, executions)

    const state = this.runtimeStates.get(pluginId)
    if (state) {
      state.activeExecutions = [...executions.values()].map(toActiveExecution)
    }

    return {
      invocationId,
      cancellationToken: token,
      cancellationPromise,
    }
  }

  cancelExecution(pluginId: string, invocationId: string, reason: 'cancelled' | 'timeout' = 'cancelled'): boolean {
    const executions = this.activeExecutions.get(pluginId)
    const execution = executions?.get(invocationId)
    if (!execution || execution.token.aborted) {
      return false
    }

    execution.cancel(reason)
    const state = this.runtimeStates.get(pluginId)
    if (state) {
      state.activeExecutions = [...(executions?.values() ?? [])].map(toActiveExecution)
    }
    return true
  }

  finishExecution(pluginId: string, invocationId: string): void {
    const executions = this.activeExecutions.get(pluginId)
    if (!executions) {
      return
    }

    executions.delete(invocationId)
    if (executions.size === 0) {
      this.activeExecutions.delete(pluginId)
    }

    const state = this.runtimeStates.get(pluginId)
    if (state) {
      state.activeExecutions = [...(this.activeExecutions.get(pluginId)?.values() ?? [])].map(toActiveExecution)
    }
  }
}
