import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AvatarCapabilitySnapshot, AvatarCommand } from '../../shared/avatar-command'
import { PetRenderer } from '../pet-renderer'

const createdRenderers: PetRenderer[] = []

type TestablePetRenderer = {
  config: { modelType: 'live2d' | 'vrm' }
  vrmRuntime: unknown
  avatarCapabilities: AvatarCapabilitySnapshot | null
  executeAvatarCommand: (value: unknown) => void
  setExternalLipSync: (payload: { level: number; active: boolean; source: 'realtime' | 'tts-pcm' }) => void
  beginModelLoadGeneration: () => number
  waitForModelLoadRetry: (delayMs: number, generation: number) => Promise<boolean>
  destroy: () => void
}

const capabilities: AvatarCapabilitySnapshot = {
  revision: 'vrm:test:1',
  modelType: 'vrm',
  modelId: 'test',
  generatedAt: 1,
  actions: {
    behavior: true,
    affect: true,
    gaze: true,
    motion: false,
    expression: true,
    parameterPatch: false,
    viseme: true,
    cancel: true,
  },
  expressions: ['happy'],
  motions: [],
  parameters: [],
}

const command = (overrides: Partial<AvatarCommand>): AvatarCommand => ({
  version: 1,
  id: `command-${Math.random()}`,
  streamId: 'test-stream',
  sequence: 0,
  issuedAt: Date.now(),
  priority: 50,
  interrupt: 'replace',
  actions: [{ type: 'behavior', behavior: 'idle', durationMs: 50 }],
  ...overrides,
})

