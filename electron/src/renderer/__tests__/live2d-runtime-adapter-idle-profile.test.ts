import type { Live2DSprite } from 'easy-live2d'
import type * as PIXI from 'pixi.js'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Live2DCoreModel } from '../runtime/live2d-core-model'

class FakeTicker {
  add = vi.fn()
  remove = vi.fn()
}

class FakeContainer {
  addChild = vi.fn()
  removeChild = vi.fn()
}

class FakeCoreModel implements Live2DCoreModel {
  getParameterValueById(): number {
    return 0
  }

  setParameterValueById(): void {}
}

const fakeCoreModel = new FakeCoreModel()
const fakeModel = {
  anchor: { set: vi.fn() },
  label: '',
  setSize: vi.fn(),
  startMotion: vi.fn(),
  startRandomMotion: vi.fn(),
  setExpression: vi.fn(),
  _model: { _model: fakeCoreModel },
}

vi.mock('../pet-model-runtime', () => ({
  createLive2DModel: vi.fn(() => fakeModel),
  destroyCurrentModel: vi.fn(() => null),
}))

vi.mock('../pet-renderer-core', () => ({
  ensureCubismCore: vi.fn(() => Promise.resolve()),
}))

describe('Live2DRuntimeAdapter companion idle profile replay', () => {
  let Live2DRuntimeAdapter: typeof import('../runtime/live2d-runtime-adapter').Live2DRuntimeAdapter

  beforeAll(async () => {
    ;({ Live2DRuntimeAdapter } = await import('../runtime/live2d-runtime-adapter'))
  }, 30000)

  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('replays the last idle profile after model/controller recreation', async () => {
    const viewport = new FakeContainer()
    let currentModel: Live2DSprite | null = null
    const adapter = new Live2DRuntimeAdapter({
      app: { ticker: new FakeTicker() } as unknown as PIXI.Application,
      getModel: () => currentModel,
      setModel: (model) => {
        currentModel = model
      },
      getViewport: () => viewport as unknown as PIXI.Container,
      ensureViewport: () => viewport as unknown as PIXI.Container,
      config: {
        modelId: 'llm-live2d/yumi',
        modelType: 'live2d',
        modelPath: './live2d/llm-live2d/yumi/yumi.model3.json',
        scale: 0.28,
        positionX: null,
        positionY: null,
        placement: 'bottom-right',
      },
      showNotice: vi.fn(),
      hideNotice: vi.fn(),
      installEasyLive2DInteractivity: vi.fn(),
      setupModelInteractivity: vi.fn(),
      applyModelTransform: vi.fn(),
      reportState: vi.fn(),
      syncMouseCaptureFromLastPoint: vi.fn(),
      markActivity: vi.fn(),
    })

    adapter.setCompanionIdleProfile({
      supportStyle: 'cheerful',
      mood: 'warm',
      relationshipTrend: 'rising',
      energy: 0.95,
      affinity: 0.9,
      trust: 0.85,
      intimacy: 0.88,
    })
    await adapter.loadModel({ modelPath: './live2d/llm-live2d/yumi/yumi.model3.json' })

    const firstSnapshot = adapter.getBehaviorDebugSnapshot()
    expect(firstSnapshot?.companionIdleProfile.relationshipTrend).toBe('rising')
    expect(firstSnapshot?.effectiveProfile.swayAmplitude).toBeGreaterThan(1)

    await adapter.loadModel({ modelPath: './live2d/llm-live2d/yumi/yumi.model3.json' })
    const reloadedSnapshot = adapter.getBehaviorDebugSnapshot()

    expect(reloadedSnapshot?.companionIdleProfile).toMatchObject({
      supportStyle: 'cheerful',
      mood: 'warm',
      relationshipTrend: 'rising',
    })
    expect(reloadedSnapshot?.effectiveProfile.swayAmplitude).toBe(firstSnapshot?.effectiveProfile.swayAmplitude)
  }, 15_000)

  it('forwards attention targets to the recreated behavior controller', async () => {
    const viewport = new FakeContainer()
    let currentModel: Live2DSprite | null = null
    const adapter = new Live2DRuntimeAdapter({
      app: { ticker: new FakeTicker() } as unknown as PIXI.Application,
      getModel: () => currentModel,
      setModel: (model) => {
        currentModel = model
      },
      getViewport: () => viewport as unknown as PIXI.Container,
      ensureViewport: () => viewport as unknown as PIXI.Container,
      config: {
        modelId: 'llm-live2d/yumi',
        modelType: 'live2d',
        modelPath: './live2d/llm-live2d/yumi/yumi.model3.json',
        scale: 0.28,
        positionX: null,
        positionY: null,
        placement: 'bottom-right',
      },
      showNotice: vi.fn(),
      hideNotice: vi.fn(),
      installEasyLive2DInteractivity: vi.fn(),
      setupModelInteractivity: vi.fn(),
      applyModelTransform: vi.fn(),
      reportState: vi.fn(),
      syncMouseCaptureFromLastPoint: vi.fn(),
      markActivity: vi.fn(),
    })

    await adapter.loadModel({ modelPath: './live2d/llm-live2d/yumi/yumi.model3.json' })
    adapter.setAttentionTarget({ x: 0.6, y: -0.25, strength: 0.7, durationMs: 600 })

    expect(adapter.getBehaviorDebugSnapshot()?.attention).toMatchObject({
      active: true,
      x: 0.6,
      y: -0.25,
      strength: 0.7,
    })
  })

  it('queues rapid motion requests through a short transition instead of hard-cutting immediately', async () => {
    vi.useFakeTimers()
    const viewport = new FakeContainer()
    let currentModel: Live2DSprite | null = null
    const adapter = new Live2DRuntimeAdapter({
      app: { ticker: new FakeTicker() } as unknown as PIXI.Application,
      getModel: () => currentModel,
      setModel: (model) => {
        currentModel = model
      },
      getViewport: () => viewport as unknown as PIXI.Container,
      ensureViewport: () => viewport as unknown as PIXI.Container,
      config: {
        modelId: 'llm-live2d/yumi',
        modelType: 'live2d',
        modelPath: './live2d/llm-live2d/yumi/yumi.model3.json',
        scale: 0.28,
        positionX: null,
        positionY: null,
        placement: 'bottom-right',
      },
      showNotice: vi.fn(),
      hideNotice: vi.fn(),
      installEasyLive2DInteractivity: vi.fn(),
      setupModelInteractivity: vi.fn(),
      applyModelTransform: vi.fn(),
      reportState: vi.fn(),
      syncMouseCaptureFromLastPoint: vi.fn(),
      markActivity: vi.fn(),
    })

    await adapter.loadModel({ modelPath: './live2d/llm-live2d/yumi/yumi.model3.json' })
    adapter.triggerMotion('Tap', 0)
    adapter.triggerMotion('Flick', 0)

    expect(fakeModel.startMotion).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(430)

    expect(fakeModel.startMotion).toHaveBeenCalledTimes(2)
    expect(fakeModel.startMotion).toHaveBeenLastCalledWith(expect.objectContaining({ group: 'Flick' }))
  })
})
