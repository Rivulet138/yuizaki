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

export type CompanionJobStatus = 'created' | 'running' | 'progress' | 'completed' | 'failed' | 'cancelled' | 'interrupted' | 'unknown_effect'

export type CompanionJobEventType =
  | 'AgentJobCreated'
  | 'AgentJobRunning'
  | 'AgentJobProgress'
  | 'AgentJobCompleted'
  | 'AgentJobFailed'
  | 'AgentJobCancelled'
  | 'AgentJobInterrupted'
  | 'AgentJobUnknownEffect'

export const COMPANION_EVENT_SCHEMA_V2 = 'yuizaki.companion-event.v2' as const

export interface CompanionEventEnvelope {
  version: 1 | 2
  schemaVersion?: typeof COMPANION_EVENT_SCHEMA_V2
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
  terminalAcknowledged: boolean
}

export interface CompanionEventGateState {
  version: 1
  jobs: Array<CompanionJobSnapshot & { jobId: string }>
}

const MAX_TRACKED_JOBS = 256
const terminalStatuses = new Set<CompanionJobStatus>(['completed', 'failed', 'cancelled', 'interrupted', 'unknown_effect'])
const eventStatusByType: Record<CompanionJobEventType, CompanionJobStatus> = {
  AgentJobCreated: 'created',
  AgentJobRunning: 'running',
  AgentJobProgress: 'progress',
  AgentJobCompleted: 'completed',
  AgentJobFailed: 'failed',
  AgentJobCancelled: 'cancelled',
  AgentJobInterrupted: 'interrupted',
  AgentJobUnknownEffect: 'unknown_effect',
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

const isCanonicalCompanionEventEnvelope = (value: unknown): value is CompanionEventEnvelope => {
  if (!isRecord(value) || (value['version'] !== 1 && value['version'] !== 2)) return false
  if (value['version'] === 2 && value['schemaVersion'] !== COMPANION_EVENT_SCHEMA_V2) return false
  if (value['version'] === 1 && value['schemaVersion'] !== undefined) return false
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

export const normalizeCompanionEventEnvelope = (value: unknown): CompanionEventEnvelope | null => {
  if (isCanonicalCompanionEventEnvelope(value)) {
    if (value.version === 2) return value
    return { ...value, version: 2, schemaVersion: COMPANION_EVENT_SCHEMA_V2 }
  }
  if (!isRecord(value)
    || value['version'] !== 1
    || value['schemaVersion'] !== 'yuizaki.companion-presentation.v1'
    || !isNonEmptyString(value['streamId'])
    || !isNonEmptyString(value['type'])
    || !isNonEmptyString(value['requestId'])
    || !isRecord(value['payload'])) return null
  const status = eventStatusByType[value['type'] as CompanionJobEventType]
  const rawSource = value['source'] as CompanionEventSource
  const migrated = {
    version: 2,
    schemaVersion: COMPANION_EVENT_SCHEMA_V2,
    type: value['type'],
    workspaceId: value['workspaceId'],
    sessionId: value['sessionId'],
    turnId: value['turnId'],
    jobId: value['streamId'],
    conversationId: value['conversationId'],
    operationId: value['operationId'],
    stepIndex: value['stepIndex'],
    runId: value['runId'],
    requestId: value['requestId'],
    revision: value['revision'],
    interruptionEpoch: value['interruptionEpoch'],
    source: eventSources.has(rawSource) ? rawSource : 'builtin',
    timestamp: typeof value['timestamp'] === 'number' ? value['timestamp'] : 0,
    status,
    data: value['payload'],
  }
  if (typeof value['terminal'] !== 'boolean' || value['terminal'] !== terminalStatuses.has(status)) return null
  return isCanonicalCompanionEventEnvelope(migrated) ? migrated : null
}

export const isCompanionEventEnvelope = (value: unknown): value is CompanionEventEnvelope =>
  isCanonicalCompanionEventEnvelope(value)

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

const isCompanionEventGateState = (value: unknown): value is CompanionEventGateState => {
  if (!isRecord(value) || value['version'] !== 1 || !Array.isArray(value['jobs'])) return false
  return value['jobs'].every((job) => isRecord(job)
    && isNonEmptyString(job['jobId'])
    && isNonEmptyString(job['workspaceId'])
    && isNonEmptyString(job['sessionId'])
    && isNonEmptyString(job['turnId'])
    && isNonEmptyString(job['requestId'])
    && isOptionalIdentity(job['runId'])
    && isOptionalIdentity(job['conversationId'])
    && isOptionalIdentity(job['operationId'])
    && isOptionalStepIndex(job['stepIndex'])
    && isNonNegativeInteger(job['interruptionEpoch'])
    && eventSources.has(job['source'] as CompanionEventSource)
    && isNonNegativeInteger(job['revision'])
    && job['revision'] > 0
    && typeof job['terminal'] === 'boolean'
    && typeof job['terminalAcknowledged'] === 'boolean'
    && (!job['terminalAcknowledged'] || job['terminal']))
}

export const createCompanionEventGate = (
  trackedJobLimit = MAX_TRACKED_JOBS,
  initialState?: unknown,
) => {
  const jobs = new Map<string, CompanionJobSnapshot>()
  const limit = Number.isFinite(trackedJobLimit) ? Math.max(1, Math.floor(trackedJobLimit)) : MAX_TRACKED_JOBS

  if (isCompanionEventGateState(initialState)) {
    for (const { jobId, ...snapshot } of initialState.jobs.slice(-limit)) jobs.set(jobId, snapshot)
  }

  const accept = (value: unknown, scope: CompanionEventScope = {}): CompanionEventGateResult => {
    const event = normalizeCompanionEventEnvelope(value)
    if (!event) return { accepted: false, reason: 'invalid_event' }
    if (scope.workspaceId !== undefined && event.workspaceId !== scope.workspaceId) return { accepted: false, reason: 'workspace_mismatch' }
    if (scope.sessionId !== undefined && event.sessionId !== scope.sessionId) return { accepted: false, reason: 'session_mismatch' }
    if (scope.turnId !== undefined && event.turnId !== scope.turnId) return { accepted: false, reason: 'turn_mismatch' }
    if (scope.jobId !== undefined && event.jobId !== scope.jobId) return { accepted: false, reason: 'job_mismatch' }
    if (scope.conversationId !== undefined && event.conversationId !== scope.conversationId) return { accepted: false, reason: 'identity_mismatch' }
    if (scope.operationId !== undefined && event.operationId !== scope.operationId) return { accepted: false, reason: 'identity_mismatch' }
    if (scope.stepIndex !== undefined && event.stepIndex !== scope.stepIndex) return { accepted: false, reason: 'identity_mismatch' }
    if (scope.interruptionEpoch !== undefined && event.interruptionEpoch !== scope.interruptionEpoch) {
      return { accepted: false, reason: 'interruption_mismatch' }
    }

    const previous = jobs.get(event.jobId)
    if (previous) {
      if (!matchesSnapshot(event, previous)) return { accepted: false, reason: 'identity_mismatch' }
      if (event.revision <= previous.revision) return { accepted: false, reason: 'stale_revision' }
      if (previous.terminal) return { accepted: false, reason: 'terminal_job' }
    } else {
      if (event.revision !== 1 || (event.status !== 'created' && !isTerminalCompanionJobStatus(event.status))) {
        return { accepted: false, reason: 'unknown_job' }
      }
      if (jobs.size >= limit) {
        const terminalJobId = [...jobs.entries()].find(([, snapshot]) => snapshot.terminalAcknowledged)?.[0]
        if (!terminalJobId) return { accepted: false, reason: 'capacity_exceeded' }
        jobs.delete(terminalJobId)
      }
    }

    jobs.set(event.jobId, {
      workspaceId: event.workspaceId,
      sessionId: event.sessionId,
      turnId: event.turnId,
      requestId: event.requestId,
      runId: event.runId,
      conversationId: event.conversationId,
      operationId: event.operationId,
      stepIndex: event.stepIndex,
      interruptionEpoch: event.interruptionEpoch,
      source: event.source,
      revision: event.revision,
      terminal: isTerminalCompanionJobStatus(event.status),
      terminalAcknowledged: false,
    })
    return { accepted: true }
  }

  const acknowledgeTerminal = (jobId: string, revision: number): boolean => {
    const snapshot = jobs.get(jobId)
    if (!snapshot?.terminal || snapshot.revision !== revision) return false
    snapshot.terminalAcknowledged = true
    return true
  }

  const unacknowledgeTerminal = (jobId: string, revision: number): boolean => {
    const snapshot = jobs.get(jobId)
    if (!snapshot?.terminal || snapshot.revision !== revision) return false
    snapshot.terminalAcknowledged = false
    return true
  }

  const isUnacknowledgedTerminal = (value: unknown): boolean => {
    const event = normalizeCompanionEventEnvelope(value)
    if (!event || !isTerminalCompanionJobStatus(event.status)) return false
    const snapshot = jobs.get(event.jobId)
    return Boolean(snapshot
      && snapshot.terminal
      && !snapshot.terminalAcknowledged
      && snapshot.revision === event.revision
      && matchesSnapshot(event, snapshot))
  }

  const exportState = (): CompanionEventGateState => ({
    version: 1,
    jobs: [...jobs].map(([jobId, snapshot]) => ({ jobId, ...snapshot })),
  })

  return {
    accept,
    acknowledgeTerminal,
    unacknowledgeTerminal,
    isUnacknowledgedTerminal,
    exportState,
    clear: () => jobs.clear(),
    trackedJobs: jobs,
  }
}
