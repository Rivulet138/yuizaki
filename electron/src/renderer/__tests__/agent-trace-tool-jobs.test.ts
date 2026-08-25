import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

describe('AgentTracePanel tool jobs', () => {
  it('offers request-scoped cancellation and correlated retry for tool jobs', () => {
    const panel = readFileSync(
      resolve(process.cwd(), 'src/renderer/domains/system/views/AgentTracePanel.vue'),
      'utf8',
    )

    expect(panel).toContain('canRetryCompanionJob')
    expect(panel).toContain('canCancelCompanionJob')
    expect(panel).toContain('companionJobToolArgs')
    expect(panel).toContain("getSocketClient().sendInterrupt(job.sessionId, job.requestId, 'manual')")
    expect(panel).toContain('getSocketClient().sendToolCall(retryRequestId, toolName, args, {')
    expect(panel).toContain('runId: job.runId')
    expect(panel).toContain('jobId: job.jobId')
    expect(panel).toContain('retry: true')
    expect(panel).toContain('function companionJobResultSummary(job: CompanionEventEnvelope)')
    expect(panel).toContain('function companionJobDuration(job: CompanionEventEnvelope)')
    expect(panel).toContain('function companionJobOutcome(job: CompanionEventEnvelope)')
    expect(panel).toContain('projectCompanionJob(job).artifactCount')
    expect(panel).toContain('canConfirmUnknownEffectRetry(job)')
    expect(panel).toContain('canResumeCompanionJob(job)')
    expect(panel).toContain('systemClient.resumeAgentRecovery({')
    expect(panel).toContain('recovery_handle: projection.recoveryHandle')
    expect(panel).toContain('从失败步骤继续')
    expect(panel).toContain('confirmUnknownEffectRetry(job)')
    expect(panel).toContain('该工具可能已经产生影响')
    expect(panel).toContain('failureEvidenceLines(job)')
    expect(panel).toContain('downloadDiagnosticBundle')
    expect(panel).toContain('createRedactedDiagnosticBundle')
    expect(panel).toContain('serializeRedactedDiagnosticBundle')
    expect(panel).toContain("unknown_effect: 'unknown effect'")
  })
})
