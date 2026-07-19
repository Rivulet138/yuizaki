import { describe, expect, it, vi } from 'vitest'
import { Live2DLipSyncController } from '@/runtime/live2d-lipsync-controller'
import { VrmRuntimeAdapter } from '@/runtime/vrm-runtime-adapter'

describe('realtime pet lip sync', () => {
  it('applies per-model calibration to all declared Live2D mouth parameters', () => {
    let ticker: (() => void) | null = null
    const app = {
      ticker: {
        add: vi.fn((callback: () => void) => {
          ticker = callback
        }),
        remove: vi.fn(() => {
          ticker = null
        }),
      },
    }
    const values = new Map<string, number>()
    const coreModel = {
      getParameterValueById: vi.fn((id: string) => values.get(id) ?? 0),
      setParameterValueById: vi.fn((id: string, value: number) => values.set(id, value)),
      addParameterValueById: vi.fn(),
    }
    const controller = new Live2DLipSyncController(
      app as never,
      () => coreModel,
    )

    controller.configure({
      gain: 2,
      noiseGate: 0.1,
      maxOpen: 0.6,
      attack: 0.5,
      release: 0.25,
    }, ['ParamMouthOpenY', 'ParamMouthOpenAlt'])
    controller.setExternalLevel(0.8)
    ticker?.()
    expect(values.get('ParamMouthOpenY')).toBeCloseTo(0.3)
    expect(values.get('ParamMouthOpenAlt')).toBeCloseTo(0.3)

    controller.stopExternal()
    expect(values.get('ParamMouthOpenY')).toBe(0)
    expect(values.get('ParamMouthOpenAlt')).toBe(0)
    expect(app.ticker.remove).toHaveBeenCalled()
  })

  it('maps bounded realtime levels to the VRM aa expression', () => {
    const expressionManager = {
      getExpression: vi.fn(() => ({})),
      getValue: vi.fn(() => 0),
      setValue: vi.fn(),
    }
    const adapter = new VrmRuntimeAdapter({
      container: document.createElement('div'),
      config: {
        modelId: 'vrm-test',
        modelType: 'vrm',
        modelPath: 'test.vrm',
        scale: 0.4,
        positionX: null,
        positionY: null,
        placement: 'bottom-right',
        lipSyncProfile: {
          gain: 2,
          noiseGate: 0.1,
          maxOpen: 0.8,
          attack: 0.5,
          release: 0.25,
        },
      },
      showNotice: vi.fn(),
      hideNotice: vi.fn(),
      reportState: vi.fn(),
      markActivity: vi.fn(),
    })
    Object.assign(adapter as object, {
      vrm: { expressionManager },
    })

    adapter.setLipSyncLevel(1.8, true)
    adapter.setLipSyncLevel(0.5, false)

    expect(expressionManager.setValue).toHaveBeenNthCalledWith(1, 'aa', 0.4)
    expect(expressionManager.setValue).toHaveBeenNthCalledWith(2, 'aa', 0)
  })

  it('combines PCM amplitude with normalized VRM vowel visemes', () => {
    const expressionManager = {
      getExpression: vi.fn(() => ({})),
      getValue: vi.fn(() => 0),
      setValue: vi.fn(),
    }
    const adapter = new VrmRuntimeAdapter({
      container: document.createElement('div'),
      config: {
        modelId: 'vrm-viseme',
        modelType: 'vrm',
        modelPath: 'test.vrm',
        scale: 0.4,
        positionX: null,
        positionY: null,
        placement: 'bottom-right',
        lipSyncProfile: {
          gain: 2,
          noiseGate: 0,
          maxOpen: 0.8,
          attack: 0.5,
          release: 0.25,
        },
      },
      showNotice: vi.fn(),
      hideNotice: vi.fn(),
      reportState: vi.fn(),
      markActivity: vi.fn(),
    })
    Object.assign(adapter as object, {
      vrm: { expressionManager },
    })

    adapter.setLipSyncLevel(0.5, true)
    adapter.setLipSyncViseme('ih', 0.75, true)
    adapter.setLipSyncViseme('sil', 0, true)

    expect(expressionManager.setValue).toHaveBeenNthCalledWith(1, 'aa', 0.4)
    expect(expressionManager.setValue).toHaveBeenNthCalledWith(2, 'aa', 0)
    expect(expressionManager.setValue.mock.calls[2]?.[0]).toBe('ih')
    expect(expressionManager.setValue.mock.calls[2]?.[1]).toBeCloseTo(0.3)
    expect(expressionManager.setValue).toHaveBeenNthCalledWith(4, 'ih', 0)
  })

  it('uses an available vowel even when the VRM omits the aa preset', () => {
    const expressionManager = {
      getExpression: vi.fn((name: string) => name === 'ih' ? {} : null),
      getValue: vi.fn(() => 0),
      setValue: vi.fn(),
    }
    const adapter = new VrmRuntimeAdapter({
      container: document.createElement('div'),
      config: {
        modelId: 'vrm-no-aa',
        modelType: 'vrm',
        modelPath: 'test.vrm',
        scale: 0.4,
        positionX: null,
        positionY: null,
        placement: 'bottom-right',
        lipSyncProfile: {
          gain: 2,
          noiseGate: 0,
          maxOpen: 0.8,
          attack: 0.5,
          release: 0.25,
        },
      },
      showNotice: vi.fn(),
      hideNotice: vi.fn(),
      reportState: vi.fn(),
      markActivity: vi.fn(),
    })
    Object.assign(adapter as object, {
      vrm: { expressionManager },
    })

    adapter.setLipSyncLevel(0.5, true)
    adapter.setLipSyncViseme('ih', 0.75, true)

    expect(expressionManager.setValue).toHaveBeenCalledOnce()
    expect(expressionManager.setValue.mock.calls[0]?.[0]).toBe('ih')
    expect(expressionManager.setValue.mock.calls[0]?.[1]).toBeCloseTo(0.3)
  })
})
