import { computed, reactive, shallowRef, watch, type ComputedRef } from 'vue'
import type { CompanionRuntimeSnapshot, HeartbeatBehaviorEvent } from '@/../shared/agent'
import {
  createCompanionEventGate,
  isTerminalCompanionJobStatus,
  type CompanionEventEnvelope,
  type CompanionEventScope,
  type CompanionEventSource,
} from '@/../shared/companion-event'
import type { PetBehaviorState } from '@/utils/petControl'
import { createReducedMotionObserver, type ReducedMotionObserver } from './reducedMotion'

export type CompanionActivity = 'idle' | 'listening' | 'thinking' | 'speaking' | 'executing'
export type CompanionAvailability = 'online' | 'offline' | 'degraded' | 'error'
export type CompanionPermission = 'none' | 'waiting'
export type CompanionRuntimeSource = CompanionEventSource
export type CompanionPresentationState = CompanionActivity | 'offline' | 'error' | 'waiting-for-permission' | 'interrupted' | 'job-success' | 'job-error' | 'job-cancelled'
export type ProactiveSuppressionReason = 'duplicate_or_invalid' | 'unavailable' | 'dnd' | 'ineligible' | 'cooldown' | 'frequency_budget'
export type CompanionRuntimeSinkName = 'behavior' | 'emotion' | 'motion' | 'advice' | 'notification'
export interface ProactiveSinkContext {
  signal: AbortSignal
  eventVersion: string
}
export interface ProactiveDeliveryResult {
  status: 'delivered' | 'partial' | 'failed'
  attempted: CompanionRuntimeSinkName[]
  succeeded: CompanionRuntimeSinkName[]
  failed: Array<{ sink: CompanionRuntimeSinkName; message: string }>
}
type OpportunityOutcome = 'delivered' | 'suppressed' | 'expired' | 'cancelled' | 'failed'
interface PendingOpportunityOutcome {
  jobId: string
  requestId: string
  outcome: OpportunityOutcome
  reason?: string
}
export type ProactivePollResult = ProactiveSuppressionReason | ProactiveDeliveryResult | 'empty' | 'in_flight' | 'stopped'

const DEFAULT_COMPANION_POLL_INTERVAL_MS = 60_000
const DEFAULT_DELIVERED_IDENTITY_LIMIT = 256
const JOB_TERMINAL_FEEDBACK_MS = 1_200

export interface CompanionRuntimeEvent {
  source: CompanionRuntimeSource
  sequence: number
  activity?: CompanionActivity
  availability?: CompanionAvailability
  permission?: CompanionPermission
  requestId?: string
  interruptionEpoch?: number
  durationMs?: number
}

export interface CompanionRuntimeState {
  activity: CompanionActivity
  availability: CompanionAvailability
  permission: CompanionPermission
  interruptionEpoch: number
  interruptedAtEpoch: number | null
  reducedMotion: boolean
  lastRequestId: string | null
  suppressionCounts: Record<ProactiveSuppressionReason, number>
}

interface CompanionRuntimeSinks {
  behavior?: (state: PetBehaviorState, durationMs?: number) => void | Promise<void>
  emotion?: (emotionId: string, context: ProactiveSinkContext) => void | Promise<void>
  motion?: (group: string, context: ProactiveSinkContext) => void | Promise<void>
  advice?: (message: string) => void | Promise<void>
  notification?: (message: string) => void | Promise<void>
}

export interface CompanionRuntimeDependencies {
  pollSnapshot: () => Promise<CompanionRuntimeSnapshot>
  isAvailable: () => boolean
  readDoNotDisturb: () => boolean | Promise<boolean>
  sinks: CompanionRuntimeSinks
  pollIntervalMs?: number
  cooldownMs?: number
  frequencyBudget?: number
  frequencyWindowMs?: number
  deliveredIdentityLimit?: number
  now?: () => number
  reducedMotionObserver?: ReducedMotionObserver
  onSinkError?: (failure: { sink: CompanionRuntimeSinkName; message: string }) => void
  onPollResult?: (result: ProactivePollResult) => void
  reportOpportunityOutcome?: (jobId: string, requestId: string, outcome: OpportunityOutcome, reason?: string) => void | Promise<void>
}

