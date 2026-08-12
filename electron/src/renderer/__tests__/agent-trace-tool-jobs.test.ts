import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

describe('AgentTracePanel tool jobs', () => {
  it('offers request-scoped cancellation and correlated retry for tool jobs', () => {
    const panel = readFileSync(
      resolve(process.cwd(), 'src/renderer/domains/system/views/AgentTracePanel.vue'),
      'utf8',
    )

    expect(panel).toContain('function isToolCompanionJob(job: CompanionEventEnvelope)')
    expect(panel).toContain("getSocketClient().sendInterrupt(job.sessionId, job.requestId, 'manual')")
    expect(panel).toContain('getSocketClient().sendToolCall(retryRequestId, toolName, args, {')
    expect(panel).toContain('runId: job.runId')
    expect(panel).toContain('jobId: job.jobId')
    expect(panel).toContain('retry: true')
    expect(panel).toContain("job.status !== 'cancelled'")
    expect(panel).toContain('function companionJobResultSummary(job: CompanionEventEnvelope)')
    expect(panel).toContain('function companionJobDuration(job: CompanionEventEnvelope)')
    expect(panel).toContain('function companionJobOutcome(job: CompanionEventEnvelope)')
    expect(panel).toContain('job.data.artifactCount')
  })
})
