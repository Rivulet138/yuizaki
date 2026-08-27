import { describe, expect, it } from 'vitest'
import {
  canCancelCompanionJob,
  canConfirmUnknownEffectRetry,
  canResumeCompanionJob,
  canRetryCompanionJob,
  canRecheckCompanionJob,
  companionJobToAgentStep,
  isTerminalCompanionJob,
  projectCompanionJob,
} from '@/app/runtime/companionJobProjection'
import type { CompanionEventEnvelope } from '@/../shared/companion-event'

const event = (overrides: Partial<CompanionEventEnvelope> = {}): CompanionEventEnvelope => ({
  version: 1, type: 'AgentJobProgress', workspaceId: 'workspace', sessionId: 'session', turnId: 'turn',
  jobId: 'job', requestId: 'request', revision: 2, interruptionEpoch: 0, source: 'mcp', timestamp: 1,
  status: 'progress', ...overrides,
})

describe('companion job projection', () => {
  it('normalizes the shared Chat and Trace view of progress, artifacts, and errors', () => {
    const input = event({ data: {
      task_name: 'Read workspace', tool_name: 'filesystem.read', progress: 75,
      result_summary: '  partial   result ', cancellation_reason: 'stopped', duration_ms: 12.6,
      artifacts: [{ artifactId: 'a1', filename: 'result.txt', path: '/result.txt' }],
    } })
    expect(projectCompanionJob(input)).toMatchObject({
      title: 'Read workspace', tool: 'filesystem.read', progress: 0.75, resultSummary: 'partial result',
      error: 'stopped', durationMs: 13, artifactCount: 1,
    })
    expect(companionJobToAgentStep(input)).toMatchObject({
      id: 'job', jobId: 'job', status: 'progress', progress: 0.75, artifactCount: 1,
    })
  })

  it('shares one terminal-state definition', () => {
    expect(isTerminalCompanionJob('completed')).toBe(true)
    expect(isTerminalCompanionJob('interrupted')).toBe(true)
    expect(isTerminalCompanionJob('unknown_effect')).toBe(true)
    expect(isTerminalCompanionJob('running')).toBe(false)
  })

  it('uses the canonical unknown-effect status as the explicit confirmation gate', () => {
    const unknownEffect = event({
      type: 'AgentJobUnknownEffect',
      status: 'unknown_effect',
      data: {
        tool_name: 'desktop.close_window', args: { window_id: 'opaque-window-1' },
        replayArgsAvailable: true,
      },
    })

    expect(projectCompanionJob(unknownEffect).effectOutcome).toBe('unknown_effect')
    expect(canRetryCompanionJob(unknownEffect)).toBe(false)
    expect(canConfirmUnknownEffectRetry(unknownEffect)).toBe(true)
  })

  it('allows cancellation only while a supported job is active', () => {
    expect(canCancelCompanionJob(event({ status: 'running', data: { tool_name: 'filesystem.read' } }))).toBe(true)
    expect(canCancelCompanionJob(event({ status: 'running', source: 'scheduler' }))).toBe(true)
    expect(canCancelCompanionJob(event({ status: 'completed', data: { tool_name: 'filesystem.read' } }))).toBe(false)
    expect(canCancelCompanionJob(event({ status: 'running', source: 'vision' }))).toBe(false)
  })

  it('never retries unknown effects or explicitly non-retryable tool outcomes', () => {
    const retryableTool = { tool_name: 'filesystem.read', args: { path: '/tmp/example' }, retryable: true }
    expect(canRetryCompanionJob(event({ status: 'failed', data: retryableTool }))).toBe(true)
    expect(canRetryCompanionJob(event({
      status: 'failed',
      data: { ...retryableTool, outcome: 'unknown_effect' },
    }))).toBe(false)
    expect(canRetryCompanionJob(event({
      status: 'failed',
      data: { ...retryableTool, retryable: false },
    }))).toBe(false)
    expect(canRetryCompanionJob(event({ status: 'failed', data: { tool_name: 'filesystem.read' } }))).toBe(false)
  })

  it('requires explicit acknowledgement for a dispatched tool with an unknown effect', () => {
    const unknownEffect = event({
      status: 'failed',
      data: {
        tool_name: 'desktop.close_window',
        args: { window_id: 'opaque-window-1' },
        effectOutcome: 'unknown_effect',
        retryable: false,
        replayArgsAvailable: true,
      },
    })

    expect(canRetryCompanionJob(unknownEffect)).toBe(false)
    expect(canConfirmUnknownEffectRetry(unknownEffect)).toBe(true)
  })

  it('does not replay unknown effects when retained arguments were redacted', () => {
    const redacted = event({
      status: 'failed',
      data: {
        tool_name: 'external.send',
        args: { token: '[REDACTED]', target: 'channel' },
        effectOutcome: 'unknown_effect',
        replayArgsAvailable: false,
      },
    })

    expect(canRetryCompanionJob(redacted)).toBe(false)
    expect(canConfirmUnknownEffectRetry(redacted)).toBe(false)
  })

  it('projects bounded failure evidence from the terminal tool contract', () => {
    const projection = projectCompanionJob(event({
      status: 'failed',
      data: {
        tool_name: 'desktop.close_window',
        effectOutcome: 'unknown_effect',
        failureCategory: 'verification',
        failedStep: 'verify-window-closed',
        completedSteps: ['find-window', 'request-close'],
        error: 'Postcondition could not be verified',
      },
    }))

    expect(projection).toMatchObject({
      effectOutcome: 'unknown_effect',
      failureCategory: 'verification',
      failedStep: 'verify-window-closed',
      completedSteps: ['find-window', 'request-close'],
    })
  })

  it('projects comfortable action completion states and verification evidence', () => {
    expect(projectCompanionJob(event({ status: 'running' })).actionStatus).toBe('executing')
    expect(projectCompanionJob(event({ status: 'failed' })).actionStatus).toBe('failed')
    expect(projectCompanionJob(event({ status: 'unknown_effect' })).actionStatus).toBe('unknown_effect')

    const verified = projectCompanionJob(event({
      type: 'AgentJobCompleted',
      status: 'completed',
      data: {
        tool_name: 'filesystem.write',
        verification: { status: 'verified', evidence: 'File exists with expected contents' },
      },
    }))
    expect(verified.actionStatus).toBe('verified')
    expect(verified.verificationStatus).toBe('verified')
    expect(verified.evidence).toEqual(['File exists with expected contents'])

    const completed = projectCompanionJob(event({
      type: 'AgentJobCompleted',
      status: 'completed',
      data: { tool_name: 'desktop.focus_window' },
    }))
    expect(completed.actionStatus).toBe('completed')
    expect(completed.verificationStatus).toBe('')
    expect(completed.evidence).toEqual([])
  })

  it('does not treat evidence as proof when verification explicitly failed or is pending', () => {
    const pending = projectCompanionJob(event({
      status: 'completed',
      data: {
        tool_name: 'desktop.focus_window',
        verificationStatus: 'unverified',
        verificationEvidence: ['Window handle was observed, but focus was not confirmed'],
      },
    }))
    expect(pending.actionStatus).toBe('completed')
    expect(pending.verificationStatus).toBe('unverified')
    expect(pending.evidence).toHaveLength(1)

    const failed = projectCompanionJob(event({
      status: 'completed',
      data: {
        tool_name: 'desktop.focus_window',
        verificationStatus: 'error',
        verificationEvidence: ['Status probe failed'],
      },
    }))
    expect(failed.actionStatus).toBe('completed')
    expect(failed.verificationStatus).toBe('error')
  })

  it('does not add confirmation to active or completed low-risk reads', () => {
    const read = event({
      status: 'running',
      data: { tool_name: 'filesystem.read', args: { path: '/tmp/example' } },
    })
    expect(projectCompanionJob(read).actionStatus).toBe('executing')
    expect(canConfirmUnknownEffectRetry(read)).toBe(false)
    expect(canRetryCompanionJob({ ...read, status: 'completed' })).toBe(false)
  })

  it('offers a side-effect-free recheck only when the tool advertises a probe', () => {
    const completed = event({
      status: 'completed',
      data: { tool_name: 'filesystem.write', args: { path: 'x', content: 'ok' }, recheckAvailable: true },
    })
    expect(canRecheckCompanionJob(completed)).toBe(true)
    expect(canRecheckCompanionJob({ ...completed, data: { ...completed.data, recheckAvailable: false } })).toBe(false)
    expect(canRecheckCompanionJob({ ...completed, status: 'failed' })).toBe(false)

    const unknownEffect = event({
      status: 'cancelled',
      data: {
        tool_name: 'desktop.close_window',
        args: { window_id: 'opaque-window-1' },
        effectOutcome: 'unknown_effect',
        recheckAvailable: true,
      },
    })
    expect(canRecheckCompanionJob(unknownEffect)).toBe(true)
  })

  it('offers failed-step resume only with a scoped opaque recovery handle', () => {
    const recoverable = event({
      status: 'failed',
      data: {
        failedStep: 'write-output',
        recovery: { available: true, action: 'resume_failed_step', retryable: true, handle: 'rh_opaque' },
      },
    })
    expect(projectCompanionJob(recoverable).recoveryHandle).toBe('rh_opaque')
    expect(canResumeCompanionJob(recoverable)).toBe(true)
    expect(canResumeCompanionJob(event({ status: 'unknown_effect', data: {
      failedStep: 'write-output',
      recovery: { available: true, action: 'resume_failed_step', retryable: true, handle: 'rh_opaque' },
    } }))).toBe(false)
    expect(canResumeCompanionJob(event({ status: 'failed', data: {
      effectOutcome: 'unknown_effect', failedStep: 'write-output',
      recovery: { available: true, action: 'resume_failed_step', retryable: true, handle: 'rh_opaque' },
    } }))).toBe(false)
    expect(canResumeCompanionJob(event({ status: 'failed', data: {
      failedStep: 'write-output', recovery: { available: false, action: 'resume_failed_step', retryable: true, handle: 'rh_opaque' },
    } }))).toBe(false)
    expect(canResumeCompanionJob(event({ status: 'failed', data: {
      failedStep: 'write-output', recovery: { available: true, action: 'retry_entire_job', retryable: true, handle: 'rh_opaque' },
    } }))).toBe(false)
    expect(canResumeCompanionJob(event({ status: 'failed', data: {
      failedStep: 'write-output',
      failure: { status: 'unknown_effect' },
      recovery: { available: true, action: 'resume_failed_step', retryable: true, handle: 'rh_opaque' },
    } }))).toBe(false)
    expect(canResumeCompanionJob(event({ status: 'failed', data: {
      failedStep: 'write-output',
      recovery: { available: true, action: 'resume_failed_step', retryable: true, reason: 'unknown_effect', handle: 'rh_opaque' },
    } }))).toBe(false)
  })

  it('redacts secrets from user-visible terminal summaries and errors', () => {
    const projection = projectCompanionJob(event({
      status: 'failed',
      data: {
        resultSummary: 'provider token=summary-secret failed',
        error: 'Authorization: Bearer error-secret',
        verificationEvidence: 'token=evidence-secret',
      },
    }))

    expect(projection.resultSummary).not.toContain('summary-secret')
    expect(projection.error).not.toContain('error-secret')
    expect(projection.evidence.join(' ')).not.toContain('evidence-secret')
    expect(`${projection.resultSummary} ${projection.error} ${projection.evidence.join(' ')}`).toContain('[redacted]')
  })
})