const activityPriority: Record<CompanionActivity, number> = {
  idle: 0,
  listening: 1,
  thinking: 2,
  executing: 3,
  speaking: 4,
}

const behaviorForPresentation = (state: CompanionPresentationState): PetBehaviorState => {
  switch (state) {
    case 'listening': return 'waiting'
    case 'thinking': return 'thinking'
    case 'speaking': return 'speaking'
    case 'executing': return 'focused'
    case 'waiting-for-permission': return 'waiting'
    case 'interrupted': return 'interrupted'
    case 'job-success': return 'curious'
    case 'job-error': return 'reacting'
    case 'job-cancelled': return 'interrupted'
    case 'offline': return 'sleepy'
    case 'error': return 'reacting'
    default: return 'idle'
  }
}

const eventIdentity = (event: HeartbeatBehaviorEvent): string | null => {
  if (!Number.isFinite(event.tick) || !event.type || !event.at) return null
  return `${event.type}:${event.tick}:${event.at}`
}

export const createCompanionRuntimeController = (initialDependencies: CompanionRuntimeDependencies) => {
  let dependencies = initialDependencies
  const reducedMotionObserver = dependencies.reducedMotionObserver ?? createReducedMotionObserver()
  const state = reactive<CompanionRuntimeState>({
    activity: 'idle',
    availability: 'online',
    permission: 'none',
    interruptionEpoch: 0,
    interruptedAtEpoch: null,
    reducedMotion: false,
    lastRequestId: null,
    suppressionCounts: {
      duplicate_or_invalid: 0,
      unavailable: 0,
      dnd: 0,
      ineligible: 0,
      cooldown: 0,
      frequency_budget: 0,
    },
  })
  const terminalJobPresentation = shallowRef<{ jobId: string; state: CompanionPresentationState; epoch: number } | null>(null)
  const presentationState: ComputedRef<CompanionPresentationState> = computed(() => {
    if (state.availability === 'offline' || state.availability === 'error') return state.availability
    if (state.permission === 'waiting') return 'waiting-for-permission'
    if (state.interruptedAtEpoch === state.interruptionEpoch) return 'interrupted'
    if (state.activity !== 'idle') return state.activity
    if (terminalJobPresentation.value) return terminalJobPresentation.value.state
    return state.activity
  })
  const sourceSequences = new Map<CompanionRuntimeSource, number>()
  const sourceActivities = new Map<CompanionRuntimeSource, CompanionActivity>()
  const sourceRequestIds = new Map<CompanionRuntimeSource, string>()
  const activityExpiryTimers = new Map<CompanionRuntimeSource, ReturnType<typeof setTimeout>>()
  const lastSnapshot = shallowRef<CompanionRuntimeSnapshot | null>(null)
  const deliveredIdentities = new Set<string>()
  const categoryDeliveredAt = new Map<string, number>()
  const deliveredAt: number[] = []
  const pendingOpportunityOutcomes = new Map<string, PendingOpportunityOutcome>()
  const jobEventGate = createCompanionEventGate()
  const activeJobIdsBySource = new Map<CompanionRuntimeSource, Set<string>>()
  let terminalJobTimer: ReturnType<typeof setTimeout> | null = null
  let timer: ReturnType<typeof setInterval> | null = null
  let started = false
  let pollingEnabled = true
  let pollInFlight = false
  let activeOpportunityCandidate: HeartbeatBehaviorEvent | null = null
  let lifecycleEpoch = 0
  let healthEpoch = 0
  let lastBehavior: PetBehaviorState | null = 'idle'
  let activePollAbortController: AbortController | null = null

  const abortActivePoll = () => {
    activePollAbortController?.abort()
  }

  const clearTerminalJobPresentation = () => {
    if (terminalJobTimer !== null) clearTimeout(terminalJobTimer)
    terminalJobTimer = null
    terminalJobPresentation.value = null
  }

  watch(reducedMotionObserver.reduced, (reduced) => {
    state.reducedMotion = reduced
  }, { immediate: true })

  const configure = (next: Partial<CompanionRuntimeDependencies>) => {
    dependencies = { ...dependencies, ...next, sinks: { ...dependencies.sinks, ...next.sinks } }
  }

  const applyPresentation = async (durationMs?: number) => {
    const behavior = behaviorForPresentation(presentationState.value)
    if (behavior === lastBehavior && durationMs === undefined) return
    lastBehavior = behavior
    try {
      await dependencies.sinks.behavior?.(behavior, durationMs)
    } catch (error) {
      dependencies.onSinkError?.({ sink: 'behavior', message: error instanceof Error ? error.message : String(error) })
    }
  }

  const showTerminalJobPresentation = async (event: CompanionEventEnvelope) => {
    const terminalState: CompanionPresentationState = event.status === 'completed'
      ? 'job-success'
      : event.status === 'failed'
        ? 'job-error'
        : 'job-cancelled'
    clearTerminalJobPresentation()
    terminalJobPresentation.value = { jobId: event.jobId, state: terminalState, epoch: state.interruptionEpoch }
    await applyPresentation(JOB_TERMINAL_FEEDBACK_MS)
    terminalJobTimer = setTimeout(() => {
      terminalJobTimer = null
      const current = terminalJobPresentation.value
      if (!current || current.jobId !== event.jobId || current.epoch !== state.interruptionEpoch) return
      terminalJobPresentation.value = null
      void applyPresentation()
    }, JOB_TERMINAL_FEEDBACK_MS)
  }

  const recomputeActivity = () => {
    state.activity = [...sourceActivities.values()].reduce<CompanionActivity>(
      (winner, activity) => activityPriority[activity] > activityPriority[winner] ? activity : winner,
      'idle',
    )
  }

  const clearActivityExpiry = (source: CompanionRuntimeSource) => {
    const existing = activityExpiryTimers.get(source)
    if (existing) clearTimeout(existing)
    activityExpiryTimers.delete(source)
  }

  const scheduleActivityExpiry = (event: CompanionRuntimeEvent) => {
    clearActivityExpiry(event.source)
    if (event.activity === undefined || event.activity === 'idle' || event.durationMs === undefined || event.durationMs <= 0) return
    const capturedEpoch = state.interruptionEpoch
    const capturedRequestId = event.requestId
    const timer = setTimeout(() => {
      activityExpiryTimers.delete(event.source)
      if (sourceSequences.get(event.source) !== event.sequence) return
      if (state.interruptionEpoch !== capturedEpoch) return
      if (capturedRequestId && sourceRequestIds.get(event.source) !== capturedRequestId) return
      sourceActivities.set(event.source, 'idle')
      if (capturedRequestId) sourceRequestIds.delete(event.source)
      recomputeActivity()
      void applyPresentation()
    }, event.durationMs)
    activityExpiryTimers.set(event.source, timer)
  }

  const publish = async (event: CompanionRuntimeEvent): Promise<boolean> => {
    const currentSequence = sourceSequences.get(event.source) ?? -1
    if (!Number.isFinite(event.sequence) || event.sequence <= currentSequence) return false
    if (event.interruptionEpoch !== undefined && event.interruptionEpoch < state.interruptionEpoch) return false
    const currentRequestId = sourceRequestIds.get(event.source)
    if (event.activity === 'idle' && event.requestId && currentRequestId && event.requestId !== currentRequestId) return false
    sourceSequences.set(event.source, event.sequence)
    if (event.activity !== undefined) {
      if (event.activity !== 'idle') clearTerminalJobPresentation()
      sourceActivities.set(event.source, event.activity)
      recomputeActivity()
      state.interruptedAtEpoch = null
    }
    if (event.availability !== undefined) {
      state.availability = event.availability
      healthEpoch += 1
      abortActivePoll()
    }
    if (event.permission !== undefined) state.permission = event.permission
    if (event.requestId !== undefined) state.lastRequestId = event.requestId
    if (event.activity === 'idle') sourceRequestIds.delete(event.source)
    else if (event.requestId !== undefined) sourceRequestIds.set(event.source, event.requestId)
    scheduleActivityExpiry(event)
    await applyPresentation(event.durationMs)
    return true
  }

  const interrupt = async (source: CompanionRuntimeSource, sequence: number) => {
    const currentSequence = sourceSequences.get(source) ?? -1
    if (sequence <= currentSequence) return false
    sourceSequences.set(source, sequence)
    for (const activeSource of activityExpiryTimers.keys()) clearActivityExpiry(activeSource)
    sourceActivities.clear()
    sourceRequestIds.clear()
    activeJobIdsBySource.clear()
    clearTerminalJobPresentation()
    jobEventGate.clear()
    state.lastRequestId = null
    recomputeActivity()
    state.interruptionEpoch += 1
    abortActivePoll()
    if (activeOpportunityCandidate) {
      await reportOpportunity(activeOpportunityCandidate, 'cancelled', `interrupted_by_${source}`)
    }
    state.interruptedAtEpoch = state.interruptionEpoch
    await applyPresentation()
    return true
  }

  const publishJob = async (event: CompanionEventEnvelope, scope: CompanionEventScope = {}): Promise<boolean> => {
    const decision = jobEventGate.accept(event, {
      ...scope,
      interruptionEpoch: scope.interruptionEpoch ?? state.interruptionEpoch,
    })
    if (!decision.accepted) return false
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent<CompanionEventEnvelope>('companion:job', { detail: event }))
    }
    if (event.source === 'heartbeat') return true
    const activeJobs = activeJobIdsBySource.get(event.source) ?? new Set<string>()
    if (isTerminalCompanionJobStatus(event.status)) activeJobs.delete(event.jobId)
    else activeJobs.add(event.jobId)
    if (activeJobs.size > 0) activeJobIdsBySource.set(event.source, activeJobs)
    else activeJobIdsBySource.delete(event.source)
    const activeRequestId = [...activeJobs].at(-1)
    const accepted = await publish({
      source: event.source,
      sequence: nextCompanionRuntimeSequence(event.source),
      activity: activeRequestId ? 'executing' : 'idle',
      requestId: activeRequestId ?? event.jobId,
      interruptionEpoch: event.interruptionEpoch,
    })
    if (accepted && isTerminalCompanionJobStatus(event.status) && activeJobIdsBySource.size === 0 && state.activity === 'idle') {
      await showTerminalJobPresentation(event)
    }
    return accepted
  }

  const ingestSnapshotJobs = async (snapshot: CompanionRuntimeSnapshot) => {
    const events = Array.isArray(snapshot.jobs?.events) ? snapshot.jobs.events : []
    for (const event of events) {
      // A snapshot may have been fetched before an interrupt and delivered
      // afterwards. Never let its event epoch become the acceptance scope.
      if (event.interruptionEpoch !== state.interruptionEpoch) continue
      await publishJob(event, {
        workspaceId: snapshot.active_workspace_id,
        interruptionEpoch: state.interruptionEpoch,
      })
    }
    const activeJobIds = new Set(snapshot.jobs?.active_job_ids ?? [])
    for (const [jobId, pending] of pendingOpportunityOutcomes) {
      if (!activeJobIds.has(jobId)) {
        pendingOpportunityOutcomes.delete(jobId)
        continue
      }
      await sendOpportunityOutcome(pending)
    }
  }

  const suppress = (reason: ProactiveSuppressionReason): ProactiveSuppressionReason => {
    state.suppressionCounts[reason] += 1
    return reason
  }

  const sendOpportunityOutcome = async (pending: PendingOpportunityOutcome): Promise<void> => {
    if (!dependencies.reportOpportunityOutcome) return
    try {
      await dependencies.reportOpportunityOutcome(
        pending.jobId,
        pending.requestId,
        pending.outcome,
        pending.reason,
      )
      pendingOpportunityOutcomes.delete(pending.jobId)
    } catch {
      pendingOpportunityOutcomes.set(pending.jobId, pending)
    }
  }

  const reportOpportunity = async (
    candidate: HeartbeatBehaviorEvent,
    outcome: OpportunityOutcome,
    reason?: string,
  ) => {
    if (!candidate.job_id || !candidate.request_id) return
    await sendOpportunityOutcome({
      jobId: candidate.job_id,
      requestId: candidate.request_id,
      outcome,
      ...(reason ? { reason } : {}),
    })
  }

  const rememberDeliveredIdentity = (identity: string) => {
    const configuredLimit = dependencies.deliveredIdentityLimit ?? DEFAULT_DELIVERED_IDENTITY_LIMIT
    const limit = Number.isFinite(configuredLimit)
      ? Math.max(1, Math.floor(configuredLimit))
      : DEFAULT_DELIVERED_IDENTITY_LIMIT
    while (deliveredIdentities.size >= limit) {
      const oldest = deliveredIdentities.values().next().value
      if (oldest === undefined) break
      deliveredIdentities.delete(oldest)
    }
    deliveredIdentities.add(identity)
  }

  const rememberResolvedOpportunity = (candidate: HeartbeatBehaviorEvent, identity: string) => {
    if (candidate.job_id && candidate.request_id) rememberDeliveredIdentity(identity)
  }

  const invokeSink = async (
    name: CompanionRuntimeSinkName,
    sink: (() => void | Promise<void>) | undefined,
    result: ProactiveDeliveryResult,
    isRequestCurrent: () => boolean,
  ): Promise<boolean> => {
    if (!isRequestCurrent()) return false
    if (!sink) return isRequestCurrent()
    result.attempted.push(name)
    try {
      await sink()
      if (!isRequestCurrent()) return false
      result.succeeded.push(name)
    } catch (error) {
      if (!isRequestCurrent()) return false
      const failure = { sink: name, message: error instanceof Error ? error.message : String(error) }
      result.failed.push(failure)
      dependencies.onSinkError?.(failure)
    }
    return isRequestCurrent()
  }

  const pollOnce = async (): Promise<ProactivePollResult> => {
    if (pollInFlight) return 'in_flight'
    pollInFlight = true
    const requestAbortController = new AbortController()
    activePollAbortController = requestAbortController
    const requestEpoch = lifecycleEpoch
    const requestHealthEpoch = healthEpoch
    const requestInterruptionEpoch = state.interruptionEpoch
    const requestStarted = started
    const isRequestCurrent = () => requestEpoch === lifecycleEpoch
      && requestHealthEpoch === healthEpoch
      && requestInterruptionEpoch === state.interruptionEpoch
      && (!requestStarted || started)
      && !requestAbortController.signal.aborted
    try {
      if (!dependencies.isAvailable()) {
        state.availability = 'offline'
        await applyPresentation()
        if (!isRequestCurrent()) return 'stopped'
        healthEpoch += 1
        return suppress('unavailable')
      }
      const snapshot = await dependencies.pollSnapshot()
      if (!isRequestCurrent()) return 'stopped'
      if (!dependencies.isAvailable()) {
        state.availability = 'offline'
        await applyPresentation()
        if (!isRequestCurrent()) return 'stopped'
        healthEpoch += 1
        return suppress('unavailable')
      }
      lastSnapshot.value = snapshot
      state.availability = 'online'
      await ingestSnapshotJobs(snapshot)
      if (!isRequestCurrent()) return 'stopped'
      const events = Array.isArray(snapshot.heartbeat?.behavior_events) ? snapshot.heartbeat.behavior_events : []
      const activeJobIds = snapshot.jobs ? new Set(snapshot.jobs.active_job_ids ?? []) : null
      const candidate = events.findLast((event) => !event.job_id || activeJobIds === null || activeJobIds.has(event.job_id))
      if (!candidate) return 'empty'
      activeOpportunityCandidate = candidate
      const identity = eventIdentity(candidate)
      if (!identity || deliveredIdentities.has(identity)) return suppress('duplicate_or_invalid')
      if (candidate.expires_at && (dependencies.now ?? Date.now)() / 1000 >= candidate.expires_at) {
        rememberResolvedOpportunity(candidate, identity)
        await reportOpportunity(candidate, 'expired', 'delivery_window_elapsed')
        return suppress('ineligible')
      }
      const sinkContext: ProactiveSinkContext = {
        signal: requestAbortController.signal,
        eventVersion: identity,
      }
      if (!dependencies.isAvailable()) return suppress('unavailable')
      const doNotDisturb = await dependencies.readDoNotDisturb()
      if (!isRequestCurrent()) return 'stopped'
      if (doNotDisturb) {
        rememberResolvedOpportunity(candidate, identity)
        await reportOpportunity(candidate, 'suppressed', 'dnd')
        return suppress('dnd')
      }
      const proactive = candidate.proactive_state ?? snapshot.companion_state?.proactive_state
      const interruptibility = snapshot.companion_state?.interruptibility
      const contextInterruptible = state.activity === 'idle' || state.activity === 'listening'
      if (proactive?.can_proactively_reach_out !== true || (typeof interruptibility === 'number' && interruptibility <= 0) || !contextInterruptible) {
        rememberResolvedOpportunity(candidate, identity)
        await reportOpportunity(candidate, 'suppressed', 'ineligible')
        return suppress('ineligible')
      }
      const now = (dependencies.now ?? Date.now)()
      const category = candidate.type || 'unknown'
      const cooldownMs = dependencies.cooldownMs ?? 60_000
      if (now - (categoryDeliveredAt.get(category) ?? Number.NEGATIVE_INFINITY) < cooldownMs) {
        rememberResolvedOpportunity(candidate, identity)
        await reportOpportunity(candidate, 'suppressed', 'cooldown')
        return suppress('cooldown')
      }
      const frequencyWindowMs = dependencies.frequencyWindowMs ?? 60 * 60_000
      while (deliveredAt.length > 0 && now - (deliveredAt[0] ?? now) >= frequencyWindowMs) deliveredAt.shift()
      if (deliveredAt.length >= (dependencies.frequencyBudget ?? 3)) {
        rememberResolvedOpportunity(candidate, identity)
        await reportOpportunity(candidate, 'suppressed', 'frequency_budget')
        return suppress('frequency_budget')
      }

      const result: ProactiveDeliveryResult = { status: 'delivered', attempted: [], succeeded: [], failed: [] }
      if (candidate.emotion_id) {
        const sink = dependencies.sinks.emotion
        if (!await invokeSink('emotion', sink ? () => sink(candidate.emotion_id!, sinkContext) : undefined, result, isRequestCurrent)) return 'stopped'
      }
      if (candidate.motion_group && !state.reducedMotion) {
        const sink = dependencies.sinks.motion
        if (!await invokeSink('motion', sink ? () => sink(candidate.motion_group!, sinkContext) : undefined, result, isRequestCurrent)) return 'stopped'
      }
      if (candidate.message) {
        const adviceSink = dependencies.sinks.advice
        const notificationSink = dependencies.sinks.notification
        if (!await invokeSink('advice', adviceSink ? () => adviceSink(candidate.message!) : undefined, result, isRequestCurrent)) return 'stopped'
        if (!await invokeSink('notification', notificationSink ? () => notificationSink(candidate.message!) : undefined, result, isRequestCurrent)) return 'stopped'
      }
      if (!isRequestCurrent()) return 'stopped'
      rememberDeliveredIdentity(identity)
      categoryDeliveredAt.set(category, now)
      deliveredAt.push(now)
      if (result.failed.length === 0) {
        result.status = 'delivered'
      } else if (result.succeeded.length === 0) {
        result.status = 'failed'
      } else {
        result.status = 'partial'
      }
      await reportOpportunity(candidate, result.status === 'failed' ? 'failed' : 'delivered', result.status)
      return result
    } catch {
      if (!isRequestCurrent()) return 'stopped'
      state.availability = 'degraded'
      await applyPresentation()
      if (!isRequestCurrent()) return 'stopped'
      return suppress('unavailable')
    } finally {
      activeOpportunityCandidate = null
      if (activePollAbortController === requestAbortController) activePollAbortController = null
      pollInFlight = false
    }
  }

  const startPollingTimer = () => {
    if (!started || !pollingEnabled || timer !== null) return
    timer = setInterval(() => {
      state.reducedMotion = reducedMotionObserver.reduced.value
      void pollOnce().then((result) => dependencies.onPollResult?.(result))
    }, dependencies.pollIntervalMs ?? DEFAULT_COMPANION_POLL_INTERVAL_MS)
  }

  const start = () => {
    if (started) return
    started = true
    pollingEnabled = true
    lifecycleEpoch += 1
    abortActivePoll()
    for (const source of activityExpiryTimers.keys()) clearActivityExpiry(source)
    reducedMotionObserver.start()
    state.reducedMotion = reducedMotionObserver.reduced.value
    startPollingTimer()
  }

  const setPollingEnabled = (enabled: boolean) => {
    if (pollingEnabled === enabled) return
    pollingEnabled = enabled
    if (!enabled) {
      abortActivePoll()
      if (timer !== null) clearInterval(timer)
      timer = null
      return
    }
    startPollingTimer()
  }

  const stop = () => {
    const wasStarted = started
    started = false
    lifecycleEpoch += 1
    abortActivePoll()
    if (activeOpportunityCandidate) void reportOpportunity(activeOpportunityCandidate, 'cancelled', 'runtime_stopped')
    for (const source of activityExpiryTimers.keys()) clearActivityExpiry(source)
    sourceActivities.clear()
    sourceRequestIds.clear()
    activeJobIdsBySource.clear()
    clearTerminalJobPresentation()
    jobEventGate.clear()
    state.lastRequestId = null
    state.interruptedAtEpoch = null
    recomputeActivity()
    if (timer) clearInterval(timer)
    timer = null
    if (wasStarted) reducedMotionObserver.stop()
    void applyPresentation()
  }

  return {
    state,
    presentationState,
    lastSnapshot,
    deliveredIdentities,
    configure,
    publish,
    publishJob,
    interrupt,
    pollOnce,
    start,
    stop,
    setPollingEnabled,
    isStarted: () => started,
  }
}

