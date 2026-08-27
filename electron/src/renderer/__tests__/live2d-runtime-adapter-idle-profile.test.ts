import type { Live2DSprite } from 'easy-live2d'
import type * as PIXI from 'pixi.js'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Live2DCoreModel } from '../runtime/live2d-core-model'
import { createLive2DModel, destroyCurrentModel } from '../pet-model-runtime'

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

  it('resolves custom emotion IDs to their declared expression and motion targets', async () => {
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
        modelId: 'custom-model',
        modelType: 'live2d',
        modelPath: './custom.model3.json',
        modelManifest: {
          id: 'custom-model',
          name: 'Custom',
          summary: '',
          persona: { tone: '', traits: [], styleRules: [] },
          modelJson: 'custom.model3.json',
          modelTransform: { scale: 1, offsetX: 0, offsetY: 0 },
          transformDefaults: { scale: 1, offsetX: 0, offsetY: 0 },
          expressions: [{ id: 'smile', label: 'Smile', kind: 'emotion', prompt: '', binding: { mode: 'preset', params: {} } }],
          parameterControls: [],
          motions: { wave: { file: 'wave.motion3.json', group: 'Wave' } },
        },
        emotionPresets: [{
          id: 'celebrate-custom',
          label: 'Celebrate',
          expressions: ['smile'],
          motions: [{ group: 'Wave', index: 0, label: 'Wave' }],
        }],
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

    await adapter.loadModel({ modelPath: './custom.model3.json' })
    const result = adapter.executeAvatarAction({ type: 'affect', emotion: 'celebrate-custom' })

    expect(result.status).toBe('completed')
    expect(fakeModel.setExpression).toHaveBeenCalledWith({ expressionId: 'smile' })
    expect(fakeModel.startMotion).toHaveBeenCalledWith(expect.objectContaining({ group: 'Wave', no: 0 }))

    vi.clearAllMocks()
    const reducedResult = adapter.executeAvatarAction({
      type: 'affect',
      emotion: 'celebrate-custom',
      intensity: 0.35,
      motion: null,
    })
    expect(reducedResult.status).toBe('completed')
    expect(fakeModel.setExpression).toHaveBeenCalledWith({ expressionId: 'smile' })
    expect(fakeModel.startMotion).not.toHaveBeenCalled()
  })

  it('keeps the previous model when the replacement fails to load', async () => {
    const viewport = new FakeContainer()
    let currentModel: Live2DSprite | null = null
    const adapter = new Live2DRuntimeAdapter({
      app: { ticker: new FakeTicker() } as unknown as PIXI.Application,
      getModel: () => currentModel,
      setModel: (model) => { currentModel = model },
      getViewport: () => viewport as unknown as PIXI.Container,
      ensureViewport: () => viewport as unknown as PIXI.Container,
      config: {
        modelId: 'model', modelType: 'live2d', modelPath: './first.model3.json',
        scale: 0.28, positionX: null, positionY: null, placement: 'bottom-right',
      },
      showNotice: vi.fn(), hideNotice: vi.fn(), installEasyLive2DInteractivity: vi.fn(),
      setupModelInteractivity: vi.fn(), applyModelTransform: vi.fn(), reportState: vi.fn(),
      syncMouseCaptureFromLastPoint: vi.fn(), markActivity: vi.fn(),
    })

    await adapter.loadModel({ modelPath: './first.model3.json' })
    const previousModel = currentModel
    vi.mocked(createLive2DModel).mockImplementationOnce(() => { throw new Error('missing model') })

    await expect(adapter.loadModel({ modelPath: './missing.model3.json' })).rejects.toThrow('missing model')

    expect(currentModel).toBe(previousModel)
    expect(viewport.removeChild).not.toHaveBeenCalledWith(previousModel)
    expect(vi.mocked(destroyCurrentModel)).not.toHaveBeenCalledWith(expect.anything(), previousModel)
  })

  it('disposes a candidate whose ready promise rejects without touching the previous model', async () => {
    const viewport = new FakeContainer()
    let currentModel: Live2DSprite | null = null
    const adapter = new Live2DRuntimeAdapter({
      app: { ticker: new FakeTicker() } as unknown as PIXI.Application,
      getModel: () => currentModel,
      setModel: (model) => { currentModel = model },
      getViewport: () => viewport as unknown as PIXI.Container,
      ensureViewport: () => viewport as unknown as PIXI.Container,
      config: {
        modelId: 'model', modelType: 'live2d', modelPath: './first.model3.json',
        scale: 0.28, positionX: null, positionY: null, placement: 'bottom-right',
      },
      showNotice: vi.fn(), hideNotice: vi.fn(), installEasyLive2DInteractivity: vi.fn(),
      setupModelInteractivity: vi.fn(), applyModelTransform: vi.fn(), reportState: vi.fn(),
      syncMouseCaptureFromLastPoint: vi.fn(), markActivity: vi.fn(),
    })

    await adapter.loadModel({ modelPath: './first.model3.json' })
    const previousModel = currentModel
    const candidate = { ...fakeModel, ready: Promise.reject(new Error('invalid model')) } as unknown as Live2DSprite
    vi.mocked(createLive2DModel).mockReturnValueOnce(candidate)
    vi.mocked(destroyCurrentModel).mockClear()

    await expect(adapter.loadModel({ modelPath: './invalid.model3.json' })).rejects.toThrow('invalid model')

    expect(currentModel).toBe(previousModel)
    expect(vi.mocked(destroyCurrentModel)).toHaveBeenCalledWith(expect.anything(), candidate)
    expect(vi.mocked(destroyCurrentModel)).not.toHaveBeenCalledWith(expect.anything(), previousModel)
    expect(viewport.removeChild).not.toHaveBeenCalledWith(previousModel)
  })

  it('atomically swaps only after the replacement is created and disposes the old model', async () => {
    const viewport = new FakeContainer()
    let currentModel: Live2DSprite | null = null
    const adapter = new Live2DRuntimeAdapter({
      app: { ticker: new FakeTicker() } as unknown as PIXI.Application,
      getModel: () => currentModel,
      setModel: (model) => { currentModel = model },
      getViewport: () => viewport as unknown as PIXI.Container,
      ensureViewport: () => viewport as unknown as PIXI.Container,
      config: {
        modelId: 'model', modelType: 'live2d', modelPath: './first.model3.json',
        scale: 0.28, positionX: null, positionY: null, placement: 'bottom-right',
      },
      showNotice: vi.fn(), hideNotice: vi.fn(), installEasyLive2DInteractivity: vi.fn(),
      setupModelInteractivity: vi.fn(), applyModelTransform: vi.fn(), reportState: vi.fn(),
      syncMouseCaptureFromLastPoint: vi.fn(), markActivity: vi.fn(),
    })

    const firstModel = { ...fakeModel, anchor: { set: vi.fn() } } as unknown as Live2DSprite
    const secondModel = { ...fakeModel, anchor: { set: vi.fn() } } as unknown as Live2DSprite
    vi.mocked(createLive2DModel).mockImplementationOnce(() => firstModel).mockImplementationOnce(() => secondModel)
    vi.mocked(destroyCurrentModel).mockClear()

    await adapter.loadModel({ modelPath: './first.model3.json' })
    await adapter.loadModel({ modelPath: './second.model3.json' })

    expect(currentModel).toBe(secondModel)
    expect(viewport.removeChild).toHaveBeenCalledWith(firstModel)
    expect(vi.mocked(destroyCurrentModel)).toHaveBeenCalledWith(expect.anything(), firstModel)
  })
})
