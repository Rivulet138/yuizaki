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

export interface DesktopPetEventDefinition {
  label: string
  trigger: string
  payloadHint: string
  frequencyHint: string
}

export const DESKTOP_PET_EVENT_DEFINITIONS = {
  onPetClicked: {
    label: '点击桌宠',
    trigger: '单击、双击、右键或长按桌宠时触发。',
    payloadHint: '包含 gesture、button、x、y、hitArea 等点击上下文。',
    frequencyHint: '高频交互，渲染层会做短间隔节流。',
  },
  onPetDragged: {
    label: '拖动桌宠',
    trigger: '用户拖动或放下桌宠时触发。',
    payloadHint: '包含 phase、x、y、deltaX、deltaY 等拖拽上下文。',
    frequencyHint: '移动过程会节流，适合保存位置或做轻量反馈。',
  },
  onPetIdle: {
    label: '桌宠空闲',
    trigger: '桌宠一段时间没有被对话、拖动或点击时触发。',
    payloadHint: '包含 idleMs、behaviorState 等空闲上下文。',
    frequencyHint: '低频事件，适合主动陪伴、轻提醒或待机动作。',
  },
  onEmotionChanged: {
    label: '情绪变化',
    trigger: 'LLM、用户操作或插件让桌宠切换情绪/表情时触发。',
    payloadHint: '包含 emotionId、expressionName、source 等情绪上下文。',
    frequencyHint: '中频事件，适合联动灯效、背景或额外动作。',
  },
  onSpeechStart: {
    label: '开始说话',
    trigger: 'TTS 口型同步开始，桌宠准备发声时触发。',
    payloadHint: '包含 audioUrl 等播放上下文。',
    frequencyHint: '每轮语音回复通常触发一次。',
  },
  onSpeechEnd: {
    label: '结束说话',
    trigger: 'TTS 播放结束、停止或被用户打断时触发。',
    payloadHint: '包含 interrupted，用于区分自然结束和用户打断。',
    frequencyHint: '每轮语音回复通常触发一次。',
  },
  onToolStart: {
    label: '工具开始',
    trigger: 'Agent 或插件开始执行工具能力时触发。',
    payloadHint: '包含 toolId、pluginId、routeId 等工具上下文。',
    frequencyHint: '按工具调用触发，适合提示桌宠进入专注或忙碌动作。',
  },
  onToolEnd: {
    label: '工具结束',
    trigger: 'Agent 或插件工具执行完成、失败或取消时触发。',
    payloadHint: '包含 status、durationMs、toolId、pluginId 等结果上下文。',
    frequencyHint: '按工具调用触发，适合恢复待机或播放完成反馈。',
  },
  requestPetAction: {
    label: '请求桌宠动作',
    trigger: '插件主动请求桌宠播放动作、表情或行为状态时触发。',
    payloadHint: '包含 action、emotionId、motion、behaviorState 等动作上下文。',
    frequencyHint: '由插件主动发起，应保持短动作和可取消设计。',
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
