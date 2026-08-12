export type CompanionEventSource =
  | 'chat'
  | 'voice'
  | 'heartbeat'
  | 'permission'
  | 'health'
  | 'scheduler'
  | 'vision'
  | 'builtin'
  | 'mcp'
  | 'plugin'

export type CompanionJobStatus = 'created' | 'running' | 'progress' | 'completed' | 'failed' | 'cancelled' | 'interrupted'

export type CompanionJobEventType =
  | 'AgentJobCreated'
  | 'AgentJobRunning'
  | 'AgentJobProgress'
  | 'AgentJobCompleted'
  | 'AgentJobFailed'
  | 'AgentJobCancelled'
  | 'AgentJobInterrupted'

export interface CompanionEventEnvelope {
  version: 1
  type: CompanionJobEventType
  workspaceId: string
  sessionId: string
  turnId: string
  jobId: string
  conversationId?: string
  operationId?: string
  stepIndex?: number
  runId?: string
  requestId: string
  revision: number
  interruptionEpoch: number
  source: CompanionEventSource
  timestamp: number
  status: CompanionJobStatus
  data?: Record<string, unknown>
}

export interface CompanionEventScope {
  workspaceId?: string
  sessionId?: string
  turnId?: string
  jobId?: string
  conversationId?: string
  operationId?: string
  stepIndex?: number
  interruptionEpoch?: number
}

export type CompanionEventRejectionReason =
  | 'invalid_event'
  | 'workspace_mismatch'
  | 'session_mismatch'
  | 'turn_mismatch'
  | 'job_mismatch'
  | 'interruption_mismatch'
  | 'identity_mismatch'
  | 'unknown_job'
  | 'capacity_exceeded'
  | 'stale_revision'
  | 'terminal_job'

export type CompanionEventGateResult =
  | { accepted: true }
  | { accepted: false; reason: CompanionEventRejectionReason }

interface CompanionJobSnapshot {
  workspaceId: string
  sessionId: string
  turnId: string
  requestId: string
  runId: string | undefined
  conversationId: string | undefined
  operationId: string | undefined
  stepIndex: number | undefined
  interruptionEpoch: number
  source: CompanionEventSource
  revision: number
  terminal: boolean
}

const MAX_TRACKED_JOBS = 256
const terminalStatuses = new Set<CompanionJobStatus>(['completed', 'failed', 'cancelled', 'interrupted'])
const eventStatusByType: Record<CompanionJobEventType, CompanionJobStatus> = {
  AgentJobCreated: 'created',
  AgentJobRunning: 'running',
  AgentJobProgress: 'progress',
  AgentJobCompleted: 'completed',
  AgentJobFailed: 'failed',
  AgentJobCancelled: 'cancelled',
  AgentJobInterrupted: 'interrupted',
}
const eventSources = new Set<CompanionEventSource>([
  'chat',
  'voice',
  'heartbeat',
  'permission',
  'health',
  'scheduler',
  'vision',
  'builtin',
  'mcp',
  'plugin',
])

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

const isNonEmptyString = (value: unknown): value is string =>
  typeof value === 'string' && value.trim().length > 0

const isNonNegativeInteger = (value: unknown): value is number =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= 0

const isOptionalIdentity = (value: unknown): value is string | undefined =>
  value === undefined || isNonEmptyString(value)

const isOptionalStepIndex = (value: unknown): value is number | undefined =>
  value === undefined || isNonNegativeInteger(value)

export const isTerminalCompanionJobStatus = (status: CompanionJobStatus): boolean =>
  terminalStatuses.has(status)

export const isCompanionEventEnvelope = (value: unknown): value is CompanionEventEnvelope => {
  if (!isRecord(value) || value['version'] !== 1) return false
  const type = value['type'] as CompanionJobEventType
  const status = value['status'] as CompanionJobStatus
  return isNonEmptyString(type)
    && Object.prototype.hasOwnProperty.call(eventStatusByType, type)
    && eventStatusByType[type] === status
    && isNonEmptyString(value['workspaceId'])
    && isNonEmptyString(value['sessionId'])
    && isNonEmptyString(value['turnId'])
    && isNonEmptyString(value['jobId'])
    && isOptionalIdentity(value['conversationId'])
    && isOptionalIdentity(value['operationId'])
    && isOptionalStepIndex(value['stepIndex'])
    && (value['runId'] === undefined || isNonEmptyString(value['runId']))
    && isNonEmptyString(value['requestId'])
    && isNonNegativeInteger(value['revision'])
    && value['revision'] > 0
    && isNonNegativeInteger(value['interruptionEpoch'])
    && eventSources.has(value['source'] as CompanionEventSource)
    && typeof value['timestamp'] === 'number'
    && Number.isFinite(value['timestamp'])
    && value['timestamp'] >= 0
    && (value['data'] === undefined || isRecord(value['data']))
}

