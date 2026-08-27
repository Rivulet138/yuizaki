export const ONBOARDING_SCHEMA_VERSION = 1 as const

export const ONBOARDING_PROBE_IDS = [
  'host.runtime',
  'backend.service',
  'llm.provider',
  'llm.model_chat',
  'tts.status',
  'asr.runtime',
  'database.status',
  'memory.status',
  'mcp.snapshot',
  'host.avatar',
  'host.microphone',
  'host.speaker',
] as const

export type OnboardingProbeId = typeof ONBOARDING_PROBE_IDS[number]
export type OnboardingProbeStatus = 'pending' | 'running' | 'ready' | 'degraded' | 'unavailable' | 'failed' | 'cancelled' | 'needs_user'
export type OnboardingRuntimeQualification = 'qualified' | 'not_qualified' | 'unsupported'
export type OnboardingRunState = 'idle' | 'running' | 'ready' | 'blocked' | 'cancelled'
export type OnboardingOperation = 'idle' | 'backend_start' | 'probe_scan'
export const ONBOARDING_PROBE_MESSAGE_KEYS = ['onboarding.interrupted'] as const
export type OnboardingProbeMessageKey = typeof ONBOARDING_PROBE_MESSAGE_KEYS[number]

export interface OnboardingProbeResult {
  id: OnboardingProbeId
  label: string
  status: OnboardingProbeStatus
  requiredForText: boolean
  dependencies: OnboardingProbeId[]
  timeoutMs: number
  durationMs?: number | null
  message: string
  messageKey?: OnboardingProbeMessageKey
  evidence: Record<string, unknown>
  repairActionId: string | null
}

export interface OnboardingReadinessSnapshot {
  schemaVersion: typeof ONBOARDING_SCHEMA_VERSION
  runId: string
  revision: number
  state: OnboardingRunState
  operation: OnboardingOperation
  readyForText: boolean
  startedAt: string | null
  completedAt: string | null
  probes: OnboardingProbeResult[]
}

export interface OnboardingProbeRequest {
  probeIds?: OnboardingProbeId[]
}

export interface OnboardingRetryRequest extends OnboardingProbeRequest {
  runId: string
}

export interface OnboardingCancelRunRequest {
  runId: string
}

export const ONBOARDING_DEVICE_PROBE_IDS = ['host.microphone', 'host.speaker'] as const
export const ONBOARDING_DEVICE_MESSAGE_CODES = [
  'permission_granted',
  'permission_denied',
  'no_device',
  'test_completed',
  'test_failed',
] as const

export interface OnboardingDeviceProbeReport {
  probeId: typeof ONBOARDING_DEVICE_PROBE_IDS[number]
  outcome: 'ready' | 'unavailable'
  messageCode: typeof ONBOARDING_DEVICE_MESSAGE_CODES[number]
}

export const isOnboardingDeviceProbeReport = (value: unknown): value is OnboardingDeviceProbeReport => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const record = value as Record<string, unknown>
  return Object.keys(record).length === 3 &&
    Object.keys(record).every((key) => ['probeId', 'outcome', 'messageCode'].includes(key)) &&
    (ONBOARDING_DEVICE_PROBE_IDS as readonly unknown[]).includes(record['probeId']) &&
    (record['outcome'] === 'ready' || record['outcome'] === 'unavailable') &&
    (ONBOARDING_DEVICE_MESSAGE_CODES as readonly unknown[]).includes(record['messageCode'])
}

export interface OnboardingRepairRequest {
  actionId: OnboardingRepairActionId
}

export const ONBOARDING_REQUIRED_TEXT_PROBES = [
  'host.runtime',
  'backend.service',
  'llm.provider',
  'llm.model_chat',
] as const satisfies readonly OnboardingProbeId[]

export const ONBOARDING_SECTIONS = [
  'overview',
  'settings',
  'pet',
  'infrastructure',
  'agent-governance',
] as const

export type OnboardingSection = typeof ONBOARDING_SECTIONS[number]

export const ONBOARDING_MANAGED_RESOURCE_IDS = ['soulx', 'sherpa', 'sherpa_online', 'embedding', 'tts'] as const
export type OnboardingManagedResourceId = typeof ONBOARDING_MANAGED_RESOURCE_IDS[number]

export type OnboardingRepairActionId =
  | 'backend.retry'
  | 'avatar.reload'
  | 'mcp.refresh_existing'
  | 'logs.open'
  | 'guide.open'
  | `probe.retry:${OnboardingProbeId}`
  | `navigate:${OnboardingSection}`
  | `resource.prepare:${OnboardingManagedResourceId}`

export const isOnboardingProbeId = (value: unknown): value is OnboardingProbeId =>
  typeof value === 'string' && (ONBOARDING_PROBE_IDS as readonly string[]).includes(value)

export const isOnboardingProbeMessageKey = (value: unknown): value is OnboardingProbeMessageKey =>
  typeof value === 'string' && (ONBOARDING_PROBE_MESSAGE_KEYS as readonly string[]).includes(value)

export const isOnboardingRepairActionId = (value: unknown): value is OnboardingRepairActionId => {
  if (typeof value !== 'string') return false
  if (['backend.retry', 'avatar.reload', 'mcp.refresh_existing', 'logs.open', 'guide.open'].includes(value)) return true
  const [prefix, suffix, extra] = value.split(':')
  if (!prefix || !suffix || extra !== undefined) return false
  if (prefix === 'probe.retry') return isOnboardingProbeId(suffix)
  if (prefix === 'navigate') return (ONBOARDING_SECTIONS as readonly string[]).includes(suffix)
  if (prefix === 'resource.prepare') return (ONBOARDING_MANAGED_RESOURCE_IDS as readonly string[]).includes(suffix)
  return false
}
