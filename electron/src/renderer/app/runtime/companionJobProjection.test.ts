import { describe, expect, it } from 'vitest'
import type { CompanionEventEnvelope } from '../../../shared/companion-event'
import { canRetryCompanionJob } from './companionJobProjection'

const failedTool = (data: Record<string, unknown>): CompanionEventEnvelope => ({
  version: 2,
  type: 'AgentJobFailed',
  workspaceId: 'workspace',
  sessionId: 'session',
  turnId: 'turn',
  jobId: 'job',
  runId: 'run',
  requestId: 'request',
  revision: 1,
  interruptionEpoch: 0,
  source: 'builtin',
  timestamp: 1,
  status: 'failed',
  data: { toolName: 'demo.retry', args: { value: 'x' }, retryable: true, ...data },
})

describe('tool job retry projection', () => {
  it.each([undefined, false])('hides retry when replay args are unavailable: %s', (available) => {
    expect(canRetryCompanionJob(failedTool({ replayArgsAvailable: available }))).toBe(false)
  })

  it.each(['failed', 'cancelled', 'interrupted'] as const)('allows replayable %s jobs', (status) => {
    expect(canRetryCompanionJob({ ...failedTool({ replayArgsAvailable: true }), status })).toBe(true)
  })

  it('keeps unknown effects, redacted args and explicit denials out of normal retry', () => {
    expect(canRetryCompanionJob(failedTool({ replayArgsAvailable: true, effectOutcome: 'unknown_effect' }))).toBe(false)
    expect(canRetryCompanionJob(failedTool({ replayArgsAvailable: true, args: null }))).toBe(false)
    expect(canRetryCompanionJob(failedTool({ replayArgsAvailable: true, retryable: false }))).toBe(false)
  })
})