const matchesSnapshot = (event: CompanionEventEnvelope, snapshot: CompanionJobSnapshot): boolean =>
  event.workspaceId === snapshot.workspaceId
  && event.sessionId === snapshot.sessionId
  && event.turnId === snapshot.turnId
  && event.requestId === snapshot.requestId
  && event.runId === snapshot.runId
  && event.conversationId === snapshot.conversationId
  && event.operationId === snapshot.operationId
  && event.stepIndex === snapshot.stepIndex
  && event.interruptionEpoch === snapshot.interruptionEpoch
  && event.source === snapshot.source

export const createCompanionEventGate = (trackedJobLimit = MAX_TRACKED_JOBS) => {
  const jobs = new Map<string, CompanionJobSnapshot>()
  const limit = Number.isFinite(trackedJobLimit) ? Math.max(1, Math.floor(trackedJobLimit)) : MAX_TRACKED_JOBS

  const accept = (value: unknown, scope: CompanionEventScope = {}): CompanionEventGateResult => {
    if (!isCompanionEventEnvelope(value)) return { accepted: false, reason: 'invalid_event' }
    if (scope.workspaceId !== undefined && value.workspaceId !== scope.workspaceId) return { accepted: false, reason: 'workspace_mismatch' }
    if (scope.sessionId !== undefined && value.sessionId !== scope.sessionId) return { accepted: false, reason: 'session_mismatch' }
    if (scope.turnId !== undefined && value.turnId !== scope.turnId) return { accepted: false, reason: 'turn_mismatch' }
    if (scope.jobId !== undefined && value.jobId !== scope.jobId) return { accepted: false, reason: 'job_mismatch' }
    if (scope.conversationId !== undefined && value.conversationId !== scope.conversationId) return { accepted: false, reason: 'identity_mismatch' }
    if (scope.operationId !== undefined && value.operationId !== scope.operationId) return { accepted: false, reason: 'identity_mismatch' }
    if (scope.stepIndex !== undefined && value.stepIndex !== scope.stepIndex) return { accepted: false, reason: 'identity_mismatch' }
    if (scope.interruptionEpoch !== undefined && value.interruptionEpoch !== scope.interruptionEpoch) {
      return { accepted: false, reason: 'interruption_mismatch' }
    }

    const previous = jobs.get(value.jobId)
    if (previous) {
      if (!matchesSnapshot(value, previous)) return { accepted: false, reason: 'identity_mismatch' }
      if (value.revision <= previous.revision) return { accepted: false, reason: 'stale_revision' }
      if (previous.terminal) return { accepted: false, reason: 'terminal_job' }
    } else {
      if ((value.status !== 'created' && value.status !== 'interrupted') || value.revision !== 1) return { accepted: false, reason: 'unknown_job' }
      if (jobs.size >= limit) {
        const terminalJobId = [...jobs.entries()].find(([, snapshot]) => snapshot.terminal)?.[0]
        if (!terminalJobId) return { accepted: false, reason: 'capacity_exceeded' }
        jobs.delete(terminalJobId)
      }
    }

    jobs.set(value.jobId, {
      workspaceId: value.workspaceId,
      sessionId: value.sessionId,
      turnId: value.turnId,
      requestId: value.requestId,
      runId: value.runId,
      conversationId: value.conversationId,
      operationId: value.operationId,
      stepIndex: value.stepIndex,
      interruptionEpoch: value.interruptionEpoch,
      source: value.source,
      revision: value.revision,
      terminal: isTerminalCompanionJobStatus(value.status),
    })
    return { accepted: true }
  }

  return {
    accept,
    clear: () => jobs.clear(),
    trackedJobs: jobs,
  }
}
