import { afterEach, describe, expect, it, vi } from 'vitest'
import { VrmRuntimeAdapter } from '@/runtime/vrm-runtime-adapter'

const createAdapter = (): VrmRuntimeAdapter => new VrmRuntimeAdapter({
  container: document.createElement('div'),
  config: {
    modelId: 'vrm-render-policy',
    modelType: 'vrm',
    modelPath: 'test.vrm',
    animationPaths: [],
    scale: 0.4,
    positionX: null,
    positionY: null,
    placement: 'bottom-right',
    lipSyncProfile: {
      gain: 1,
      noiseGate: 0,
      maxOpen: 1,
      attack: 1,
      release: 1,
    },
  },
  showNotice: vi.fn(),
  hideNotice: vi.fn(),
  reportState: vi.fn(),
  markActivity: vi.fn(),
})

describe('VRM render policy', () => {
  afterEach(() => vi.restoreAllMocks())

  it('renders at the active or idle budget and invalidates paused callbacks', () => {
    const callbacks: FrameRequestCallback[] = []
    const requestFrame = vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => {
      callbacks.push(callback)
      return callbacks.length
    })
    const cancelFrame = vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => undefined)
    vi.spyOn(performance, 'now').mockReturnValue(0)

    const render = vi.fn()
    const adapter = createAdapter()
    Object.assign(adapter as object, {
      renderer: { render },
      scene: {},
      camera: {},
      timer: { reset: vi.fn(), update: vi.fn(), getDelta: vi.fn(() => 1 / 60) },
    })

    adapter.setRenderPolicy({ targetFps: 60, paused: false })
    expect(render).toHaveBeenCalledOnce()

    callbacks.shift()?.(100)
    expect(render).toHaveBeenCalledTimes(2)
    callbacks.shift()?.(108)
    expect(render).toHaveBeenCalledTimes(2)
    callbacks.shift()?.(117)
    expect(render).toHaveBeenCalledTimes(3)

    adapter.setRenderPolicy({ targetFps: 30, paused: false })
    callbacks.shift()?.(140)
    expect(render).toHaveBeenCalledTimes(3)
    callbacks.shift()?.(151)
    expect(render).toHaveBeenCalledTimes(4)

    const staleCallback = callbacks.shift()
    adapter.setRenderPolicy({ targetFps: 30, paused: true })
    const queuedAtPause = callbacks.length
    staleCallback?.(200)
    expect(callbacks).toHaveLength(queuedAtPause)
    expect(cancelFrame).toHaveBeenCalled()

    adapter.setRenderPolicy({ targetFps: 60, paused: false })
    expect(requestFrame).toHaveBeenCalled()
    expect(render).toHaveBeenCalledTimes(5)
  })
})
