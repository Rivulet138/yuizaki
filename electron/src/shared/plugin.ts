import type { CapabilityRiskLevel } from './capability'

export const PLUGIN_MANIFEST_VERSION = 2 as const

export type PluginManifestVersion = typeof PLUGIN_MANIFEST_VERSION

export interface PluginPermissionManifest {
  routes: string[]
  toolScopes: string[]
  modelScopes: string[]
  agentBridge?: boolean
  allowedHosts?: string[]
  allowedPaths?: string[]
  allowedCommands?: string[]
}

export interface PluginExecutionPolicy {
  maxExecutionTimeMs: number
  maxConcurrentExecutions: number
  allowCancellation: boolean
}

export interface PluginRouteContribution {
  id: string
  namespace: 'pet' | 'model' | 'system' | 'workbench' | 'plugin'
  path?: string
  handler?: string
}

export interface PluginModelProviderContribution {
  id: string
  modelType: 'live2d' | 'vrm'
  name: string
  assetPath?: string
}

export interface PluginToolCapabilityContribution {
  id: string
  name: string
  desc: string
  riskLevel?: CapabilityRiskLevel
  scopes?: string[]
  tags?: string[]
}

export type DesktopPetEventName =
  | 'onPetClicked'
  | 'onPetDragged'
  | 'onPetIdle'
  | 'onEmotionChanged'
  | 'onSpeechStart'
  | 'onSpeechEnd'
  | 'onToolStart'
  | 'onToolEnd'
  | 'requestPetAction'

/**
 * Desktop-pet event copy lives in the renderer i18n layer
 * (`i18n/petEventMessages.ts`): this module only carries message keys so it stays
 * importable from the main process, which has no i18n layer of its own.
 */
export interface DesktopPetEventDefinition {
  labelKey: string
  triggerKey: string
  payloadHintKey: string
  frequencyHintKey: string
}

export const DESKTOP_PET_EVENT_DEFINITIONS = {
  onPetClicked: {
    labelKey: 'petEvent.onPetClicked.label',
    triggerKey: 'petEvent.onPetClicked.trigger',
    payloadHintKey: 'petEvent.onPetClicked.payloadHint',
    frequencyHintKey: 'petEvent.onPetClicked.frequencyHint',
  },
  onPetDragged: {
    labelKey: 'petEvent.onPetDragged.label',
    triggerKey: 'petEvent.onPetDragged.trigger',
    payloadHintKey: 'petEvent.onPetDragged.payloadHint',
    frequencyHintKey: 'petEvent.onPetDragged.frequencyHint',
  },
  onPetIdle: {
    labelKey: 'petEvent.onPetIdle.label',
    triggerKey: 'petEvent.onPetIdle.trigger',
    payloadHintKey: 'petEvent.onPetIdle.payloadHint',
    frequencyHintKey: 'petEvent.onPetIdle.frequencyHint',
  },
  onEmotionChanged: {
    labelKey: 'petEvent.onEmotionChanged.label',
    triggerKey: 'petEvent.onEmotionChanged.trigger',
    payloadHintKey: 'petEvent.onEmotionChanged.payloadHint',
    frequencyHintKey: 'petEvent.onEmotionChanged.frequencyHint',
  },
  onSpeechStart: {
    labelKey: 'petEvent.onSpeechStart.label',
    triggerKey: 'petEvent.onSpeechStart.trigger',
    payloadHintKey: 'petEvent.onSpeechStart.payloadHint',
    frequencyHintKey: 'petEvent.onSpeechStart.frequencyHint',
  },
  onSpeechEnd: {
    labelKey: 'petEvent.onSpeechEnd.label',
    triggerKey: 'petEvent.onSpeechEnd.trigger',
    payloadHintKey: 'petEvent.onSpeechEnd.payloadHint',
    frequencyHintKey: 'petEvent.onSpeechEnd.frequencyHint',
  },
  onToolStart: {
    labelKey: 'petEvent.onToolStart.label',
    triggerKey: 'petEvent.onToolStart.trigger',
    payloadHintKey: 'petEvent.onToolStart.payloadHint',
    frequencyHintKey: 'petEvent.onToolStart.frequencyHint',
  },
  onToolEnd: {
    labelKey: 'petEvent.onToolEnd.label',
    triggerKey: 'petEvent.onToolEnd.trigger',
    payloadHintKey: 'petEvent.onToolEnd.payloadHint',
    frequencyHintKey: 'petEvent.onToolEnd.frequencyHint',
  },
  requestPetAction: {
    labelKey: 'petEvent.requestPetAction.label',
    triggerKey: 'petEvent.requestPetAction.trigger',
    payloadHintKey: 'petEvent.requestPetAction.payloadHint',
    frequencyHintKey: 'petEvent.requestPetAction.frequencyHint',
  },
} satisfies Record<DesktopPetEventName, DesktopPetEventDefinition>

