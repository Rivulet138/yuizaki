import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PetRenderer } from './pet-renderer'

const mocks = vi.hoisted(() => ({ createApp: vi.fn() }))
vi.mock('pixi.js/unsafe-eval', () => ({}))
vi.mock('pixi.js', () => ({}))
vi.mock('easy-live2d', () => ({ Config: {}, Priority: {} }))
vi.mock('@/i18n', () => ({ t: (key: string) => key }))
vi.mock('./runtime/live2d-runtime-adapter', () => ({ Live2DRuntimeAdapter: class {} }))
vi.mock('./pet-renderer-core', () => ({
  createPixiApp: () => mocks.createApp(),
  getPixiCanvas: () => ({ style: {} }),
  resolveRendererAsset: (path: string) => path,
  getReadableError: String,
}))

const createStage = () => {
  const pet = new PetRenderer('stage')
  // Keep the real initialization, visibility, loading and global input lifecycle;
  // replace only DOM presentation and unrelated IPC/state publication.
  for (const method of ['setupModelInteractivity', 'setupAdjustmentControls', 'setupIPCListeners', 'showNotice', 'reportRendererMetrics', 'publishAvatarCapabilities', 'reportState']) {
    Reflect.set(pet, method, vi.fn())
  }
  const app = {
    ticker: { start: vi.fn(), stop: vi.fn(), maxFPS: 60, minFPS: 30 },
    stage: {},
    destroy: vi.fn(),
  }
  mocks.createApp.mockResolvedValue(app)
  const runtime = {
    loadModel: vi.fn(async () => undefined),
    setRenderPolicy: vi.fn(),
    setCompanionIdleProfile: vi.fn(),
    destroy: vi.fn(),
  }
  Reflect.set(pet, 'vrmRuntime', runtime)
  Reflect.get(pet, 'config').modelType = 'vrm'
  return { pet, app, runtime }
}

const deferred = () => {
  let resolve!: () => void
  const promise = new Promise<void>(complete => { resolve = complete })
  return { promise, resolve }
}

describe('embedded pet rendering visibility', () => {
  let pet: PetRenderer | undefined
  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
    vi.stubGlobal('window', Object.assign(new EventTarget(), {
      setTimeout, clearTimeout, innerWidth: 800, innerHeight: 600, devicePixelRatio: 1,
    }))
    vi.stubGlobal('document', Object.assign(new EventTarget(), {
      hidden: false, getElementById: () => ({ appendChild: vi.fn() }),
    }))
    vi.stubGlobal('navigator', { hardwareConcurrency: 8 })
  })
  afterEach(() => {
    pet?.destroy()
    pet = undefined
    vi.useRealTimers()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('stops ticker, VRM and global input while cached, and resumes only when visible', async () => {
    const stage = createStage()
    pet = stage.pet
    await pet.init()
    await pet.loadModel('/avatar.vrm')
    const removeListener = vi.spyOn(window, 'removeEventListener')
    pet.setEmbeddedActive(false)
    expect(stage.app.ticker.stop).toHaveBeenCalled()
    expect(stage.runtime.setRenderPolicy).toHaveBeenLastCalledWith({ targetFps: 60, paused: true })
    expect(removeListener.mock.calls.map(([event]) => event)).toEqual(expect.arrayContaining(['keydown', 'mousedown', 'mousemove', 'wheel', 'contextmenu']))
    expect(vi.getTimerCount()).toBe(0)
    expect(stage.runtime.destroy).not.toHaveBeenCalled()
    stage.app.ticker.start.mockClear()
    Reflect.set(document, 'hidden', true)
    pet.setEmbeddedActive(true)
    expect(stage.app.ticker.start).not.toHaveBeenCalled()
    expect(stage.runtime.setRenderPolicy).toHaveBeenLastCalledWith({ targetFps: 60, paused: true })
    Reflect.set(document, 'hidden', false)
    document.dispatchEvent(new Event('visibilitychange'))
    expect(stage.app.ticker.start).toHaveBeenCalledTimes(1)
    expect(stage.runtime.setRenderPolicy).toHaveBeenLastCalledWith({ targetFps: 60, paused: false })
    expect(stage.runtime.loadModel).toHaveBeenCalledTimes(1)
  })

  it('does not restart ticker or VRM when a pending load settles while inactive', async () => {
    const stage = createStage()
    pet = stage.pet
    await pet.init()
    const pending = deferred()
    stage.runtime.loadModel.mockImplementationOnce(() => pending.promise)
    const loading = pet.loadModel('/avatar.vrm')
    pet.setEmbeddedActive(false)
    stage.app.ticker.start.mockClear()
    pending.resolve()
    await loading
    expect(stage.app.ticker.start).not.toHaveBeenCalled()
    expect(stage.runtime.setRenderPolicy.mock.calls.every(([policy]) => policy.paused)).toBe(true)
    expect(vi.getTimerCount()).toBe(0)
    await pet.loadModel('/another.vrm')
    expect(stage.runtime.loadModel).toHaveBeenCalledTimes(1)
  })

  it('destroys a late initialized app without starting its ticker after disposal', async () => {
    const stage = createStage()
    pet = stage.pet
    let release!: (app: typeof stage.app) => void
    mocks.createApp.mockImplementationOnce(() => new Promise(resolve => { release = resolve }))
    const initializing = pet.init()
    pet.setEmbeddedActive(false)
    pet.destroy()
    release(stage.app)
    await initializing
    expect(stage.app.destroy).toHaveBeenCalledWith(true)
    expect(stage.app.ticker.start).not.toHaveBeenCalled()
  })

  it('does not restart rendering when a destroyed candidate load resolves', async () => {
    const stage = createStage()
    pet = stage.pet
    await pet.init()
    const pending = deferred()
    stage.runtime.loadModel.mockImplementationOnce(() => pending.promise)
    const loading = pet.loadModel('/avatar.vrm')
    pet.destroy()
    stage.app.ticker.start.mockClear()
    stage.runtime.setRenderPolicy.mockClear()
    pending.resolve()
    await loading
    expect(stage.app.ticker.start).not.toHaveBeenCalled()
    expect(stage.runtime.setRenderPolicy).not.toHaveBeenCalled()
    expect(stage.runtime.destroy).toHaveBeenCalledTimes(1)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('keeps standalone windows active by default and follows document visibility', async () => {
    const stage = createStage()
    pet = stage.pet
    await pet.init()
    await pet.loadModel('/avatar.vrm')
    expect(stage.app.ticker.start).toHaveBeenCalled()
    expect(stage.runtime.setRenderPolicy).toHaveBeenLastCalledWith({ targetFps: 60, paused: false })
    Reflect.set(document, 'hidden', true)
    document.dispatchEvent(new Event('visibilitychange'))
    expect(stage.runtime.setRenderPolicy).toHaveBeenLastCalledWith({ targetFps: 60, paused: true })
    Reflect.set(document, 'hidden', false)
    document.dispatchEvent(new Event('visibilitychange'))
    expect(stage.runtime.setRenderPolicy).toHaveBeenLastCalledWith({ targetFps: 60, paused: false })
  })
})
