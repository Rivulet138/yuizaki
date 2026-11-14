import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createRenderer, getCurrentInstance, h, KeepAlive, nextTick, ref, ssrContextKey, type Component, type ComponentInternalInstance } from 'vue'
import BrowserPetStage from './BrowserPetStage.vue'
import BrowserStageView from './BrowserStageView.vue'

const mocks = vi.hoisted(() => ({
  modelId: 'a', modelType: 'live2d' as 'live2d' | 'vrm', init: vi.fn<() => Promise<void>>(), load: vi.fn<(path: string) => Promise<void>>(),
  core: vi.fn<() => Promise<void>>(),
  instances: [] as Array<{ setEmbeddedActive: ReturnType<typeof vi.fn>; resizeTo: ReturnType<typeof vi.fn>; fitEmbeddedModelToViewport: ReturnType<typeof vi.fn>; applyBrowserConfig: ReturnType<typeof vi.fn>; destroy: ReturnType<typeof vi.fn>; startLipSync: ReturnType<typeof vi.fn>; stopLipSync: ReturnType<typeof vi.fn>; path?: string }>,
  catalog: vi.fn(), resolveUrl: vi.fn<(url: string) => Promise<string>>(),
}))
vi.mock('@/pet-renderer-core', () => ({ ensureCubismCore: () => mocks.core() }))
vi.mock('@/pet-renderer', () => ({ PetRenderer: class {
  setEmbeddedActive = vi.fn()
  destroy = vi.fn()
  startLipSync = vi.fn()
  stopLipSync = vi.fn()
  path?: string
  constructor() { mocks.instances.push(this) }
  init = () => mocks.init()
  resizeTo = vi.fn()
  fitEmbeddedModelToViewport = vi.fn(() => 1)
  applyBrowserConfig = vi.fn(async (patch: { modelPath?: string }) => {
    if (patch.modelPath) { this.path = patch.modelPath; await mocks.load(patch.modelPath) }
  })
} }))
vi.mock('@/utils/petControl', () => ({ petControl: {
  getState: async () => ({ modelId: mocks.modelId }),
  getCatalog: () => mocks.catalog(),
} }))
vi.mock('@/i18n', () => ({ t: (key: string) => key, useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('@/stores/chatStore', () => ({ useChatStore: () => ({ state: {} }) }))
vi.mock('@/net/socketClient', () => ({ getSocketClient: () => ({ connected: { value: false } }) }))
vi.mock('./AppSidebar.vue', () => ({ default: { render: () => null } }))
vi.mock('element-plus', () => ({ ElIcon: {} }))
vi.mock('element-plus/es/components/icon/style/css', () => ({}))
vi.mock('@/api/clients/http-client', () => ({ resolveBackendUrl: (url: string) => mocks.resolveUrl(url) }))

class Element {
  children: Element[] = []
  parentNode: Element | null = null
  style: Record<string, unknown> = {}
  props: Record<string, unknown> = {}
  id = ''
  text = ''
  constructor(readonly tag = 'div') {}
  appendChild(child: Element) { this.insertBefore(child, null) }
  insertBefore(child: Element, anchor: Element | null) {
    child.remove()
    child.parentNode = this
    const index = anchor ? this.children.indexOf(anchor) : -1
    if (index < 0) this.children.push(child)
    else this.children.splice(index, 0, child)
  }
  remove() {
    if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(child => child !== this)
    this.parentNode = null
  }
  clientWidth = 1000
  getBoundingClientRect() { return { width: 400, height: 600 } }
}
const renderer = createRenderer<Element, Element>({
  createElement: tag => new Element(tag),
  createText: text => Object.assign(new Element('text'), { text }),
  createComment: text => Object.assign(new Element('comment'), { text }),
  setText: (node, text) => { node.text = text },
  setElementText: (node, text) => { node.text = text },
  insert: (node, parent, anchor = null) => parent.insertBefore(node, anchor),
  remove: node => node.remove(),
  parentNode: node => node.parentNode,
  nextSibling: node => node.parentNode?.children[node.parentNode.children.indexOf(node) + 1] || null,
  patchProp: (node, key, _previous, value) => { node.props[key] = value },
})
const flush = async () => {
  await vi.dynamicImportSettled()
  for (let i = 0; i < 12; i += 1) await Promise.resolve()
  await nextTick()
}

describe('browser model replacement lifecycle', () => {
  let app: ReturnType<typeof renderer.createApp> | undefined
  let visible = ref(true)
  let stageInstance: ComponentInternalInstance
  let resizeCallback: ResizeObserverCallback
  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
    mocks.instances.length = 0
    mocks.modelId = 'a'
    mocks.modelType = 'live2d'
    visible = ref(true)
    mocks.core.mockResolvedValue(undefined)
    mocks.init.mockResolvedValue(undefined)
    mocks.load.mockResolvedValue(undefined)
    mocks.catalog.mockImplementation(async () => ({ activeModelId: mocks.modelId, models: ['a', 'b', 'c'].map(id => ({ id, type: mocks.modelType, assetPath: `/${id}.${mocks.modelType === 'vrm' ? 'vrm' : 'json'}` })) }))
    mocks.resolveUrl.mockImplementation(async url => url)
    vi.stubGlobal('document', Object.assign(new EventTarget(), { hidden: false, createElement: (tag: string) => new Element(tag) }))
    vi.stubGlobal('window', Object.assign(new EventTarget(), { setTimeout, clearTimeout }))
    vi.stubGlobal('CustomEvent', class<T> extends Event {
      detail: T | undefined
      constructor(type: string, options?: CustomEventInit<T>) { super(type); this.detail = options?.detail }
    })
    vi.stubGlobal('ResizeObserver', class {
      constructor(callback: ResizeObserverCallback) { resizeCallback = callback }
      observe() {}
      disconnect() {}
    })
    vi.spyOn(console, 'warn').mockImplementation(() => undefined)
  })
  afterEach(() => {
    app?.unmount()
    vi.useRealTimers()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })
  const mount = async (component: Component = BrowserPetStage) => {
    // Vitest compiles SFCs for SSR; use the real setup with a host-only mount.
    const hosted = { ...component, render() {
      stageInstance = getCurrentInstance()!
      return h('div', { ref: (element: unknown) => {
        Reflect.set(Reflect.get(stageInstance, 'setupState'), component === BrowserStageView ? 'mainEl' : 'mountEl', element)
      } })
    } }
    app = renderer.createApp({ render: () => h(KeepAlive, { max: 1 }, {
      default: () => visible.value ? h(hosted) : null,
    }) })
    app.provide(ssrContextKey, { modules: new Set() })
    app.mount(new Element('root'))
    await flush()
  }
  const setVisible = async (value: boolean) => {
    visible.value = value
    await nextTick()
    await flush()
  }

  const setDocumentHidden = async (hidden: boolean) => {
    Object.assign(document, { hidden })
    document.dispatchEvent(new Event('visibilitychange'))
    await flush()
  }

  it.each(['live2d', 'vrm'] as const)('defers hidden initial %s activation until the document becomes visible', async (type) => {
    mocks.modelType = type
    await setDocumentHidden(true)
    await mount()
    await vi.advanceTimersByTimeAsync(10_000)
    expect(mocks.catalog).not.toHaveBeenCalled()
    expect(mocks.core).not.toHaveBeenCalled()
    expect(mocks.init).not.toHaveBeenCalled()
    expect(vi.getTimerCount()).toBe(0)
    await setDocumentHidden(false)
    await setDocumentHidden(false)
    expect(mocks.catalog).toHaveBeenCalledTimes(1)
    expect(mocks.init).toHaveBeenCalledTimes(1)
    expect(mocks.instances[0]!.path).toBe(type === 'vrm' ? '/a.vrm' : '/a.json')
  })

  it.each(['live2d', 'vrm'] as const)('pauses active %s catalog polling while hidden and resumes one chain with the old model', async (type) => {
    mocks.modelType = type
    await mount()
    const working = mocks.instances[0]!
    await setDocumentHidden(true)
    await vi.advanceTimersByTimeAsync(10_000)
    expect(mocks.catalog).toHaveBeenCalledTimes(1)
    expect(vi.getTimerCount()).toBe(0)
    expect(working.destroy).not.toHaveBeenCalled()
    await setDocumentHidden(false)
    await setDocumentHidden(false)
    expect(mocks.catalog).toHaveBeenCalledTimes(2)
    expect(mocks.init).toHaveBeenCalledTimes(1)
    expect(mocks.load).toHaveBeenCalledTimes(1)
    expect(working.destroy).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(2500)
    await flush()
    expect(mocks.catalog).toHaveBeenCalledTimes(3)
  })

  it.each(['visibility-first', 'activation-first'])('deduplicates document visibility and KeepAlive restoration: %s', async (order) => {
    await mount()
    await setDocumentHidden(true)
    await setVisible(false)
    if (order === 'visibility-first') {
      await setDocumentHidden(false)
      expect(mocks.catalog).toHaveBeenCalledTimes(1)
      await setVisible(true)
    } else {
      await setVisible(true)
      expect(mocks.catalog).toHaveBeenCalledTimes(1)
      await setDocumentHidden(false)
    }
    await setDocumentHidden(false)
    expect(mocks.catalog).toHaveBeenCalledTimes(2)
    expect(mocks.init).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(2500)
    await flush()
    expect(mocks.catalog).toHaveBeenCalledTimes(3)
  })

  it.each(['hidden', 'visible'] as const)('discards an old catalog success arriving while %s', async (arrival) => {
    await mount()
    const working = mocks.instances[0]!
    let release!: (catalog: unknown) => void
    mocks.modelId = 'b'
    mocks.catalog.mockImplementationOnce(() => new Promise(resolve => { release = resolve }))
    await vi.advanceTimersByTimeAsync(2500)
    await setDocumentHidden(true)
    mocks.modelId = 'a'
    if (arrival === 'visible') await setDocumentHidden(false)
    release({ models: [{ id: 'b', type: 'live2d', assetPath: '/b.json' }] })
    await flush()
    expect(mocks.instances).toHaveLength(1)
    expect(working.destroy).not.toHaveBeenCalled()
    if (arrival === 'hidden') {
      expect(vi.getTimerCount()).toBe(0)
      await setDocumentHidden(false)
    }
    await vi.advanceTimersByTimeAsync(2500)
    await flush()
    expect(mocks.catalog).toHaveBeenCalledTimes(4)
    expect(mocks.instances).toHaveLength(1)
  })

  it.each(['hidden', 'visible'] as const)('ignores an old initial catalog failure arriving while %s', async (arrival) => {
    let reject!: (error: Error) => void
    mocks.catalog.mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail }))
    await mount()
    await setDocumentHidden(true)
    if (arrival === 'visible') await setDocumentHidden(false)
    reject(new Error('old catalog offline'))
    await flush()
    expect(console.warn).not.toHaveBeenCalled()
    if (arrival === 'hidden') {
      expect(mocks.init).not.toHaveBeenCalled()
      expect(vi.getTimerCount()).toBe(0)
      await setDocumentHidden(false)
    }
    expect(mocks.instances).toHaveLength(1)
    expect(mocks.instances[0]!.path).toBe('/a.json')
    await vi.advanceTimersByTimeAsync(2500)
    await flush()
    expect(mocks.catalog).toHaveBeenCalledTimes(3)
  })

  it('does not initialize WebGL when Cubism resolves while the active document is hidden', async () => {
    let release!: () => void
    mocks.core.mockImplementationOnce(() => new Promise<void>(resolve => { release = resolve }))
    await mount()
    await setDocumentHidden(true)
    release()
    await flush()
    expect(mocks.init).not.toHaveBeenCalled()
    expect(vi.getTimerCount()).toBe(0)
    await setDocumentHidden(false)
    expect(mocks.init).toHaveBeenCalledTimes(1)
    expect(mocks.instances[0]!.path).toBe('/a.json')
  })

  it('releases a hidden pending renderer and ignores its late WebGL initialization', async () => {
    let release!: () => void
    mocks.init.mockImplementationOnce(() => new Promise<void>(resolve => { release = resolve }))
    await mount()
    const stale = mocks.instances[0]!
    await setDocumentHidden(true)
    expect(stale.destroy).toHaveBeenCalled()
    release()
    await flush()
    expect(mocks.load).not.toHaveBeenCalled()
    expect(vi.getTimerCount()).toBe(0)
    await setDocumentHidden(false)
    expect(mocks.instances).toHaveLength(2)
    expect(mocks.instances[1]!.path).toBe('/a.json')
  })

  it('preserves the working model and rejects a hidden replacement after a newer replacement succeeds', async () => {
    await mount()
    const working = mocks.instances[0]!
    let release!: () => void
    mocks.modelId = 'b'
    mocks.load.mockImplementationOnce(() => new Promise<void>(resolve => { release = resolve }))
    await vi.advanceTimersByTimeAsync(2500)
    await flush()
    const stale = mocks.instances[1]!
    await setDocumentHidden(true)
    expect(stale.destroy).toHaveBeenCalled()
    expect(working.destroy).not.toHaveBeenCalled()
    mocks.modelId = 'c'
    await setDocumentHidden(false)
    const latest = mocks.instances[2]!
    expect(latest.path).toBe('/c.json')
    expect(working.destroy).toHaveBeenCalled()
    release()
    await flush()
    expect(stale.applyBrowserConfig).toHaveBeenCalledTimes(1)
    expect(latest.destroy).not.toHaveBeenCalled()
    expect(latest.setEmbeddedActive).toHaveBeenLastCalledWith(true)
  })

  it('removes the document visibility listener and releases the cached model on hidden unmount', async () => {
    const removeListener = vi.spyOn(document, 'removeEventListener')
    await mount()
    const working = mocks.instances[0]!
    await setDocumentHidden(true)
    app!.unmount()
    app = undefined
    expect(removeListener).toHaveBeenCalledWith('visibilitychange', expect.any(Function))
    expect(working.destroy).toHaveBeenCalled()
    await setDocumentHidden(false)
    await vi.advanceTimersByTimeAsync(10_000)
    expect(mocks.catalog).toHaveBeenCalledTimes(1)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('retries the same URL and preserves the working model on replacement failure', async () => {
    mocks.load.mockRejectedValueOnce(new Error('503'))
    await mount()
    expect(mocks.instances[0]?.destroy).toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(2500)
    await flush()
    expect(mocks.load.mock.calls.map(([path]) => path)).toEqual(['/a.json', '/a.json'])
    const working = mocks.instances[1]!
    mocks.modelId = 'b'
    mocks.load.mockRejectedValueOnce(new Error('503'))
    await vi.advanceTimersByTimeAsync(2500)
    await flush()
    expect(working.destroy).not.toHaveBeenCalled()
    expect(mocks.instances[2]?.destroy).toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(2500)
    await flush()
    expect(mocks.instances.at(-1)?.path).toBe('/b.json')
    expect(working.destroy).toHaveBeenCalled()
    expect(mocks.instances.at(-1)?.destroy).not.toHaveBeenCalled()
  })

  it('discards a slow superseded model when a newer selection succeeds', async () => {
    await mount()
    let release!: () => void
    mocks.load.mockImplementationOnce(() => new Promise<void>(resolve => { release = resolve }))
    mocks.modelId = 'b'
    await vi.advanceTimersByTimeAsync(2500)
    await flush()
    const stale = mocks.instances.at(-1)!
    mocks.modelId = 'c'
    await vi.advanceTimersByTimeAsync(2500)
    await flush()
    const latest = mocks.instances.at(-1)!
    expect(latest.path).toBe('/c.json')
    expect(stale.destroy).toHaveBeenCalled()
    release()
    await flush()
    expect(latest.destroy).not.toHaveBeenCalled()
  })

  it('destroys an unmounted candidate and never starts its delayed model load', async () => {
    let release!: () => void
    mocks.init.mockImplementationOnce(() => new Promise<void>(resolve => { release = resolve }))
    await mount()
    const candidate = mocks.instances[0]!
    app!.unmount()
    app = undefined
    expect(candidate.destroy).toHaveBeenCalled()
    release()
    await flush()
    expect(mocks.load).not.toHaveBeenCalled()
    expect(vi.getTimerCount()).toBe(0)
  })
  it('keeps a pending selected model through a transient catalog error', async () => {
    let release!: () => void
    mocks.load.mockImplementationOnce(() => new Promise<void>(resolve => { release = resolve }))
    await mount()
    const candidate = mocks.instances[0]!
    mocks.catalog.mockRejectedValueOnce(new Error('catalog offline'))
    await vi.advanceTimersByTimeAsync(2500)
    await flush()
    expect(candidate.destroy).not.toHaveBeenCalled()
    expect(mocks.instances).toHaveLength(1)
    release()
    await flush()
    expect(candidate.path).toBe('/a.json')
    expect(candidate.destroy).not.toHaveBeenCalled()
  })

  it('does not apply a delayed audio URL to a replacement or unmounted model', async () => {
    await mount()
    let release!: (url: string) => void
    mocks.resolveUrl.mockImplementationOnce(() => new Promise<string>(resolve => { release = resolve }))
    window.dispatchEvent(new CustomEvent('pet:tts-play-url', { detail: { audio_url: '/old.wav', generationId: 'old' } }))
    const oldModel = mocks.instances[0]!
    mocks.modelId = 'b'
    await vi.advanceTimersByTimeAsync(2500)
    await flush()
    const replacement = mocks.instances.at(-1)!
    release('/old.wav')
    await flush()
    expect(oldModel.startLipSync).not.toHaveBeenCalled()
    expect(replacement.startLipSync).not.toHaveBeenCalled()
    mocks.resolveUrl.mockImplementationOnce(() => new Promise<string>(resolve => { release = resolve }))
    window.dispatchEvent(new CustomEvent('pet:tts-play-url', { detail: { audio_url: '/new.wav', generationId: 'new' } }))
    app!.unmount()
    app = undefined
    release('/new.wav')
    await flush()
    expect(replacement.startLipSync).not.toHaveBeenCalled()
    expect(replacement.destroy).toHaveBeenCalled()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('ignores stale audio endings and ends the active PCM generation', async () => {
    await mount()
    const model = mocks.instances[0]!
    window.dispatchEvent(new CustomEvent('pet:audio-started', { detail: { generationId: 'pcm-new' } }))
    window.dispatchEvent(new CustomEvent('pet:audio-ended', { detail: { generationId: 'url-old' } }))
    expect(model.stopLipSync).not.toHaveBeenCalled()
    window.dispatchEvent(new CustomEvent('pet:audio-ended', { detail: { generationId: 'pcm-new' } }))
    expect(model.stopLipSync).toHaveBeenCalledTimes(1)
  })

  it.each(['live2d', 'vrm'] as const)('pauses cached %s models, polling, fit and input, then reuses the model on activation', async (type) => {
    mocks.modelType = type
    await mount()
    const model = mocks.instances[0]!
    expect(mocks.init).toHaveBeenCalledTimes(1)
    expect(mocks.catalog).toHaveBeenCalledTimes(1)
    await setVisible(false)
    expect(model.setEmbeddedActive).toHaveBeenLastCalledWith(false)
    expect(model.destroy).not.toHaveBeenCalled()
    expect(model.stopLipSync).toHaveBeenCalledTimes(1)
    expect(vi.getTimerCount()).toBe(0)
    const configCalls = model.applyBrowserConfig.mock.calls.length
    const fitCalls = model.fitEmbeddedModelToViewport.mock.calls.length
    window.dispatchEvent(new CustomEvent('yuizaki:input-action', { detail: { action: 'lock' } }))
    window.dispatchEvent(new CustomEvent('pet:tts-play-url', { detail: { audio_url: '/hidden.wav' } }))
    resizeCallback([], {} as ResizeObserver)
    await vi.advanceTimersByTimeAsync(10_000)
    expect(mocks.catalog).toHaveBeenCalledTimes(1)
    expect(model.fitEmbeddedModelToViewport).toHaveBeenCalledTimes(fitCalls)
    expect(model.applyBrowserConfig).toHaveBeenCalledTimes(configCalls)
    expect(mocks.resolveUrl).not.toHaveBeenCalled()
    model.resizeTo.mockClear()
    await setVisible(true)
    expect(model.setEmbeddedActive).toHaveBeenLastCalledWith(true)
    expect(model.resizeTo).toHaveBeenCalledWith(400, 600)
    expect(mocks.catalog).toHaveBeenCalledTimes(2)
    expect(mocks.init).toHaveBeenCalledTimes(1)
    expect(mocks.load).toHaveBeenCalledTimes(1)
    window.dispatchEvent(new CustomEvent('yuizaki:input-action', { detail: { action: 'lock' } }))
    expect(model.applyBrowserConfig).toHaveBeenLastCalledWith({ interactMode: false, locked: true, clickThrough: false })
    await vi.advanceTimersByTimeAsync(2500)
    await flush()
    expect(mocks.catalog).toHaveBeenCalledTimes(3)
  })

  it('does not initialize a model from a catalog that arrives after deactivation', async () => {
    let release!: (catalog: unknown) => void
    mocks.catalog.mockImplementationOnce(() => new Promise(resolve => { release = resolve }))
    await mount()
    await setVisible(false)
    release({ models: [{ id: 'a', type: 'live2d', assetPath: '/a.json' }] })
    await flush()
    expect(mocks.init).not.toHaveBeenCalled()
    expect(vi.getTimerCount()).toBe(0)
    await setVisible(true)
    expect(mocks.init).toHaveBeenCalledTimes(1)
    expect(mocks.load).toHaveBeenCalledTimes(1)
  })

  it('does not begin WebGL initialization when Cubism resolves while inactive', async () => {
    let release!: () => void
    mocks.core.mockImplementationOnce(() => new Promise<void>(resolve => { release = resolve }))
    await mount()
    await setVisible(false)
    release()
    await flush()
    expect(mocks.init).not.toHaveBeenCalled()
    expect(vi.getTimerCount()).toBe(0)
    await setVisible(true)
    expect(mocks.init).toHaveBeenCalledTimes(1)
  })

  it('destroys a pending WebGL candidate and retries on activation after its late init', async () => {
    let release!: () => void
    mocks.init.mockImplementationOnce(() => new Promise<void>(resolve => { release = resolve }))
    await mount()
    const candidate = mocks.instances[0]!
    await setVisible(false)
    expect(candidate.setEmbeddedActive).toHaveBeenLastCalledWith(false)
    expect(candidate.destroy).toHaveBeenCalled()
    release()
    await flush()
    expect(mocks.load).not.toHaveBeenCalled()
    expect(vi.getTimerCount()).toBe(0)
    await setVisible(true)
    expect(mocks.instances).toHaveLength(2)
    expect(mocks.instances[1]!.path).toBe('/a.json')
  })

  it('preserves the working model when an inactive replacement resolves after reactivation', async () => {
    await mount()
    const working = mocks.instances[0]!
    let release!: () => void
    mocks.load.mockImplementationOnce(() => new Promise<void>(resolve => { release = resolve }))
    mocks.modelId = 'b'
    await vi.advanceTimersByTimeAsync(2500)
    await flush()
    const stale = mocks.instances[1]!
    await setVisible(false)
    expect(stale.destroy).toHaveBeenCalled()
    expect(working.destroy).not.toHaveBeenCalled()
    mocks.modelId = 'a'
    await setVisible(true)
    release()
    await flush()
    expect(mocks.instances).toHaveLength(2)
    expect(stale.applyBrowserConfig).toHaveBeenCalledTimes(1)
    expect(working.destroy).not.toHaveBeenCalled()
    expect(working.setEmbeddedActive).toHaveBeenLastCalledWith(true)
  })

  it('cancels delayed lip sync on deactivation even if the cached model returns first', async () => {
    await mount()
    let release!: (url: string) => void
    mocks.resolveUrl.mockImplementationOnce(() => new Promise<string>(resolve => { release = resolve }))
    window.dispatchEvent(new CustomEvent('pet:tts-play-url', { detail: { audio_url: '/old.wav' } }))
    const model = mocks.instances[0]!
    await setVisible(false)
    await setVisible(true)
    release('/old.wav')
    await flush()
    expect(model.startLipSync).not.toHaveBeenCalled()
    expect(model.stopLipSync).toHaveBeenCalledTimes(1)
  })

  it('ignores shell shortcuts and hidden zero sizes, then measures width again on activation', async () => {
    await mount(BrowserStageView)
    const state = Reflect.get(stageInstance, 'setupState') as Record<string, unknown>
    const main = state.mainEl as Element
    state.immersive = true
    state.chatOpen = false
    await setVisible(false)
    main.clientWidth = 0
    resizeCallback([{ contentRect: { width: 0 } }] as ResizeObserverEntry[], {} as ResizeObserver)
    window.dispatchEvent(new CustomEvent('yuizaki:input-action', { detail: { action: 'openPanel' } }))
    window.dispatchEvent(Object.assign(new Event('keydown'), { key: 'Escape' }))
    expect(state.immersive).toBe(true)
    expect(state.chatOpen).toBe(false)
    expect(state.mainWidth).toBe(1000)
    main.clientWidth = 800
    await setVisible(true)
    expect(state.mainWidth).toBe(800)
    window.dispatchEvent(new CustomEvent('yuizaki:input-action', { detail: { action: 'openPanel' } }))
    expect(state.chatOpen).toBe(true)
    window.dispatchEvent(Object.assign(new Event('keydown'), { key: 'Escape' }))
    expect(state.chatOpen).toBe(false)
  })

  it('refreshes immediately on reactivation and discards the previous activation catalog', async () => {
    let release!: (catalog: unknown) => void
    mocks.modelId = 'b'
    mocks.catalog.mockImplementationOnce(() => new Promise(resolve => { release = resolve }))
    await mount()
    await setVisible(false)
    mocks.modelId = 'a'
    await setVisible(true)
    expect(mocks.instances).toHaveLength(1)
    expect(mocks.instances[0]!.path).toBe('/a.json')
    release({ models: [{ id: 'b', type: 'live2d', assetPath: '/b.json' }] })
    await flush()
    expect(mocks.instances).toHaveLength(1)
    await vi.advanceTimersByTimeAsync(2500)
    await flush()
    expect(mocks.catalog).toHaveBeenCalledTimes(3)
  })

})
