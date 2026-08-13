import type { CompanionEventEnvelope, CompanionJobStatus } from '@/../shared/companion-event'
import type { ChatAgentStep, ChatArtifactRef } from '@/../shared/types'

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
}

const text = (value: unknown): string => typeof value === 'string' ? value.trim() : ''
const finiteNumber = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null

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
  status === 'completed' || status === 'failed' || status === 'cancelled' || status === 'interrupted'

export const projectCompanionJob = (event: CompanionEventEnvelope): CompanionJobProjection => {
  const data = event.data || {}
  const progressValue = finiteNumber(data.progress ?? data.percent)
  const durationValue = finiteNumber(data.durationMs ?? data.duration_ms)
  const artifacts = projectArtifacts(data.artifacts)
  const explicitArtifactCount = finiteNumber(data.artifactCount ?? data.artifact_count)
  return {
    id: event.jobId,
    title: text(data.title) || text(data.task_name) || text(data.taskName) || text(data.behaviorType)
      || text(data.summary) || text(data.phase) || `${event.source} job`,
    status: event.status,
    source: event.source,
    tool: text(data.toolName ?? data.tool_name ?? data.tool),
    progress: progressValue === null ? null : Math.max(0, Math.min(1, progressValue > 1 ? progressValue / 100 : progressValue)),
    resultSummary: text(data.resultSummary ?? data.result_summary).replace(/\s+/g, ' ').slice(0, 360),
    error: text(data.error ?? data.cancellationReason ?? data.cancellation_reason),
    durationMs: durationValue === null ? null : Math.max(0, Math.round(durationValue)),
    artifactCount: explicitArtifactCount === null
      ? (artifacts.length ? artifacts.length : null)
      : Math.max(0, Math.round(explicitArtifactCount)),
    artifacts,
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