describe('PetRenderer AvatarCommand scheduling', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    document.body.innerHTML = '<div id="pet"></div><div id="pet-canvas"></div>'
    window.live2dApi = {
      pet: {
        reportAvatarCommandResult: vi.fn(),
      },
    } as never
  })

  afterEach(() => {
    createdRenderers.splice(0).forEach((renderer) => renderer.destroy())
    vi.clearAllTimers()
    vi.useRealTimers()
    document.body.innerHTML = ''
  })

  const setup = () => {
    const rendererInstance = new PetRenderer('pet')
    const renderer = rendererInstance as unknown as TestablePetRenderer
    const runtime = {
      modelType: 'vrm',
      getCapabilities: () => capabilities,
      executeAvatarAction: vi.fn(() => ({ status: 'completed' as const })),
      setLipSyncLevel: vi.fn(),
      destroy: vi.fn(),
    }
    renderer.config.modelType = 'vrm'
    renderer.vrmRuntime = runtime
    renderer.avatarCapabilities = capabilities
    createdRenderers.push(rendererInstance)
    return { renderer, runtime, report: window.live2dApi.pet.reportAvatarCommandResult as ReturnType<typeof vi.fn> }
  }

  it('imports the renderer class without starting the pet window', () => {
    expect((window as typeof window & { petRenderer?: unknown }).petRenderer).toBeUndefined()
  })

  it('keeps sequence ordering independent for each producer stream', () => {
    const { renderer, runtime } = setup()
    renderer.executeAvatarCommand(command({ id: 'a', streamId: 'a', sequence: 0 }))
    renderer.executeAvatarCommand(command({ id: 'b', streamId: 'b', sequence: 0 }))

    expect(runtime.executeAvatarAction).toHaveBeenCalledTimes(4)
  })

  it('queues commands and honors startAt without blocking the renderer loop', () => {
    const { renderer, runtime } = setup()
    const now = Date.now()
    renderer.executeAvatarCommand(command({ id: 'queued', sequence: 0, interrupt: 'queue' }))
    renderer.executeAvatarCommand(command({
      id: 'scheduled',
      sequence: 1,
      interrupt: 'queue',
      startAt: now + 100,
      expiresAt: now + 1000,
    }))

    expect(runtime.executeAvatarAction).toHaveBeenCalledTimes(1)
    vi.advanceTimersByTime(99)
    expect(runtime.executeAvatarAction).toHaveBeenCalledTimes(1)
    vi.advanceTimersByTime(1)
    expect(runtime.executeAvatarAction).toHaveBeenCalledTimes(2)
  })

  it('cancels scheduled avatar commands when destroyed', () => {
    const { renderer, runtime } = setup()
    const now = Date.now()
    renderer.executeAvatarCommand(command({
      id: 'scheduled-destroy',
      sequence: 0,
      startAt: now + 100,
      expiresAt: now + 1000,
    }))

    runtime.executeAvatarAction.mockClear()
    renderer.destroy()
    vi.advanceTimersByTime(100)

    expect(runtime.executeAvatarAction).not.toHaveBeenCalled()
  })

  it('settles a pending model retry when a newer model supersedes it', async () => {
    const { renderer } = setup()
    const generation = renderer.beginModelLoadGeneration()
    const pendingRetry = renderer.waitForModelLoadRetry(250, generation)

    expect(renderer.beginModelLoadGeneration()).toBe(generation + 1)

    await expect(pendingRetry).resolves.toBe(false)
  })

  it('settles a pending model retry when the renderer is destroyed', async () => {
    const { renderer } = setup()
    const generation = renderer.beginModelLoadGeneration()
    const pendingRetry = renderer.waitForModelLoadRetry(250, generation)

    renderer.destroy()

    await expect(pendingRetry).resolves.toBe(false)
  })

  it('expires ignore priority after the active action window', () => {
    const { renderer, runtime, report } = setup()
    renderer.executeAvatarCommand(command({ id: 'high', sequence: 0, priority: 90 }))
    renderer.executeAvatarCommand(command({ id: 'blocked', sequence: 1, priority: 10, interrupt: 'ignore' }))
    expect(runtime.executeAvatarAction).toHaveBeenCalledTimes(2)
    expect(report).toHaveBeenLastCalledWith(expect.objectContaining({ commandId: 'blocked', status: 'dropped' }))

    vi.advanceTimersByTime(51)
    renderer.executeAvatarCommand(command({ id: 'allowed', sequence: 2, priority: 10, interrupt: 'ignore' }))
    expect(runtime.executeAvatarAction).toHaveBeenCalledTimes(3)
  })

  it('scoped behavior cancel removes the command claim and stale TTL cannot reapply it', () => {
    const { renderer, runtime } = setup()
    renderer.executeAvatarCommand(command({
      id: 'speech',
      sequence: 0,
      actions: [{ type: 'behavior', behavior: 'speak', durationMs: 500 }],
    }))
    renderer.executeAvatarCommand(command({
      id: 'cancel-speech',
      sequence: 1,
      priority: 100,
      interrupt: 'ignore',
      actions: [{ type: 'cancel', commandId: 'speech', channel: 'behavior' }],
    }))

    const callsAfterCancel = runtime.executeAvatarAction.mock.calls.length
    vi.advanceTimersByTime(600)
    expect(runtime.executeAvatarAction).toHaveBeenCalledTimes(callsAfterCancel)
    expect(runtime.executeAvatarAction).toHaveBeenCalledWith({ type: 'cancel', channel: 'behavior' })
  })

  it('global cancel invalidates command behavior timers instead of refreshing stale state', () => {
    const { renderer, runtime } = setup()
    renderer.executeAvatarCommand(command({
      id: 'reaction',
      sequence: 0,
      actions: [{ type: 'behavior', behavior: 'react', durationMs: 500 }],
    }))
    renderer.executeAvatarCommand(command({
      id: 'cancel-all',
      sequence: 1,
      priority: 100,
      interrupt: 'ignore',
      actions: [{ type: 'cancel' }],
    }))

    const callsAfterCancel = runtime.executeAvatarAction.mock.calls.length
    vi.advanceTimersByTime(600)
    expect(runtime.executeAvatarAction).toHaveBeenCalledTimes(callsAfterCancel)
    expect(runtime.executeAvatarAction).toHaveBeenCalledWith({ type: 'cancel' })
  })

  it('replace cancel restores ownerless speaking before applying the replacement command', () => {
    const { renderer, runtime } = setup()
    renderer.setExternalLipSync({ level: 0.7, active: true, source: 'realtime' })
    renderer.executeAvatarCommand(command({
      id: 'old-reaction',
      sequence: 0,
      interrupt: 'queue',
      actions: [{ type: 'behavior', behavior: 'react', durationMs: 500 }],
    }))
    runtime.executeAvatarAction.mockClear()

    renderer.executeAvatarCommand(command({
      id: 'replacement',
      sequence: 1,
      interrupt: 'replace',
      actions: [{ type: 'behavior', behavior: 'think', durationMs: 200 }],
    }))

    expect(runtime.executeAvatarAction.mock.calls.map(([action]) => action)).toEqual([
      { type: 'cancel' },
      { type: 'behavior', behavior: 'speak' },
    ])
    vi.advanceTimersByTime(600)
    expect(runtime.executeAvatarAction.mock.calls.map(([action]) => action)).toEqual([
      { type: 'cancel' },
      { type: 'behavior', behavior: 'speak' },
    ])
  })
})
