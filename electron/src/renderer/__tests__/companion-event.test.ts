import { describe, expect, it } from 'vitest'
import {
  createCompanionEventGate,
  isCompanionEventEnvelope,
  type CompanionEventEnvelope,
} from '../../shared/companion-event'

const jobEvent = (overrides: Partial<CompanionEventEnvelope> = {}): CompanionEventEnvelope => ({
  version: 1,
  type: 'AgentJobCreated',
  workspaceId: 'default',
  sessionId: 'voice',
  turnId: 'turn-1',
  jobId: 'job-1',
  runId: 'run-1',
  requestId: 'request-1',
  revision: 1,
  interruptionEpoch: 3,
  source: 'voice',
  timestamp: 1_000,
  status: 'created',
  ...overrides,
})

describe('companion event gate', () => {
  it('accepts monotonic job revisions and rejects stale or post-terminal updates', () => {
    const gate = createCompanionEventGate()

    expect(gate.accept(jobEvent())).toEqual({ accepted: true })
    expect(gate.accept(jobEvent({ type: 'AgentJobProgress', status: 'progress', revision: 2 }))).toEqual({ accepted: true })
    expect(gate.accept(jobEvent({ type: 'AgentJobProgress', status: 'progress', revision: 2 }))).toEqual({
      accepted: false,
      reason: 'stale_revision',
    })
    expect(gate.accept(jobEvent({ type: 'AgentJobCompleted', status: 'completed', revision: 3 }))).toEqual({ accepted: true })
    expect(gate.accept(jobEvent({ type: 'AgentJobProgress', status: 'progress', revision: 4 }))).toEqual({
      accepted: false,
      reason: 'terminal_job',
    })
  })

  it('accepts a recovered interrupted job as a terminal snapshot', () => {
    const gate = createCompanionEventGate()
    expect(gate.accept(jobEvent({ type: 'AgentJobInterrupted', status: 'interrupted' }))).toEqual({ accepted: true })
    expect(gate.accept(jobEvent({ type: 'AgentJobProgress', status: 'progress', revision: 2 }))).toEqual({
      accepted: false,
      reason: 'terminal_job',
    })
  })

  it('rejects events outside the active workspace, session, turn, job, or interruption epoch', () => {
    const scope = {
      workspaceId: 'default',
      sessionId: 'voice',
      turnId: 'turn-1',
      jobId: 'job-1',
      interruptionEpoch: 3,
    }

    expect(createCompanionEventGate().accept(jobEvent({ workspaceId: 'other' }), scope).reason).toBe('workspace_mismatch')
    expect(createCompanionEventGate().accept(jobEvent({ sessionId: 'other' }), scope).reason).toBe('session_mismatch')
    expect(createCompanionEventGate().accept(jobEvent({ turnId: 'other' }), scope).reason).toBe('turn_mismatch')
    expect(createCompanionEventGate().accept(jobEvent({ jobId: 'other' }), scope).reason).toBe('job_mismatch')
    expect(createCompanionEventGate().accept(jobEvent({ interruptionEpoch: 2 }), scope).reason).toBe('interruption_mismatch')
  })

  it('prevents a job id from being reused with a different identity', () => {
    const gate = createCompanionEventGate()
    expect(gate.accept(jobEvent())).toEqual({ accepted: true })
    expect(gate.accept(jobEvent({ revision: 2, turnId: 'turn-2' }))).toEqual({
      accepted: false,
      reason: 'identity_mismatch',
    })
    expect(createCompanionEventGate().accept(jobEvent({ runId: '' }))).toEqual({
      accepted: false,
      reason: 'invalid_event',
    })
  })

  it('evicts terminal history before active jobs and rejects new jobs when capacity is fully active', () => {
    const gate = createCompanionEventGate(2)
    expect(gate.accept(jobEvent({ jobId: 'done', requestId: 'done', status: 'created' }))).toEqual({ accepted: true })
    expect(gate.accept(jobEvent({
      jobId: 'done',
      requestId: 'done',
      type: 'AgentJobCompleted',
      status: 'completed',
      revision: 2,
    }))).toEqual({ accepted: true })
    expect(gate.accept(jobEvent({ jobId: 'active', requestId: 'active' }))).toEqual({ accepted: true })
    expect(gate.accept(jobEvent({ jobId: 'new', requestId: 'new' }))).toEqual({ accepted: true })
    expect(gate.accept(jobEvent({
      jobId: 'done',
      requestId: 'done',
      type: 'AgentJobProgress',
      status: 'progress',
      revision: 3,
    }))).toEqual({ accepted: false, reason: 'unknown_job' })

    const activeOnlyGate = createCompanionEventGate(1)
    expect(activeOnlyGate.accept(jobEvent())).toEqual({ accepted: true })
    expect(activeOnlyGate.accept(jobEvent({ jobId: 'job-2', requestId: 'request-2' }))).toEqual({
      accepted: false,
      reason: 'capacity_exceeded',
    })
  })

  it('validates the complete shared event contract', () => {
    expect(isCompanionEventEnvelope(jobEvent())).toBe(true)
    expect(isCompanionEventEnvelope(jobEvent({ source: 'builtin' }))).toBe(true)
    expect(isCompanionEventEnvelope(jobEvent({ source: 'mcp' }))).toBe(true)
    expect(isCompanionEventEnvelope({ ...jobEvent(), revision: -1 })).toBe(false)
    expect(isCompanionEventEnvelope({ ...jobEvent(), status: 'unknown' })).toBe(false)
    expect(isCompanionEventEnvelope({ ...jobEvent(), requestId: '' })).toBe(false)
  })

  it('keeps operation identity stable across job revisions', () => {
    const gate = createCompanionEventGate()
    const identity = { conversationId: 'conversation-1', operationId: 'operation-1', stepIndex: 2 }
    expect(gate.accept(jobEvent(identity))).toEqual({ accepted: true })
    expect(gate.accept(jobEvent({ ...identity, revision: 2, type: 'AgentJobRunning', status: 'running' }))).toEqual({ accepted: true })
    expect(gate.accept(jobEvent({ ...identity, revision: 3, operationId: 'operation-2', type: 'AgentJobProgress', status: 'progress' }))).toEqual({
      accepted: false,
      reason: 'identity_mismatch',
    })
  })
})
