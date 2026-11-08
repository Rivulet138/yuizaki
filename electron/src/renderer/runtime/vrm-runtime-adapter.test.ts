import * as THREE from 'three'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DEFAULT_PET_CONTROL_STATE } from '../../shared/pet-control'
import { VrmRuntimeAdapter } from './vrm-runtime-adapter'

const loader = vi.hoisted(() => ({ loadAsync: vi.fn(), dispose: vi.fn() }))

vi.mock('three', async importOriginal => ({
  ...await importOriginal<typeof import('three')>(),
  WebGLRenderer: class {
    setSize = vi.fn()
    setPixelRatio = vi.fn()
    render = vi.fn()
    dispose = vi.fn()
  },
}))

vi.mock('three/examples/jsm/loaders/GLTFLoader.js', () => ({
  GLTFLoader: class {
    register = vi.fn()
    loadAsync = loader.loadAsync
  },
}))

vi.mock('@pixiv/three-vrm', () => ({
  VRMLoaderPlugin: class {},
  VRMUtils: { deepDispose: loader.dispose, rotateVRM0: vi.fn() },
}))

const deferred = <T,>() => {
  let resolve: (value: T) => void = () => { throw new Error('Promise not initialized') }
  const promise = new Promise<T>(complete => { resolve = complete })
  return { promise, resolve }
}

const modelAsset = () => ({
  userData: { vrm: { scene: new THREE.Group(), update: vi.fn() } },
  animations: [],
})

const createRuntime = (animationPaths: string[] = []) => {
  const host = {
    container: document.createElement('div'),
    config: {
      ...DEFAULT_PET_CONTROL_STATE,
      modelPath: 'avatar.vrm',
      animationPaths,
    },
    showNotice: vi.fn(),
    hideNotice: vi.fn(),
    reportState: vi.fn(),
    markActivity: vi.fn(),
  }
  return { runtime: new VrmRuntimeAdapter(host), host }
}

describe('VRM load cancellation', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    loader.loadAsync.mockReset()
    vi.stubGlobal('document', {
      createElement: () => ({ dataset: {}, style: {}, appendChild: vi.fn() }),
    })
    vi.stubGlobal('window', {
      innerWidth: 800, innerHeight: 600, devicePixelRatio: 1,
      requestAnimationFrame: vi.fn(() => 1), cancelAnimationFrame: vi.fn(),
    })
    vi.stubGlobal('navigator', { hardwareConcurrency: 8 })
  })

  afterEach(() => vi.unstubAllGlobals())

  it('disposes a cancelled model without publishing ready state or starting rendering', async () => {
    const asset = modelAsset()
    const pending = deferred<ReturnType<typeof modelAsset>>()
    loader.loadAsync.mockReturnValueOnce(pending.promise)
    const { runtime, host } = createRuntime()
    const loading = runtime.loadModel({})

    runtime.cancelPendingLoad()
    pending.resolve(asset)
    await loading

    expect(loader.dispose).toHaveBeenCalledExactlyOnceWith(asset.userData.vrm.scene)
    expect(runtime.getState().ready).toBe(false)
    expect(host.hideNotice).not.toHaveBeenCalled()
    expect(host.reportState).not.toHaveBeenCalled()
    expect(host.markActivity).not.toHaveBeenCalled()
    expect(window.requestAnimationFrame).not.toHaveBeenCalled()
    runtime.destroy()
  })

  it('invalidates a model awaiting external animation clips', async () => {
    const asset = modelAsset()
    const pending = deferred<{ animations: [] }>()
    loader.loadAsync.mockResolvedValueOnce(asset).mockReturnValueOnce(pending.promise)
    const { runtime, host } = createRuntime(['motion.vrma'])
    const loading = runtime.loadModel({})
    await vi.waitFor(() => expect(loader.loadAsync).toHaveBeenCalledWith('motion.vrma'))

    runtime.cancelPendingLoad()
    pending.resolve({ animations: [] })
    await loading

    expect(loader.dispose).toHaveBeenCalledExactlyOnceWith(asset.userData.vrm.scene)
    expect(runtime.getState().ready).toBe(false)
    expect(host.reportState).not.toHaveBeenCalled()
    runtime.destroy()
  })

  it('keeps the current model when a cancelled replacement resolves after the retry succeeds', async () => {
    const current = modelAsset()
    const stale = modelAsset()
    const replacement = modelAsset()
    const pending = deferred<ReturnType<typeof modelAsset>>()
    loader.loadAsync.mockResolvedValueOnce(current)
    const { runtime, host } = createRuntime()
    await runtime.loadModel({})
    host.reportState.mockClear()
    loader.loadAsync.mockReturnValueOnce(pending.promise)
    const loading = runtime.loadModel({ modelPath: 'stale.vrm' })

    runtime.cancelPendingLoad()
    expect(runtime.getState().ready).toBe(true)
    expect(loader.dispose).not.toHaveBeenCalled()
    loader.loadAsync.mockResolvedValueOnce(replacement)
    await runtime.loadModel({ modelPath: 'retry.vrm' })
    pending.resolve(stale)
    await loading

    expect(loader.dispose).toHaveBeenCalledWith(current.userData.vrm.scene)
    expect(loader.dispose).toHaveBeenCalledWith(stale.userData.vrm.scene)
    expect(loader.dispose).not.toHaveBeenCalledWith(replacement.userData.vrm.scene)
    expect(host.reportState).toHaveBeenCalledTimes(1)
    expect(runtime.getState().ready).toBe(true)
    runtime.destroy()
  })

  it('invalidates pending models on destroy', async () => {
    const asset = modelAsset()
    const pending = deferred<ReturnType<typeof modelAsset>>()
    loader.loadAsync.mockReturnValueOnce(pending.promise)
    const { runtime, host } = createRuntime()
    const loading = runtime.loadModel({})
    runtime.destroy()
    pending.resolve(asset)
    await loading

    expect(loader.dispose).toHaveBeenCalledExactlyOnceWith(asset.userData.vrm.scene)
    expect(runtime.getState().ready).toBe(false)
    expect(host.reportState).not.toHaveBeenCalled()
  })
})
