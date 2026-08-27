import type { CompanionEventEnvelope, CompanionJobStatus } from '@/../shared/companion-event'
import type { ChatAgentStep, ChatArtifactRef } from '@/../shared/types'
import { redactDiagnosticText } from './companionDiagnosticExport'

export interface CompanionJobProjection {
  id: string
  title: string
  status: CompanionJobStatus
  source: CompanionEventEnvelope['source']
  tool: string
  progress: number | null
  resultSummary: string
  error: string
  durationMs: number | null
  artifactCount: number | null
  artifacts: ChatArtifactRef[]
  effectOutcome: string
  verificationStatus: string
  failureCategory: string
  failedStep: string
  completedSteps: string[]
  recoveryHandle: string
  /** User-facing completion state; wire status remains backward compatible. */
  actionStatus: 'executing' | 'completed' | 'verified' | 'failed' | 'unknown_effect' | 'cancelled'
  evidence: string[]
}

const text = (value: unknown): string => typeof value === 'string' ? value.trim() : ''
const finiteNumber = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null
const textList = (value: unknown): string[] => !Array.isArray(value)
  ? []
  : value.flatMap(item => text(item) ? [text(item).slice(0, 120)] : []).slice(0, 20)
const record = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
const normalizedMarker = (value: unknown): string => text(value).toLowerCase().replace(/[\s-]+/g, '_')

const evidenceList = (data: Record<string, unknown>): string[] => {
  const values = [data.evidence, data.verificationEvidence, data.verification_evidence, data.postconditionEvidence]
  const nested = record(data.verification)
  if (nested) values.push(nested.evidence, nested.message, nested.detail)
  return values.flatMap(value => Array.isArray(value) ? value : [value])
    .map(value => text(value).replace(/\s+/g, ' ').slice(0, 240))
    .filter(Boolean).slice(0, 6).map(redactDiagnosticText)
}

const actionStatus = (event: CompanionEventEnvelope, data: Record<string, unknown>) => {
  if (event.status === 'unknown_effect' || effectOutcome(event) === 'unknown_effect') return 'unknown_effect' as const
  if (event.status === 'failed') return 'failed' as const
  if (event.status === 'cancelled' || event.status === 'interrupted') return 'cancelled' as const
  if (event.status === 'completed') {
    const verification = record(data.verification)
    const marker = normalizedMarker(data.verificationStatus ?? data.verification_status ?? verification?.status ?? data.postcondition)
    // Evidence is useful context, but it must not upgrade an explicitly
    // unverified/error result into a verified real-world effect.
    if (['verified', 'passed', 'success', 'succeeded', 'ok'].includes(marker)) return 'verified' as const
    // Transport completion only proves that the handler returned; a verifier or
    // postcondition evidence is required before claiming the real-world effect.
    return 'completed' as const
  }
  return 'executing' as const
}

const effectOutcome = (event: CompanionEventEnvelope): string => text(
  event.data?.effectOutcome ?? event.data?.effect_outcome ?? event.data?.outcome,
) || (event.status === 'unknown_effect' ? 'unknown_effect' : '')

export const isUnknownEffectEvent = (event: CompanionEventEnvelope): boolean => {
  const failure = record(event.data?.failure)
  const recovery = record(event.data?.recovery)
  return [
    event.status,
    effectOutcome(event),
    failure?.status,
    failure?.kind,
    failure?.category,
    failure?.outcome,
    failure?.effectOutcome,
    failure?.effect_outcome,
    recovery?.reason,
    recovery?.outcome,
    recovery?.action,
  ].some(value => {
    const marker = normalizedMarker(value)
    return marker === 'unknown_effect' || marker === 'inspect_effect'
  })
}

const projectArtifacts = (value: unknown): ChatArtifactRef[] => !Array.isArray(value)
  ? []
  : value.flatMap((artifact) => {
      if (!artifact || typeof artifact !== 'object' || Array.isArray(artifact)) return []
      const record = artifact as Record<string, unknown>
      const id = text(record.id ?? record.artifactId)
      const name = text(record.name ?? record.filename)
      const type = text(record.type ?? record.mimeType)
      const url = text(record.url ?? record.path)
      if (!id && !name && !url) return []
      return [{ ...(id ? { id } : {}), ...(name ? { name } : {}), ...(type ? { type } : {}), ...(url ? { url } : {}) }]
    })

export const isTerminalCompanionJob = (status: CompanionJobStatus): boolean =>
  status === 'completed' || status === 'failed' || status === 'cancelled' || status === 'interrupted' || status === 'unknown_effect'

export const companionJobToolArgs = (event: CompanionEventEnvelope): Record<string, unknown> | null => {
  const args = event.data?.args
  return args && typeof args === 'object' && !Array.isArray(args)
    ? args as Record<string, unknown>
    : null
}

export const isToolCompanionJob = (event: CompanionEventEnvelope): boolean =>
  Boolean(projectCompanionJob(event).tool)

export const canCancelCompanionJob = (event: CompanionEventEnvelope): boolean =>
  !isTerminalCompanionJob(event.status)
  && (isToolCompanionJob(event) || event.source === 'scheduler' || event.source === 'heartbeat')

