import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { legacyDirectiveToAvatarCommand, type AvatarCapabilitySnapshot, type AvatarCommand } from '../../shared/avatar-command'
import { PetRenderer } from '../pet-renderer'

const createdRenderers: PetRenderer[] = []

type TestablePetRenderer = {
  app: unknown
  config: { modelType: 'live2d' | 'vrm' }
  live2dRuntime: unknown
  vrmRuntime: unknown
  avatarCapabilities: AvatarCapabilitySnapshot | null
  executeAvatarCommand: (value: unknown) => void
  setExternalLipSync: (payload: { level: number; active: boolean; source: 'realtime' | 'tts-pcm' }) => void
  beginModelLoadGeneration: () => number
  waitForModelLoadRetry: (delayMs: number, generation: number) => Promise<boolean>
  loadRuntimeWithRecovery: (load: () => Promise<void>, generation: number, modelType: 'live2d' | 'vrm') => Promise<void>
  showNotice: (text: string) => void
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

const fullCapabilities: AvatarCapabilitySnapshot = {
  ...capabilities,
  actions: {
    ...capabilities.actions,
    motion: true,
    parameterPatch: true,
  },
  motions: [{ group: 'Wave', index: 0, label: 'Wave' }],
  parameters: [{ id: 'ParamAngleX', min: -30, max: 30, modes: ['set'] }],
}

let reducedMotion = false

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
    reducedMotion = false
    vi.stubGlobal('matchMedia', vi.fn().mockImplementation((query: string) => ({
      matches: query === '(prefers-reduced-motion: reduce)' && reducedMotion,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })))
    document.body.innerHTML = '<div id="pet"></div><div id="pet-canvas"></div>'
    window.live2dApi = {
      pet: {
        reportAvatarCommandResult: vi.fn(),
        reportAvatarCapabilities: vi.fn(),
        reportState: vi.fn(),
      },
    } as never
  })

  afterEach(() => {
    createdRenderers.splice(0).forEach((renderer) => renderer.destroy())
    vi.clearAllTimers()
    vi.useRealTimers()
    vi.unstubAllGlobals()
    document.body.innerHTML = ''
  })

  const setup = (activeCapabilities = capabilities) => {
    const rendererInstance = new PetRenderer('pet')
    const renderer = rendererInstance as unknown as TestablePetRenderer
    const runtime = {
      modelType: 'vrm',
      getCapabilities: () => activeCapabilities,
      executeAvatarAction: vi.fn(() => ({ status: 'completed' as const })),
      setLipSyncLevel: vi.fn(),
      destroy: vi.fn(),
    }
    renderer.config.modelType = 'vrm'
    renderer.vrmRuntime = runtime
    renderer.avatarCapabilities = activeCapabilities
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

  it('keeps the current same-type runtime alive until its replacement is ready', async () => {
    const rendererInstance = new PetRenderer('pet')
    const renderer = rendererInstance as unknown as TestablePetRenderer
    let resolveLoad: (() => void) | null = null
    const runtime = {
      modelType: 'live2d' as const,
      loadModel: vi.fn(() => new Promise<void>((resolve) => { resolveLoad = resolve })),
      applyConfig: vi.fn(),
      getCapabilities: vi.fn(() => fullCapabilities),
      executeAvatarAction: vi.fn(() => ({ status: 'completed' as const })),
      setCompanionIdleProfile: vi.fn(),
      getState: vi.fn(() => ({ ready: true, modelType: 'live2d' as const })),
      destroy: vi.fn(),
    }
    renderer.app = { destroy: vi.fn() }
    renderer.config.modelType = 'live2d'
    renderer.live2dRuntime = runtime
    renderer.avatarCapabilities = capabilities
    createdRenderers.push(rendererInstance)

    const replacement = rendererInstance.loadModel('./replacement.model3.json')
    await Promise.resolve()

    expect(runtime.loadModel).toHaveBeenCalledTimes(1)
    expect(runtime.destroy).not.toHaveBeenCalled()
    expect(renderer.avatarCapabilities).toBe(capabilities)

    resolveLoad?.()
    await replacement

    expect(runtime.destroy).not.toHaveBeenCalled()
    expect(renderer.avatarCapabilities).toBe(fullCapabilities)
  })

  it('shows retry progress while a model load is recovering', async () => {
    const { renderer } = setup()
    const showNotice = vi.fn()
    renderer.showNotice = showNotice
    const generation = renderer.beginModelLoadGeneration()
    let attempts = 0
    const load = vi.fn(async () => {
      attempts += 1
      if (attempts === 1) throw new Error('temporary asset read failure')
    })

    const recovery = renderer.loadRuntimeWithRecovery(load, generation, 'vrm')
    for (let index = 0; index < 6; index += 1) await Promise.resolve()
    expect(showNotice).toHaveBeenCalledWith(expect.stringContaining('正在重试 (1/3)'))

    vi.advanceTimersByTime(250)
    await recovery
    expect(load).toHaveBeenCalledTimes(2)
  })

  it('turns a hung model load into the visible retry path', async () => {
    const { renderer } = setup()
    const showNotice = vi.fn()
    renderer.showNotice = showNotice
    const generation = renderer.beginModelLoadGeneration()
    let attempts = 0
    const load = vi.fn(() => {
      attempts += 1
      if (attempts === 1) return new Promise<void>(() => undefined)
      return Promise.resolve()
    })

    const recovery = renderer.loadRuntimeWithRecovery(load, generation, 'vrm')
    for (let index = 0; index < 6; index += 1) await Promise.resolve()
    vi.advanceTimersByTime(20_000)
    for (let index = 0; index < 6; index += 1) await Promise.resolve()
    expect(showNotice).toHaveBeenCalledWith(expect.stringContaining('正在重试 (1/3)'))

    vi.advanceTimersByTime(250)
    await recovery
    expect(load).toHaveBeenCalledTimes(2)
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

  it('executes a degraded expression command with the model fallback instead of dropping it', () => {
    const { renderer, runtime, report } = setup()
    renderer.executeAvatarCommand(command({
      id: 'fallback-expression',
      sequence: 0,
      actions: [{ type: 'expression', name: 'surprised', weight: 0.7 }],
    }))

    expect(runtime.executeAvatarAction).toHaveBeenCalledWith({
      type: 'expression',
      name: 'happy',
      weight: 0.7,
    })
    expect(report).toHaveBeenLastCalledWith(expect.objectContaining({
      commandId: 'fallback-expression',
      status: 'degraded',
      message: expect.stringContaining("used 'happy'"),
    }))
  })

  it('applies reduced-motion policy to direct commands and restores motion without recreating the renderer', () => {
    reducedMotion = true
    const { renderer, runtime, report } = setup(fullCapabilities)
    renderer.executeAvatarCommand(command({
      id: 'reduced-motion',
      sequence: 0,
      actions: [
        { type: 'behavior', behavior: 'react', durationMs: 400 },
        { type: 'affect', emotion: 'happy', intensity: 0.9 },
        { type: 'gaze', target: { x: 1, y: 0 }, strength: 0.9 },
        { type: 'motion', group: 'Wave', index: 0, intensity: 0.9 },
        { type: 'expression', name: 'happy', weight: 0.8 },
        { type: 'parameterPatch', patches: [{ id: 'ParamAngleX', value: 20, mode: 'set' }] },
        { type: 'viseme', viseme: 'aa', weight: 0.8, active: true },
      ],
    }))

    const reducedActions = runtime.executeAvatarAction.mock.calls.map(([action]) => action)
    expect(reducedActions).toContainEqual({ type: 'behavior', behavior: 'think' })
    expect(reducedActions).toContainEqual({ type: 'affect', emotion: 'happy', intensity: 0.35, motion: null })
    expect(reducedActions).toContainEqual({ type: 'expression', name: 'happy', weight: 0.35 })
    expect(reducedActions).toContainEqual({ type: 'viseme', viseme: 'aa', weight: 0.8, active: true })
    expect(reducedActions.some(action => ['motion', 'gaze', 'parameterPatch'].includes(action.type))).toBe(false)
    expect(report).toHaveBeenLastCalledWith(expect.objectContaining({
      commandId: 'reduced-motion',
      status: 'degraded',
      message: expect.stringContaining('reduced-motion preference'),
    }))

    reducedMotion = false
    runtime.executeAvatarAction.mockClear()
    renderer.executeAvatarCommand(command({
      id: 'motion-restored',
      sequence: 1,
      actions: [
        { type: 'gaze', target: { x: 1, y: 0 }, strength: 0.9 },
        { type: 'motion', group: 'Wave', index: 0, intensity: 0.9 },
        { type: 'expression', name: 'happy', weight: 0.8 },
        { type: 'parameterPatch', patches: [{ id: 'ParamAngleX', value: 20, mode: 'set' }] },
      ],
    }))

    const restoredActions = runtime.executeAvatarAction.mock.calls.map(([action]) => action)
    expect(restoredActions).toContainEqual({ type: 'gaze', target: { x: 1, y: 0 }, strength: 0.9 })
    expect(restoredActions).toContainEqual({ type: 'motion', group: 'Wave', index: 0, intensity: 0.9 })
    expect(restoredActions).toContainEqual({ type: 'expression', name: 'happy', weight: 0.8 })
    expect(restoredActions).toContainEqual({
      type: 'parameterPatch',
      patches: [{ id: 'ParamAngleX', value: 20, mode: 'set' }],
    })
  })

  it('prevents legacy voice directives from bypassing reduced-motion policy', () => {
    reducedMotion = true
    const { renderer, runtime } = setup(fullCapabilities)
    renderer.executeAvatarCommand(legacyDirectiveToAvatarCommand({
      expressionMix: [{ expression: 'happy', weight: 0.8 }],
      parameterOverrides: [{ id: 'ParamAngleX', value: 20, weight: 1 }],
      motion: { group: 'Wave', index: 0 },
      intensity: 0.9,
      durationMs: 1200,
    }, {
      id: 'legacy-reduced-motion',
      streamId: 'legacy-voice',
      sequence: 0,
      issuedAt: Date.now(),
    }))

    const actions = runtime.executeAvatarAction.mock.calls.map(([action]) => action)
    expect(actions).toContainEqual({ type: 'expression', name: 'happy', weight: 0.35, fadeOutMs: 1200 })
    expect(actions.some(action => action.type === 'motion' || action.type === 'parameterPatch')).toBe(false)
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
