import { describe, expect, it } from 'vitest'
import { companionJobToAgentStep, isTerminalCompanionJob, projectCompanionJob } from '@/app/runtime/companionJobProjection'
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
    expect(isTerminalCompanionJob('running')).toBe(false)
  })
})