export const canRetryCompanionJob = (event: CompanionEventEnvelope): boolean => {
  if (isUnknownEffectEvent(event)) return false
  if (event.status !== 'failed' && event.status !== 'cancelled' && event.status !== 'interrupted') return false
  if (isToolCompanionJob(event)) {
    return event.data?.retryable !== false
      && companionJobToolArgs(event) !== null
  }
  return event.source === 'scheduler' && typeof event.data?.taskId === 'string'
}

export const canRecheckCompanionJob = (event: CompanionEventEnvelope): boolean =>
  isToolCompanionJob(event)
  && (
    projectCompanionJob(event).actionStatus === 'completed'
    || isUnknownEffectEvent(event)
  )
  && event.data?.recheckAvailable === true
  && companionJobToolArgs(event) !== null

export const canResumeCompanionJob = (event: CompanionEventEnvelope): boolean => {
  const projection = projectCompanionJob(event)
  const recovery = event.data?.recovery && typeof event.data.recovery === 'object' && !Array.isArray(event.data.recovery)
    ? event.data.recovery as Record<string, unknown>
    : null
  const handle = projection.recoveryHandle
  return projection.recoveryHandle.length > 0
    && projection.failedStep.length > 0
    && projection.status === 'failed'
    && !isUnknownEffectEvent(event)
    && recovery?.available === true
    && recovery.action === 'resume_failed_step'
    && recovery.retryable === true
    && /^rh_[A-Za-z0-9_-]{5,160}$/.test(handle)
}

export const canConfirmUnknownEffectRetry = (event: CompanionEventEnvelope): boolean =>
  (event.status === 'failed' || event.status === 'cancelled' || event.status === 'interrupted' || event.status === 'unknown_effect')
  && isToolCompanionJob(event)
  && isUnknownEffectEvent(event)
  && event.data?.replayArgsAvailable === true
  && companionJobToolArgs(event) !== null

export const projectCompanionJob = (event: CompanionEventEnvelope): CompanionJobProjection => {
  const data = event.data || {}
  const progressValue = finiteNumber(data.progress ?? data.percent)
  const durationValue = finiteNumber(data.durationMs ?? data.duration_ms)
  const artifacts = projectArtifacts(data.artifacts)
  const explicitArtifactCount = finiteNumber(data.artifactCount ?? data.artifact_count)
  const recovery = data.recovery && typeof data.recovery === 'object' && !Array.isArray(data.recovery)
    ? data.recovery as Record<string, unknown>
    : null
  const evidence = evidenceList(data)
  const verification = record(data.verification)
  const verificationStatus = normalizedMarker(
    data.verificationStatus ?? data.verification_status ?? verification?.status,
  )
  return {
    id: event.jobId,
    title: text(data.title) || text(data.task_name) || text(data.taskName) || text(data.behaviorType)
      || text(data.summary) || text(data.phase) || `${event.source} job`,
    status: event.status,
    source: event.source,
    tool: text(data.toolName ?? data.tool_name ?? data.tool),
    progress: progressValue === null ? null : Math.max(0, Math.min(1, progressValue > 1 ? progressValue / 100 : progressValue)),
    resultSummary: redactDiagnosticText(text(data.resultSummary ?? data.result_summary).replace(/\s+/g, ' ').slice(0, 360)),
    error: redactDiagnosticText(text(data.error ?? data.cancellationReason ?? data.cancellation_reason)),
    durationMs: durationValue === null ? null : Math.max(0, Math.round(durationValue)),
    artifactCount: explicitArtifactCount === null
      ? (artifacts.length ? artifacts.length : null)
      : Math.max(0, Math.round(explicitArtifactCount)),
    artifacts,
    effectOutcome: effectOutcome(event),
    verificationStatus,
    failureCategory: text(data.failureCategory ?? data.failure_category ?? data.category).slice(0, 120),
    failedStep: text(data.failedStep ?? data.failed_step ?? data.stepId ?? data.step_id).slice(0, 120),
    completedSteps: textList(data.completedSteps ?? data.completed_steps),
    recoveryHandle: text(recovery?.handle ?? data.recoveryHandle ?? data.recovery_handle).slice(0, 160),
    actionStatus: actionStatus(event, data),
    evidence,
  }
}

export const companionJobToAgentStep = (event: CompanionEventEnvelope): ChatAgentStep => {
  const job = projectCompanionJob(event)
  return {
    id: job.id,
    title: job.title,
    status: job.status,
    ...(job.tool ? { tool: job.tool } : {}),
    ...(job.error ? { error: job.error } : {}),
    jobId: job.id,
    ...(event.runId ? { runId: event.runId } : {}),
    ...(job.resultSummary ? { resultSummary: job.resultSummary } : {}),
    ...(job.durationMs !== null ? { durationMs: job.durationMs } : {}),
    ...(job.artifactCount !== null ? { artifactCount: job.artifactCount } : {}),
    ...(job.artifacts.length ? { artifacts: job.artifacts } : {}),
    ...(job.progress !== null ? { progress: job.progress } : {}),
  }
}