export const getDesktopPetEventDefinition = (event: DesktopPetEventName): DesktopPetEventDefinition =>
  DESKTOP_PET_EVENT_DEFINITIONS[event]

export interface DesktopPetEventRecord {
  event: DesktopPetEventName
  timestamp: string
  payload: Record<string, unknown>
}

export interface DesktopPetEventDispatchTarget {
  pluginId: string
  routeId: string
  event: DesktopPetEventName
  status: 'dispatched' | 'skipped' | 'failed'
  reason?: string
  invocationId?: string
  traceId?: string
}

export interface DesktopPetEventDispatchResult {
  ok: boolean
  event?: DesktopPetEventName
  matched: number
  dispatched: number
  skipped: number
  results: DesktopPetEventDispatchTarget[]
  error?: string
}

export interface PluginPetEventSubscription {
  event: DesktopPetEventName
  routeId?: string
  description?: string
}

export type PluginContributionCategory = 'ui' | 'capability' | 'event' | 'policy'

export interface PluginContributionSummary {
  category: PluginContributionCategory
  count: number
  items: string[]
}

export interface DesktopPetPlugin {
  manifestVersion: PluginManifestVersion
  id: string
  name: string
  version?: string
  manifestPath?: string
  permissions: PluginPermissionManifest
  execution: PluginExecutionPolicy
  routes?: PluginRouteContribution[]
  modelProviders?: PluginModelProviderContribution[]
  toolCapabilities?: PluginToolCapabilityContribution[]
  petEvents?: PluginPetEventSubscription[]
}

export type DesktopPetPluginManifest = DesktopPetPlugin

export interface PluginManifestValidationIssue {
  field: string
  message: string
  severity: 'error' | 'warning'
}

export interface PluginLoadFailure {
  manifestPath: string
  pluginId?: string
  reason: string
  validationIssues: PluginManifestValidationIssue[]
  occurredAt: string
}

export type PluginExecutionStatus = 'running' | 'cancelled' | 'timed_out'
export type PluginExecutionIsolation = 'node-permission-process'

export interface PluginActiveExecution {
  invocationId: string
  routeId: string
  startedAt: string
  timeoutMs: number
  status: PluginExecutionStatus
}

export type PluginRuntimeStatus = 'loaded' | 'degraded' | 'blocked' | 'error'

export interface PluginRuntimeStats {
  totalInvocations: number
  okCount: number
  errorCount: number
  timeoutCount: number
  deniedCount: number
  cancelledCount: number
}

export interface PluginRuntimeState {
  pluginId: string
  status: PluginRuntimeStatus
  executionIsolation: PluginExecutionIsolation
  loadedAt: string
  lastAuditAt?: string
  lastError?: string
  validationIssues: PluginManifestValidationIssue[]
  activeExecutions: PluginActiveExecution[]
  stats: PluginRuntimeStats
}

export interface PluginRegistrySnapshot {
  plugins: DesktopPetPlugin[]
  routes: PluginRouteContribution[]
  modelProviders: PluginModelProviderContribution[]
  toolCapabilities: PluginToolCapabilityContribution[]
  contributionSummary?: PluginContributionSummary[]
  pluginStates: PluginRuntimeState[]
  loadFailures: PluginLoadFailure[]
  audit: PluginAuditRecord[]
}

export interface PluginAuditRecord {
  timestamp: string
  pluginId: string
  routeId?: string
  invocationId?: string
  status: 'ok' | 'error' | 'timeout' | 'denied' | 'cancelled'
  detail?: string
  durationMs?: number
}