export type CompanionRuntimeController = ReturnType<typeof createCompanionRuntimeController>

let installedController: CompanionRuntimeController | null = null
const publisherSequences = new Map<CompanionRuntimeSource, number>()

export const installCompanionRuntimeController = (controller: CompanionRuntimeController) => {
  installedController = controller
}

export const nextCompanionRuntimeSequence = (source: CompanionRuntimeSource): number => {
  const next = (publisherSequences.get(source) ?? 0) + 1
  publisherSequences.set(source, next)
  return next
}

export const publishCompanionRuntimeEvent = (event: Omit<CompanionRuntimeEvent, 'sequence'> & { sequence?: number }) =>
  installedController?.publish({ ...event, sequence: event.sequence ?? nextCompanionRuntimeSequence(event.source) }) ?? Promise.resolve(false)

export const publishCompanionJobEvent = (event: CompanionEventEnvelope, scope?: CompanionEventScope) =>
  installedController?.publishJob(event, scope ?? {}) ?? Promise.resolve(false)

export const publishCompanionInterrupt = (source: CompanionRuntimeSource) =>
  installedController?.interrupt(source, nextCompanionRuntimeSequence(source)) ?? Promise.resolve(false)

export const getCompanionInterruptionEpoch = () => installedController?.state.interruptionEpoch ?? 0

export const compareCompanionActivity = (left: CompanionActivity, right: CompanionActivity) =>
  activityPriority[left] - activityPriority[right]
