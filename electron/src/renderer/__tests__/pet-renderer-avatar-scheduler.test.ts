import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AvatarCapabilitySnapshot, AvatarCommand } from '../../shared/avatar-command'
import { PetRenderer } from '../pet-renderer'

const createdRenderers: PetRenderer[] = []

type TestablePetRenderer = {
  config: { modelType: 'live2d' | 'vrm' }
  vrmRuntime: unknown
  avatarCapabilities: AvatarCapabilitySnapshot | null
  executeAvatarCommand: (value: unknown) => void
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
})
