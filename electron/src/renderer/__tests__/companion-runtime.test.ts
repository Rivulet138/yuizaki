import { describe, expect, it, vi } from 'vitest'
import { createCompanionRuntimeController } from '../app/runtime/companionRuntime'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import type { CompanionEventEnvelope } from '../../shared/companion-event'

const event = (overrides: Record<string, unknown> = {}) => ({
  type: 'suggestion',
  message: 'take a break',
  emotion: 'calm',
  emotion_id: 'calm',
  motion_group: 'TapBody',
  prompt: '',
  tick: 1,
  at: '2026-08-04T00:00:00Z',
  proactive_state: { can_proactively_reach_out: true },
  ...overrides,
})

const deferred = <T,>() => {
  let resolve!: (value: T | PromiseLike<T>) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

describe('companion runtime controller', () => {
  it('keeps orthogonal state and rejects stale publisher events', async () => {
    const behavior = vi.fn()
    const controller = createCompanionRuntimeController({
      pollSnapshot: vi.fn(),
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      sinks: { behavior },
    })

    await controller.publish({ source: 'chat', sequence: 2, activity: 'thinking', requestId: 'new' })
    await controller.publish({ source: 'chat', sequence: 1, activity: 'idle', requestId: 'old' })
    await controller.publish({ source: 'health', sequence: 1, availability: 'degraded' })
    await controller.publish({ source: 'permission', sequence: 1, permission: 'waiting' })
    await controller.publish({ source: 'voice', sequence: 1, activity: 'speaking' })

    expect(controller.state.activity).toBe('speaking')
    expect(controller.state.availability).toBe('degraded')
    expect(controller.state.permission).toBe('waiting')
    expect(controller.presentationState.value).toBe('waiting-for-permission')
    expect(behavior).toHaveBeenLastCalledWith('waiting', undefined)

    await controller.publish({ source: 'permission', sequence: 2, permission: 'none' })
    await controller.interrupt('chat', 3)
    const interruptedEpoch = controller.state.interruptionEpoch
    await controller.publish({ source: 'voice', sequence: 2, activity: 'speaking', interruptionEpoch: interruptedEpoch - 1 })
    expect(controller.presentationState.value).toBe('interrupted')
  })

  it('rejects a late completion from a superseded request identity', async () => {
    const controller = createCompanionRuntimeController({
      pollSnapshot: vi.fn(),
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      sinks: {},
    })
    await controller.publish({ source: 'chat', sequence: 1, activity: 'thinking', requestId: 'old' })
    await controller.publish({ source: 'chat', sequence: 2, activity: 'thinking', requestId: 'new' })
    expect(await controller.publish({ source: 'chat', sequence: 3, activity: 'idle', requestId: 'old' })).toBe(false)
    expect(controller.state.activity).toBe('thinking')
  })

  it('emits scoped operational embodiment intent with TTL and pet-link fallback', async () => {
    let petLinkEnabled = true
    const embodiment = vi.fn()
    const controller = createCompanionRuntimeController({
      pollSnapshot: vi.fn(),
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      isPetLinkEnabled: () => petLinkEnabled,
      now: () => 10_000,
      sinks: { embodiment },
    })

    await controller.publish({
      source: 'chat',
      sequence: 1,
      activity: 'thinking',
      requestId: 'request-intent',
      durationMs: 750,
    })
    expect(embodiment).toHaveBeenLastCalledWith(expect.objectContaining({
      version: 1,
      kind: 'operational',
      state: 'thinking',
      source: 'chat',
      confidence: 1,
      issuedAt: 10_000,
      expiresAt: 10_750,
      reducedMotion: false,
      petLinkEnabled: true,
    }))

    petLinkEnabled = false
    await controller.refreshPresentation()
    expect(embodiment).toHaveBeenLastCalledWith(expect.objectContaining({
      state: 'thinking',
      petLinkEnabled: false,
    }))
    expect(embodiment.mock.calls.at(-1)?.[0]).not.toHaveProperty('persona')
  })

  it('bounds non-idle embodiment states when publishers omit a duration', async () => {
    const embodiment = vi.fn()
    const controller = createCompanionRuntimeController({
      pollSnapshot: vi.fn(),
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      now: () => 20_000,
      sinks: { embodiment },
    })

    await controller.publish({ source: 'voice', sequence: 1, activity: 'speaking', requestId: 'voice-ttl' })
    expect(embodiment).toHaveBeenLastCalledWith(expect.objectContaining({
      state: 'speaking',
      issuedAt: 20_000,
      expiresAt: 80_000,
    }))
  })

  it('does not invoke proactive avatar sinks when pet link is disabled', async () => {
    const emotion = vi.fn()
    const motion = vi.fn()
    const notification = vi.fn()
    const controller = createCompanionRuntimeController({
      pollSnapshot: async () => ({
        heartbeat: { behavior_events: [event()] },
        companion_state: { interruptibility: 1 },
      } as never),
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      isPetLinkEnabled: () => false,
      sinks: { emotion, motion, notification },
      cooldownMs: 0,
    })

    expect(await controller.pollOnce()).toMatchObject({ status: 'delivered' })
    expect(emotion).not.toHaveBeenCalled()
    expect(motion).not.toHaveBeenCalled()
    expect(notification).toHaveBeenCalledOnce()
  })

  it('consumes unified Agent job events without allowing late progress to reopen a terminal job', async () => {
    const controller = createCompanionRuntimeController({
      pollSnapshot: vi.fn(),
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      sinks: {},
    })
    const base = {
      version: 1 as const,
      workspaceId: 'default',
      sessionId: 'voice',
      turnId: 'turn-1',
      jobId: 'job-1',
      requestId: 'request-1',
      interruptionEpoch: 0,
      source: 'voice' as const,
      timestamp: 1_000,
    }

    expect(await controller.publishJob({
      ...base,
      type: 'AgentJobCreated',
      revision: 1,
      status: 'created',
    })).toBe(true)
    expect(controller.state.activity).toBe('executing')

    expect(await controller.publishJob({
      ...base,
      type: 'AgentJobCompleted',
      revision: 2,
      status: 'completed',
    })).toBe(true)
    expect(controller.state.activity).toBe('idle')

    expect(await controller.publishJob({
      ...base,
      type: 'AgentJobProgress',
      revision: 3,
      status: 'progress',
    })).toBe(false)
    expect(controller.state.activity).toBe('idle')
  })

  it('restores the reducer and acknowledges a terminal projection durably across remounts', async () => {
    let durableState: unknown
    const eventFor = (revision: number, status: 'created' | 'completed') => ({
      version: 1 as const,
      type: status === 'created' ? 'AgentJobCreated' as const : 'AgentJobCompleted' as const,
      workspaceId: 'default', sessionId: 'voice', turnId: 'turn-durable', jobId: 'job-durable',
      requestId: 'request-durable', revision, interruptionEpoch: 0, source: 'voice' as const,
      timestamp: 1_000 + revision, status,
    })
    const create = () => createCompanionRuntimeController({
      pollSnapshot: vi.fn(),
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      sinks: {},
      loadJobEventGateState: () => durableState,
      saveJobEventGateState: (state) => { durableState = JSON.parse(JSON.stringify(state)) },
    })

    const first = create()
    expect(await first.publishJob(eventFor(1, 'created'))).toBe(true)
    expect(await first.publishJob(eventFor(2, 'completed'))).toBe(true)

    const restored = create()
    expect(await restored.publishJob(eventFor(2, 'completed'))).toBe(false)
    expect(await restored.publishJob({ ...eventFor(2, 'completed'), revision: 3 })).toBe(false)
  })

  it('replays an unacknowledged terminal after durable acknowledgement persistence fails', async () => {
    let durableState: unknown
    let failTerminalSave = true
    const dispatched: string[] = []
    const listener = (event: Event) => dispatched.push((event as CustomEvent<CompanionEventEnvelope>).detail.status)
    window.addEventListener('companion:job', listener)
    const base = {
      version: 1 as const, workspaceId: 'default', sessionId: 'voice', turnId: 'turn-replay',
      jobId: 'job-replay', requestId: 'request-replay', interruptionEpoch: 0, source: 'voice' as const,
      timestamp: 1_000,
    }
    const dependencies = {
      pollSnapshot: vi.fn(), isAvailable: () => true, readDoNotDisturb: async () => false, sinks: {},
      loadJobEventGateState: () => durableState,
      saveJobEventGateState: (state: unknown) => {
        const terminal = (state as { jobs: Array<{ terminal: boolean; terminalAcknowledged: boolean }> }).jobs[0]
        if (terminal?.terminalAcknowledged && failTerminalSave) throw new Error('disk unavailable')
        durableState = JSON.parse(JSON.stringify(state))
      },
    }

    const first = createCompanionRuntimeController(dependencies)
    await first.publishJob({ ...base, type: 'AgentJobCreated', revision: 1, status: 'created' })
    await first.publishJob({ ...base, type: 'AgentJobCompleted', revision: 2, status: 'completed' })
    failTerminalSave = false
    const restored = createCompanionRuntimeController(dependencies)
    expect(await restored.publishJob({ ...base, type: 'AgentJobCompleted', revision: 2, status: 'completed' })).toBe(true)
    expect(dispatched).toEqual(['created', 'completed', 'completed'])
    window.removeEventListener('companion:job', listener)
  })

  it('rejects an unacknowledged terminal replay from before the current interruption epoch', async () => {
    let durableState: unknown
    let failTerminalSave = true
    const controller = createCompanionRuntimeController({
      pollSnapshot: vi.fn(), isAvailable: () => true, readDoNotDisturb: async () => false, sinks: {},
      loadJobEventGateState: () => durableState,
      saveJobEventGateState: (state: unknown) => {
        const terminal = (state as { jobs: Array<{ terminal: boolean; terminalAcknowledged: boolean }> }).jobs[0]
        if (terminal?.terminalAcknowledged && failTerminalSave) throw new Error('disk unavailable')
        durableState = JSON.parse(JSON.stringify(state))
      },
    })
    const base = {
      version: 1 as const, workspaceId: 'default', sessionId: 'voice', turnId: 'turn-epoch-replay',
      jobId: 'job-epoch-replay', requestId: 'request-epoch-replay', interruptionEpoch: 0,
      source: 'voice' as const, timestamp: 1_000,
    }

    expect(await controller.publishJob({ ...base, type: 'AgentJobCreated', revision: 1, status: 'created' })).toBe(true)
    expect(await controller.publishJob({ ...base, type: 'AgentJobCompleted', revision: 2, status: 'completed' })).toBe(true)
    expect(controller.state.interruptionEpoch).toBe(0)

    await controller.interrupt('chat', 1)
    failTerminalSave = false
    expect(controller.state.interruptionEpoch).toBe(1)
    expect(await controller.publishJob({ ...base, type: 'AgentJobCompleted', revision: 2, status: 'completed' })).toBe(false)
  })

  it('does not let a stale caller scope override the controller interruption epoch', async () => {
    const dispatched: string[] = []
    const listener = (event: Event) => dispatched.push((event as CustomEvent<CompanionEventEnvelope>).detail.jobId)
    window.addEventListener('companion:job', listener)
    const controller = createCompanionRuntimeController({
      pollSnapshot: vi.fn(), isAvailable: () => true, readDoNotDisturb: async () => false, sinks: {},
    })
    await controller.interrupt('chat', 1)
    const stale = {
      version: 1 as const, type: 'AgentJobCreated' as const, workspaceId: 'default',
      sessionId: 'voice', turnId: 'turn-stale-scope', jobId: 'job-stale-scope',
      requestId: 'request-stale-scope', revision: 1, interruptionEpoch: 0,
      source: 'voice' as const, timestamp: 1_000, status: 'created' as const,
    }
    expect(await controller.publishJob(stale, { interruptionEpoch: 0 })).toBe(false)
    expect(dispatched).toEqual([])
    window.removeEventListener('companion:job', listener)
  })

  it('restores a persisted interruption epoch on remount and accepts fresh events at that epoch', async () => {
    let durableState: unknown
    const create = () => createCompanionRuntimeController({
      pollSnapshot: vi.fn(), isAvailable: () => true, readDoNotDisturb: async () => false, sinks: {},
      loadJobEventGateState: () => durableState,
      saveJobEventGateState: (value) => { durableState = JSON.parse(JSON.stringify(value)) },
    })

    const first = create()
    await first.interrupt('chat', 1)
    expect(first.state.interruptionEpoch).toBe(1)
    expect((durableState as { interruptionEpoch: number }).interruptionEpoch).toBe(1)

    const restored = create()
    expect(restored.state.interruptionEpoch).toBe(1)
    expect(await restored.publishJob({
      version: 1 as const, type: 'AgentJobCreated' as const,
      workspaceId: 'default', sessionId: 'voice', turnId: 'turn-after-remount',
      jobId: 'job-after-remount', requestId: 'request-after-remount', revision: 1,
      interruptionEpoch: 1, source: 'voice' as const, timestamp: 2_000, status: 'created' as const,
    })).toBe(true)
  })

  it('uses bounded workspace-scoped storage without retaining event payloads', async () => {
    const key = 'yuizaki:companion-event-gate:v1:workspace-storage'
    window.localStorage.removeItem(key)
    const create = () => createCompanionRuntimeController({
      pollSnapshot: vi.fn(), isAvailable: () => true, readDoNotDisturb: async () => false, sinks: {},
      getWorkspaceId: () => 'workspace-storage',
    })
    const base = {
      version: 1 as const, workspaceId: 'workspace-storage', sessionId: 'voice', turnId: 'turn-storage',
      jobId: 'job-storage', requestId: 'request-storage', interruptionEpoch: 0, source: 'voice' as const,
      timestamp: 1_000,
    }

    const first = create()
    await first.publishJob({ ...base, type: 'AgentJobCreated', revision: 1, status: 'created', data: { secret: 'not durable' } })
    await first.publishJob({ ...base, type: 'AgentJobCompleted', revision: 2, status: 'completed', data: { secret: 'not durable' } })
    const stored = window.localStorage.getItem(key) || ''
    expect(stored).not.toContain('not durable')
    expect((JSON.parse(stored) as { jobs: unknown[] }).jobs).toHaveLength(1)

    expect(await create().publishJob({ ...base, type: 'AgentJobCompleted', revision: 2, status: 'completed' })).toBe(false)
    window.localStorage.removeItem(key)
  })

  it('rehydrates independent event gates and epochs across workspace A to B to A switches', async () => {
    const keyA = 'yuizaki:companion-event-gate:v1:workspace-a'
    const keyB = 'yuizaki:companion-event-gate:v1:workspace-b'
    window.localStorage.removeItem(keyA)
    window.localStorage.removeItem(keyB)
    let workspaceId = 'workspace-a'
    const controller = createCompanionRuntimeController({
      pollSnapshot: vi.fn(), isAvailable: () => true, readDoNotDisturb: async () => false, sinks: {},
      getWorkspaceId: () => workspaceId,
    })
    const eventFor = (workspace: string, job: string, revision: number, status: 'created' | 'progress', epoch: number) => ({
      version: 1 as const,
      type: status === 'created' ? 'AgentJobCreated' as const : 'AgentJobProgress' as const,
      workspaceId: workspace, sessionId: 'voice', turnId: `turn-${job}`, jobId: job,
      requestId: `request-${job}`, revision, interruptionEpoch: epoch, source: 'voice' as const,
      timestamp: 3_000 + revision, status,
    })

    await controller.interrupt('chat', 1)
    expect(controller.state.interruptionEpoch).toBe(1)
    expect(await controller.publishJob(eventFor('workspace-a', 'job-a', 1, 'created', 1))).toBe(true)

    workspaceId = 'workspace-b'
    expect(await controller.publishJob(eventFor('workspace-b', 'job-b', 1, 'created', 0))).toBe(true)
    expect(controller.state.interruptionEpoch).toBe(0)
    expect(window.localStorage.getItem(keyA)).toContain('job-a')
    expect(window.localStorage.getItem(keyA)).not.toContain('job-b')
    expect(window.localStorage.getItem(keyB)).toContain('job-b')
    expect(window.localStorage.getItem(keyB)).not.toContain('job-a')

    workspaceId = 'workspace-a'
    expect(await controller.publishJob(eventFor('workspace-a', 'job-a', 1, 'created', 1))).toBe(false)
    expect(controller.state.interruptionEpoch).toBe(1)
    expect(await controller.publishJob(eventFor('workspace-a', 'job-a', 2, 'progress', 1))).toBe(true)
    expect((JSON.parse(window.localStorage.getItem(keyA) || '{}') as { interruptionEpoch: number }).interruptionEpoch).toBe(1)

    window.localStorage.removeItem(keyA)
    window.localStorage.removeItem(keyB)
  })

  it('shows bounded terminal job feedback and restores idle without reopening stale jobs', async () => {
    vi.useFakeTimers()
    const behavior = vi.fn()
    const controller = createCompanionRuntimeController({
      pollSnapshot: vi.fn(),
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      sinks: { behavior },
    })
    const base = {
      version: 1 as const, workspaceId: 'default', sessionId: 'voice', turnId: 'turn-feedback',
      jobId: 'job-feedback', requestId: 'request-feedback', interruptionEpoch: 0,
      source: 'voice' as const, timestamp: 1_000,
    }

    await controller.publishJob({ ...base, type: 'AgentJobCreated', revision: 1, status: 'created' })
    await controller.publishJob({ ...base, type: 'AgentJobCompleted', revision: 2, status: 'completed' })
    expect(controller.presentationState.value).toBe('job-success')
    expect(behavior).toHaveBeenLastCalledWith('curious', 1_200)

    await vi.advanceTimersByTimeAsync(1_200)
    expect(controller.presentationState.value).toBe('idle')
    expect(behavior).toHaveBeenLastCalledWith('idle', undefined)
  })

  it('clears terminal feedback when a newer job starts', async () => {
    vi.useFakeTimers()
    const behavior = vi.fn()
    const controller = createCompanionRuntimeController({
      pollSnapshot: vi.fn(), isAvailable: () => true, readDoNotDisturb: async () => false, sinks: { behavior },
    })
    const eventFor = (jobId: string, revision: number, status: 'created' | 'failed') => ({
      version: 1 as const,
      type: status === 'created' ? 'AgentJobCreated' as const : 'AgentJobFailed' as const,
      workspaceId: 'default', sessionId: 'voice', turnId: `turn-${jobId}`, jobId,
      requestId: `request-${jobId}`, revision, interruptionEpoch: 0, source: 'voice' as const,
      timestamp: 1_000 + revision, status,
    })

    await controller.publishJob(eventFor('old', 1, 'created'))
    await controller.publishJob(eventFor('old', 2, 'failed'))
    expect(controller.presentationState.value).toBe('job-error')
    await controller.publishJob(eventFor('new', 1, 'created'))
    expect(controller.presentationState.value).toBe('executing')
    expect(behavior).toHaveBeenLastCalledWith('focused', undefined)
    await vi.advanceTimersByTimeAsync(1_200)
    expect(controller.presentationState.value).toBe('executing')
  })

  it('stays executing until every active job for a source reaches a terminal state', async () => {
    const controller = createCompanionRuntimeController({
      pollSnapshot: vi.fn(),
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      sinks: {},
    })
    const eventFor = (jobId: string, revision: number, status: 'created' | 'completed') => ({
      version: 1 as const,
      type: status === 'created' ? 'AgentJobCreated' as const : 'AgentJobCompleted' as const,
      workspaceId: 'default',
      sessionId: 'voice',
      turnId: `turn-${jobId}`,
      jobId,
      requestId: `request-${jobId}`,
      revision,
      interruptionEpoch: 0,
      source: 'voice' as const,
      timestamp: 1_000 + revision,
      status,
    })

    expect(await controller.publishJob(eventFor('a', 1, 'created'))).toBe(true)
    expect(await controller.publishJob(eventFor('b', 1, 'created'))).toBe(true)
    expect(await controller.publishJob(eventFor('a', 2, 'completed'))).toBe(true)
    expect(controller.state.activity).toBe('executing')
    expect(await controller.publishJob(eventFor('b', 2, 'completed'))).toBe(true)
    expect(controller.state.activity).toBe('idle')
  })

  it('ingests scheduler job events from the existing runtime snapshot', async () => {
    const events = [{
      version: 1 as const,
      type: 'AgentJobCreated' as const,
      workspaceId: 'default',
      sessionId: 'schedule:task-1',
      turnId: 'job-1',
      jobId: 'job-1',
      requestId: 'request-1',
      revision: 1,
      interruptionEpoch: 0,
      source: 'scheduler' as const,
      timestamp: 1_000,
      status: 'created' as const,
      data: { taskId: 'task-1' },
    }]
    const pollSnapshot = vi.fn(async () => ({
      heartbeat: { behavior_events: [] },
      jobs: { events, active_job_ids: ['job-1'] },
    } as never))
    const controller = createCompanionRuntimeController({
      pollSnapshot,
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      sinks: {},
    })

    expect(await controller.pollOnce()).toBe('empty')
    expect(controller.state.activity).toBe('executing')

    events.push({
      ...events[0],
      type: 'AgentJobCompleted',
      revision: 2,
      timestamp: 2_000,
      status: 'completed',
    })

    expect(await controller.pollOnce()).toBe('empty')
    expect(controller.state.activity).toBe('idle')
  })

  it('globally invalidates cross-source activity and rejects old playback completion after interrupt', async () => {
    const advice = vi.fn()
    const controller = createCompanionRuntimeController({
      pollSnapshot: async () => ({
        heartbeat: { behavior_events: [event()] },
        companion_state: { interruptibility: 1 },
      } as never),
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      sinks: { advice },
      cooldownMs: 0,
    })

    await controller.publish({ source: 'voice', sequence: 1, activity: 'speaking', requestId: 'voice-turn', interruptionEpoch: 0 })
    await controller.publish({ source: 'chat', sequence: 1, activity: 'executing', requestId: 'chat-turn', interruptionEpoch: 0, durationMs: 5000 })
    await controller.interrupt('chat', 2)

    expect(controller.state.activity).toBe('idle')
    expect(controller.state.lastRequestId).toBeNull()
    expect(controller.presentationState.value).toBe('interrupted')
    expect(await controller.publish({ source: 'chat', sequence: 3, activity: 'idle', requestId: 'chat-turn', interruptionEpoch: 0 })).toBe(false)
    expect(await controller.publish({ source: 'voice', sequence: 2, activity: 'idle', requestId: 'voice-turn', interruptionEpoch: 0 })).toBe(false)
    expect(controller.presentationState.value).toBe('interrupted')

    expect(await controller.pollOnce()).toMatchObject({ status: 'delivered' })
    expect(advice).toHaveBeenCalledWith('take a break')
    expect(controller.state.activity).toBe('idle')
  })

  it('gates all proactive effects before delivery in deterministic order', async () => {
    const emotion = vi.fn()
    const motion = vi.fn()
    const advice = vi.fn()
    const notification = vi.fn()
    let dnd = true
    const controller = createCompanionRuntimeController({
      pollSnapshot: async () => ({
        heartbeat: { behavior_events: [event()] },
        companion_state: { interruptibility: 1 },
      } as never),
      isAvailable: () => true,
      readDoNotDisturb: async () => dnd,
      sinks: { emotion, motion, advice, notification },
      cooldownMs: 0,
      frequencyBudget: 10,
    })

    expect(await controller.pollOnce()).toBe('dnd')
    expect([emotion, motion, advice, notification].map((sink) => sink.mock.calls.length)).toEqual([0, 0, 0, 0])
    dnd = false
    expect(await controller.pollOnce()).toMatchObject({ status: 'delivered' })
    expect([emotion, motion, advice, notification].map((sink) => sink.mock.calls.length)).toEqual([1, 1, 1, 1])
    expect(await controller.pollOnce()).toBe('duplicate_or_invalid')
  })

  it('starts and stops one polling loop and ignores late results after stop', async () => {
    vi.useFakeTimers()
    let resolvePoll!: (value: unknown) => void
    const pollSnapshot = vi.fn(() => new Promise((resolve) => { resolvePoll = resolve }))
    const controller = createCompanionRuntimeController({
      pollSnapshot,
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      sinks: {},
      pollIntervalMs: 1000,
    })
    controller.start()
    controller.start()
    await vi.advanceTimersByTimeAsync(1000)
    expect(pollSnapshot).toHaveBeenCalledTimes(1)
    controller.stop()
    controller.stop()
    resolvePoll({ heartbeat: { behavior_events: [event()] } })
    await Promise.resolve()
    expect(controller.deliveredIdentities.size).toBe(0)
    vi.useRealTimers()
  })

  it('uses a low-frequency default polling interval', async () => {
    vi.useFakeTimers()
    const pollSnapshot = vi.fn(async () => ({ heartbeat: { behavior_events: [] } } as never))
    const controller = createCompanionRuntimeController({
      pollSnapshot,
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      sinks: {},
    })

    controller.start()
    await vi.advanceTimersByTimeAsync(59_999)
    expect(pollSnapshot).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1)
    expect(pollSnapshot).toHaveBeenCalledTimes(1)
    controller.stop()
    vi.useRealTimers()
  })

  it('pauses only proactive polling while the renderer is hidden', async () => {
    vi.useFakeTimers()
    const pollSnapshot = vi.fn(async () => ({ heartbeat: { behavior_events: [] } } as never))
    const controller = createCompanionRuntimeController({
      pollSnapshot,
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      sinks: {},
      pollIntervalMs: 1000,
    })

    controller.start()
    controller.setPollingEnabled(false)
    await vi.advanceTimersByTimeAsync(3000)
    expect(pollSnapshot).not.toHaveBeenCalled()

    controller.setPollingEnabled(true)
    await vi.advanceTimersByTimeAsync(1000)
    expect(pollSnapshot).toHaveBeenCalledTimes(1)
    controller.stop()
    vi.useRealTimers()
  })

  it.each(['interrupt', 'stop'] as const)(
    'invalidates a poll blocked on DND after %s without delivery bookkeeping',
    async (action) => {
      const dnd = deferred<boolean>()
      const sinks = { emotion: vi.fn(), motion: vi.fn(), advice: vi.fn(), notification: vi.fn() }
      const controller = createCompanionRuntimeController({
        pollSnapshot: async () => ({
          heartbeat: { behavior_events: [event()] },
          companion_state: { interruptibility: 1 },
        } as never),
        isAvailable: () => true,
        readDoNotDisturb: vi.fn(() => dnd.promise),
        sinks,
        cooldownMs: 60_000,
        frequencyBudget: 1,
      })

      const pending = controller.pollOnce()
      await vi.waitFor(() => expect(controller.lastSnapshot.value).not.toBeNull())
      if (action === 'interrupt') await controller.interrupt('chat', 1)
      else controller.stop()
      dnd.resolve(false)

      expect(await pending).toBe('stopped')
      expect([sinks.emotion, sinks.motion, sinks.advice, sinks.notification].map((sink) => sink.mock.calls.length)).toEqual([0, 0, 0, 0])
      expect(controller.deliveredIdentities.size).toBe(0)

      controller.configure({ readDoNotDisturb: async () => false })
      expect(await controller.pollOnce()).toMatchObject({ status: 'delivered' })
      expect(controller.deliveredIdentities.size).toBe(1)
    },
  )

  it.each(
    (['interrupt', 'stop'] as const).flatMap((action) =>
      (['emotion', 'motion', 'advice', 'notification'] as const).map((sink) => ({ action, sink })),
    ),
  )('stops after an awaited $sink sink is invalidated by $action', async ({ action, sink: blockedSink }) => {
    const blocked = deferred<void>()
    const sinks = {
      emotion: vi.fn(async () => undefined),
      motion: vi.fn(async () => undefined),
      advice: vi.fn(async () => undefined),
      notification: vi.fn(async () => undefined),
    }
    sinks[blockedSink].mockImplementation(() => blocked.promise)
    const controller = createCompanionRuntimeController({
      pollSnapshot: async () => ({
        heartbeat: { behavior_events: [event()] },
        companion_state: { interruptibility: 1 },
      } as never),
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      sinks,
      cooldownMs: 0,
      frequencyBudget: 10,
    })

    const pending = controller.pollOnce()
    await vi.waitFor(() => expect(sinks[blockedSink]).toHaveBeenCalledOnce())
    if (action === 'interrupt') await controller.interrupt('chat', 1)
    else controller.stop()
    blocked.resolve()

    expect(await pending).toBe('stopped')
    const orderedSinks = ['emotion', 'motion', 'advice', 'notification'] as const
    for (const laterSink of orderedSinks.slice(orderedSinks.indexOf(blockedSink) + 1)) {
      expect(sinks[laterSink]).not.toHaveBeenCalled()
    }
    expect(controller.deliveredIdentities.size).toBe(0)
  })

  it.each(
    (['interrupt', 'stop'] as const).flatMap((action) =>
      (['emotion', 'motion'] as const).map((sink) => ({ action, sink })),
    ),
  )('aborts a pending proactive $sink transport on $action', async ({ action, sink: blockedSink }) => {
    let tick = 0
    const signals: AbortSignal[] = []
    const onSinkError = vi.fn()
    const blockedTransport = vi.fn((_value: string, context: { signal: AbortSignal; eventVersion: string }) => {
      signals.push(context.signal)
      if (signals.length > 1) return Promise.resolve()
      return new Promise<void>((_resolve, reject) => {
        context.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true })
      })
    })
    const sinks = {
      emotion: blockedSink === 'emotion' ? blockedTransport : vi.fn(async () => undefined),
      motion: blockedSink === 'motion' ? blockedTransport : vi.fn(async () => undefined),
      advice: vi.fn(),
      notification: vi.fn(),
    }
    const controller = createCompanionRuntimeController({
      pollSnapshot: async () => ({
        heartbeat: { behavior_events: [event({ tick: ++tick, at: `t${tick}` })] },
        companion_state: { interruptibility: 1 },
      } as never),
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      sinks,
      onSinkError,
      cooldownMs: 0,
      frequencyBudget: 1,
    })

    const pending = controller.pollOnce()
    await vi.waitFor(() => expect(blockedTransport).toHaveBeenCalledOnce())
    const firstContext = blockedTransport.mock.calls[0]?.[1]
    expect(firstContext?.eventVersion).toBe('suggestion:1:t1')
    expect(firstContext?.signal.aborted).toBe(false)

    if (action === 'interrupt') await controller.interrupt('chat', 1)
    else controller.stop()

    expect(firstContext?.signal.aborted).toBe(true)
    expect(await pending).toBe('stopped')
    expect(sinks.advice).not.toHaveBeenCalled()
    expect(sinks.notification).not.toHaveBeenCalled()
    expect(controller.deliveredIdentities.size).toBe(0)
    expect(controller.state.suppressionCounts.unavailable).toBe(0)
    expect(controller.state.availability).toBe('online')
    expect(onSinkError).not.toHaveBeenCalled()

    expect(await controller.pollOnce()).toMatchObject({ status: 'delivered' })
    expect(signals[1]).not.toBe(firstContext?.signal)
    expect(signals[1]?.aborted).toBe(false)
    expect(controller.deliveredIdentities.size).toBe(1)
  })

  it('pauses requests while unavailable and resumes one existing loop after recovery', async () => {
    vi.useFakeTimers()
    let available = false
    const pollSnapshot = vi.fn(async () => ({ heartbeat: { behavior_events: [] } } as never))
    const controller = createCompanionRuntimeController({
      pollSnapshot,
      isAvailable: () => available,
      readDoNotDisturb: async () => false,
      sinks: {},
      pollIntervalMs: 1000,
    })
    controller.start()
    controller.start()
    await vi.advanceTimersByTimeAsync(2000)
    expect(pollSnapshot).not.toHaveBeenCalled()
    available = true
    await vi.advanceTimersByTimeAsync(1000)
    expect(pollSnapshot).toHaveBeenCalledTimes(1)
    controller.stop()
    vi.useRealTimers()
  })

  it('observes failed results from the scheduled polling loop', async () => {
    vi.useFakeTimers()
    const onPollResult = vi.fn()
    const controller = createCompanionRuntimeController({
      pollSnapshot: async () => ({
        heartbeat: { behavior_events: [event()] },
        companion_state: { interruptibility: 1 },
      } as never),
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      sinks: { emotion: vi.fn().mockRejectedValue(new Error('sink down')) },
      onPollResult,
      pollIntervalMs: 1000,
      cooldownMs: 0,
    })

    controller.start()
    await vi.advanceTimersByTimeAsync(1000)
    expect(onPollResult).toHaveBeenCalledWith(expect.objectContaining({
      status: 'failed',
      attempted: ['emotion'],
      failed: [{ sink: 'emotion', message: 'sink down' }],
    }))
    controller.stop()
    vi.useRealTimers()
  })

  it('atomically clears timed activity before a singleton controller remount', async () => {
    vi.useFakeTimers()
    const behavior = vi.fn()
    const controller = createCompanionRuntimeController({
      pollSnapshot: vi.fn(),
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      sinks: { behavior },
    })

    controller.start()
    await controller.publish({
      source: 'chat',
      sequence: 1,
      activity: 'executing',
      requestId: 'req-before-remount',
      durationMs: 5000,
    })
    expect(controller.state.activity).toBe('executing')

    controller.stop()
    expect(controller.state.activity).toBe('idle')
    expect(controller.state.lastRequestId).toBeNull()
    expect(controller.presentationState.value).toBe('idle')
    controller.start()
    await vi.advanceTimersByTimeAsync(5000)

    expect(controller.state.activity).toBe('idle')
    expect(controller.presentationState.value).toBe('idle')
    expect(behavior).toHaveBeenLastCalledWith('idle', undefined)
    controller.stop()
    vi.useRealTimers()
  })

  it('does not replay a delivered identity after stop and remount', async () => {
    const notification = vi.fn()
    const controller = createCompanionRuntimeController({
      pollSnapshot: async () => ({ heartbeat: { behavior_events: [event()] } } as never),
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      sinks: { notification },
      cooldownMs: 0,
      frequencyBudget: 10,
    })
    controller.start()
    expect(await controller.pollOnce()).toMatchObject({ status: 'delivered' })
    controller.stop()
    controller.start()
    expect(await controller.pollOnce()).toBe('duplicate_or_invalid')
    controller.stop()
  })

  it('does not replay a resolved heartbeat opportunity after remount', async () => {
    const notification = vi.fn()
    const controller = createCompanionRuntimeController({
      pollSnapshot: async () => ({
        heartbeat: { behavior_events: [event({
          job_id: 'resolved-job',
          request_id: 'resolved-request',
        })] },
        jobs: { events: [], active_job_ids: [] },
      } as never),
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      sinks: { notification },
    })

    expect(await controller.pollOnce()).toBe('empty')
    expect(notification).not.toHaveBeenCalled()
  })

  it('bounds delivered identity history while retaining recent duplicate suppression', async () => {
    let tick = 0
    const notification = vi.fn()
    const controller = createCompanionRuntimeController({
      pollSnapshot: async () => ({
        heartbeat: { behavior_events: [event({ tick: ++tick, at: `t${tick}` })] },
      } as never),
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      sinks: { notification },
      cooldownMs: 0,
      frequencyBudget: 10,
      deliveredIdentityLimit: 3,
    })

    await controller.pollOnce()
    await controller.pollOnce()
    await controller.pollOnce()
    await controller.pollOnce()

    expect(controller.deliveredIdentities.size).toBe(3)
    expect(controller.deliveredIdentities.has('suggestion:1:t1')).toBe(false)
    expect(controller.deliveredIdentities.has('suggestion:4:t4')).toBe(true)
  })

  it('applies unavailable, eligibility, cooldown, and frequency gates before effects', async () => {
    const sinks = { emotion: vi.fn(), motion: vi.fn(), advice: vi.fn(), notification: vi.fn() }
    const unavailablePoll = vi.fn()
    const unavailable = createCompanionRuntimeController({
      pollSnapshot: unavailablePoll,
      isAvailable: () => false,
      readDoNotDisturb: async () => false,
      sinks,
    })
    expect(await unavailable.pollOnce()).toBe('unavailable')
    expect(unavailablePoll).not.toHaveBeenCalled()

    const ineligible = createCompanionRuntimeController({
      pollSnapshot: async () => ({ heartbeat: { behavior_events: [event({ proactive_state: { can_proactively_reach_out: false } })] } } as never),
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      sinks,
    })
    expect(await ineligible.pollOnce()).toBe('ineligible')

    let tick = 0
    const cooldown = createCompanionRuntimeController({
      pollSnapshot: async () => ({ heartbeat: { behavior_events: [event({ tick: ++tick, at: `t${tick}` })] } } as never),
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      sinks,
      now: () => 1000,
      cooldownMs: 5000,
      frequencyBudget: 10,
    })
    expect(await cooldown.pollOnce()).toMatchObject({ status: 'delivered' })
    expect(await cooldown.pollOnce()).toBe('cooldown')

    tick = 0
    const frequency = createCompanionRuntimeController({
      pollSnapshot: async () => ({ heartbeat: { behavior_events: [event({ type: `type-${++tick}`, tick, at: `t${tick}` })] } } as never),
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      sinks,
      now: () => 1000,
      cooldownMs: 0,
      frequencyBudget: 1,
    })
    expect(await frequency.pollOnce()).toMatchObject({ status: 'delivered' })
    expect(await frequency.pollOnce()).toBe('frequency_budget')
  })

  it('reports delivery and suppression against the heartbeat opportunity identity', async () => {
    const reportOpportunityOutcome = vi.fn(async () => undefined)
    const notification = vi.fn()
    let dnd = true
    let tick = 0
    const controller = createCompanionRuntimeController({
      pollSnapshot: async () => ({
        heartbeat: { behavior_events: [event({
          tick: ++tick,
          at: `t${tick}`,
          job_id: `heartbeat-job-${tick}`,
          request_id: `heartbeat-request-${tick}`,
        })] },
        companion_state: { interruptibility: 1 },
      } as never),
      isAvailable: () => true,
      readDoNotDisturb: async () => dnd,
      sinks: { notification },
      reportOpportunityOutcome,
      cooldownMs: 0,
      frequencyBudget: 10,
    })

    expect(await controller.pollOnce()).toBe('dnd')
    expect(reportOpportunityOutcome).toHaveBeenLastCalledWith(
      'heartbeat-job-1', 'heartbeat-request-1', 'suppressed', 'dnd',
    )
    dnd = false
    expect(await controller.pollOnce()).toMatchObject({ status: 'delivered' })
    expect(reportOpportunityOutcome).toHaveBeenLastCalledWith(
      'heartbeat-job-2', 'heartbeat-request-2', 'delivered', 'delivered',
    )
  })

  it('does not repeat proactive effects when outcome reporting temporarily fails', async () => {
    const reportOpportunityOutcome = vi.fn()
      .mockRejectedValueOnce(new Error('control server unavailable'))
      .mockResolvedValue(undefined)
    const notification = vi.fn()
    const job = {
      version: 1 as const,
      type: 'AgentJobCreated' as const,
      workspaceId: 'default',
      sessionId: 'heartbeat',
      turnId: 'heartbeat:1',
      jobId: 'heartbeat-job-retry',
      requestId: 'heartbeat-request-retry',
      revision: 1,
      interruptionEpoch: 0,
      source: 'heartbeat' as const,
      timestamp: 1_000,
      status: 'created' as const,
      data: { behaviorType: 'suggestion', tick: 1 },
    }
    const snapshot = {
      active_workspace_id: 'default',
      heartbeat: { behavior_events: [event({
        job_id: job.jobId,
        request_id: job.requestId,
      })] },
      jobs: { events: [job], active_job_ids: [job.jobId] },
      companion_state: { interruptibility: 1 },
    }
    const controller = createCompanionRuntimeController({
      pollSnapshot: async () => snapshot as never,
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      sinks: { notification },
      reportOpportunityOutcome,
      cooldownMs: 0,
      frequencyBudget: 10,
    })

    expect(await controller.pollOnce()).toMatchObject({ status: 'delivered' })
    expect(notification).toHaveBeenCalledOnce()
    expect(await controller.pollOnce()).toBe('duplicate_or_invalid')
    expect(notification).toHaveBeenCalledOnce()
    expect(reportOpportunityOutcome).toHaveBeenCalledTimes(2)
  })

  it('expires an opportunity before invoking proactive sinks', async () => {
    const reportOpportunityOutcome = vi.fn(async () => undefined)
    const emotion = vi.fn()
    const controller = createCompanionRuntimeController({
      pollSnapshot: async () => ({ heartbeat: { behavior_events: [event({
        job_id: 'heartbeat-job-expired',
        request_id: 'heartbeat-request-expired',
        expires_at: 1,
      })] } } as never),
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      sinks: { emotion },
      reportOpportunityOutcome,
      now: () => 2_000,
    })

    expect(await controller.pollOnce()).toBe('ineligible')
    expect(emotion).not.toHaveBeenCalled()
    expect(reportOpportunityOutcome).toHaveBeenCalledWith(
      'heartbeat-job-expired', 'heartbeat-request-expired', 'expired', 'delivery_window_elapsed',
    )
  })

  it('expires timed activity only while its sequence, request, and interruption epoch are current', async () => {
    vi.useFakeTimers()
    const controller = createCompanionRuntimeController({
      pollSnapshot: vi.fn(),
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      sinks: {},
    })

    await controller.publish({ source: 'chat', sequence: 1, activity: 'thinking', requestId: 'req-1', interruptionEpoch: 0 })
    await controller.publish({ source: 'chat', sequence: 2, activity: 'idle', requestId: 'req-1', interruptionEpoch: 0 })
    await controller.publish({ source: 'chat', sequence: 3, activity: 'executing', requestId: 'req-1', interruptionEpoch: 0, durationMs: 1000 })
    await controller.publish({ source: 'chat', sequence: 4, activity: 'speaking', requestId: 'req-1', interruptionEpoch: 0 })
    await vi.advanceTimersByTimeAsync(1000)
    expect(controller.state.activity).toBe('speaking')

    await controller.publish({ source: 'chat', sequence: 5, activity: 'idle', requestId: 'req-1', interruptionEpoch: 0 })
    expect(controller.state.activity).toBe('idle')
    await controller.publish({ source: 'chat', sequence: 6, activity: 'executing', requestId: 'req-2', interruptionEpoch: 0, durationMs: 1000 })
    await controller.interrupt('chat', 7)
    expect(controller.state.activity).toBe('idle')
    expect(await controller.publish({ source: 'chat', sequence: 8, activity: 'speaking', requestId: 'req-2', interruptionEpoch: 0 })).toBe(false)
    await vi.advanceTimersByTimeAsync(1000)
    expect(controller.presentationState.value).toBe('interrupted')
    vi.useRealTimers()
  })

  it('does not let an older poll success or failure replace a newer offline health state', async () => {
    let resolvePoll!: (value: unknown) => void
    let rejectPoll!: (reason: unknown) => void
    const available = true
    const first = createCompanionRuntimeController({
      pollSnapshot: () => new Promise((resolve) => { resolvePoll = resolve }),
      isAvailable: () => available,
      readDoNotDisturb: async () => false,
      sinks: {},
    })
    const pendingSuccess = first.pollOnce()
    await first.publish({ source: 'health', sequence: 1, availability: 'offline' })
    resolvePoll({ heartbeat: { behavior_events: [] } })
    expect(await pendingSuccess).toBe('stopped')
    expect(first.state.availability).toBe('offline')

    const second = createCompanionRuntimeController({
      pollSnapshot: () => new Promise((_resolve, reject) => { rejectPoll = reject }),
      isAvailable: () => available,
      readDoNotDisturb: async () => false,
      sinks: {},
    })
    const pendingFailure = second.pollOnce()
    await second.publish({ source: 'health', sequence: 1, availability: 'offline' })
    rejectPoll(new Error('late failure'))
    expect(await pendingFailure).toBe('stopped')
    expect(second.state.availability).toBe('offline')
  })

  it('reports partial and failed proactive delivery with sink diagnostics', async () => {
    const failures: Array<{ sink: string; message: string }> = []
    const controller = createCompanionRuntimeController({
      pollSnapshot: async () => ({ heartbeat: { behavior_events: [event()] }, companion_state: { interruptibility: 1 } } as never),
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      sinks: {
        emotion: vi.fn(),
        motion: vi.fn().mockRejectedValue(new Error('motion unavailable')),
        advice: vi.fn().mockRejectedValue(new Error('advice unavailable')),
        notification: vi.fn(),
      },
      onSinkError: (failure) => failures.push(failure),
      cooldownMs: 0,
    })

    expect(await controller.pollOnce()).toEqual({
      status: 'partial',
      attempted: ['emotion', 'motion', 'advice', 'notification'],
      succeeded: ['emotion', 'notification'],
      failed: [
        { sink: 'motion', message: 'motion unavailable' },
        { sink: 'advice', message: 'advice unavailable' },
      ],
    })
    expect(failures).toEqual([
      { sink: 'motion', message: 'motion unavailable' },
      { sink: 'advice', message: 'advice unavailable' },
    ])
  })

  it('terminates the heartbeat job as failed when every attempted sink fails', async () => {
    const reportOpportunityOutcome = vi.fn(async () => undefined)
    const controller = createCompanionRuntimeController({
      pollSnapshot: async () => ({
        heartbeat: { behavior_events: [event({ job_id: 'heartbeat-failed', request_id: 'request-failed', emotion_id: 'sad' })] },
        companion_state: { interruptibility: 1 },
      } as never),
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      sinks: { emotion: vi.fn().mockRejectedValue(new Error('sink unavailable')) },
      reportOpportunityOutcome,
      cooldownMs: 0,
    })

    expect(await controller.pollOnce()).toMatchObject({ status: 'failed' })
    expect(reportOpportunityOutcome).toHaveBeenCalledWith(
      'heartbeat-failed', 'request-failed', 'failed', 'all_visible_sinks_failed',
    )
  })

  it('does not report absent sinks as attempted deliveries', async () => {
    const controller = createCompanionRuntimeController({
      pollSnapshot: async () => ({ heartbeat: { behavior_events: [event()] }, companion_state: { interruptibility: 1 } } as never),
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      sinks: {},
      cooldownMs: 0,
    })

    expect(await controller.pollOnce()).toEqual({
      status: 'failed',
      attempted: [],
      succeeded: [],
      failed: [],
    })
  })

  it('keeps Chat and Voice as publishers and AppShell as the single poll owner', () => {
    const source = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8')
    const chat = source('src/renderer/stores/chatStore.ts')
    const voice = source('src/renderer/app/composables/useVoiceConversationBridge.ts')
    const runtimeBridge = source('src/renderer/app/composables/useCompanionRuntimeBridge.ts')
    const shell = source('src/renderer/app/AppShell.vue')

    expect(chat).toContain('publishCompanionRuntimeEvent')
    expect(voice).toContain('publishCompanionRuntimeEvent')
    expect(voice).toContain('interruptionEpoch: voiceRuntimeEpoch')
    expect(runtimeBridge).toContain('onSinkError: reportCompanionRuntimeSinkError')
    expect(runtimeBridge).toContain('onPollResult: reportCompanionRuntimePollResult')
    expect(chat).not.toContain("petControl.setBehaviorState(")
    expect(voice).not.toContain("petControl.setBehaviorState(")
    expect(shell).toContain('startCompanionRuntime')
    expect(shell).not.toContain('systemClient.companionRuntime')
    expect(runtimeBridge).toContain('resolveCompanionEmbodimentDelivery')
    expect(runtimeBridge).toContain('resolved.motionAllowed')
    expect(runtimeBridge).toContain("resolved.behavior === 'waiting' ? 'waiting' : 'idle'")
  })
})
