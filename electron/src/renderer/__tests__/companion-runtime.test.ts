import { describe, expect, it, vi } from 'vitest'
import { createCompanionRuntimeController } from '../app/runtime/companionRuntime'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

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
    const controller = createCompanionRuntimeController({
      pollSnapshot: async () => ({ heartbeat: { behavior_events: [event()] } } as never),
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      sinks: {},
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

  it('bounds delivered identity history while retaining recent duplicate suppression', async () => {
    let tick = 0
    const controller = createCompanionRuntimeController({
      pollSnapshot: async () => ({
        heartbeat: { behavior_events: [event({ tick: ++tick, at: `t${tick}` })] },
      } as never),
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      sinks: {},
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

  it('does not report absent sinks as attempted deliveries', async () => {
    const controller = createCompanionRuntimeController({
      pollSnapshot: async () => ({ heartbeat: { behavior_events: [event()] }, companion_state: { interruptibility: 1 } } as never),
      isAvailable: () => true,
      readDoNotDisturb: async () => false,
      sinks: {},
      cooldownMs: 0,
    })

    expect(await controller.pollOnce()).toEqual({
      status: 'delivered',
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
    const companion = source('src/renderer/domains/companion/views/CompanionPanel.vue')

    expect(chat).toContain('publishCompanionRuntimeEvent')
    expect(voice).toContain('publishCompanionRuntimeEvent')
    expect(voice).toContain('interruptionEpoch: voiceRuntimeEpoch')
    expect(runtimeBridge).toContain('onSinkError: reportCompanionRuntimeSinkError')
    expect(runtimeBridge).toContain('onPollResult: reportCompanionRuntimePollResult')
    expect(chat).not.toContain("petControl.setBehaviorState(")
    expect(voice).not.toContain("petControl.setBehaviorState(")
    expect(shell).toContain('startCompanionRuntime')
    expect(shell).not.toContain('systemClient.companionRuntime')
    expect(companion).not.toContain('runtimeRefreshTimer')
  })
})
